"""
This test file uses the https://github.com/esheldon/fitsio package to verify
our compression and decompression routines against the implementation in
cfitsio.

*Note*: The fitsio library is GPL licensed, therefore it could be interpreted
 that so is this test file. Given that this test file isn't imported anywhere
 else in the code this shouldn't cause us any issues. Please bear this in mind
 when editing this file.
"""
import os

import numpy as np
import pytest

from astropy.io import fits

from .conftest import _expand

# This is so that tox can force this file to be run, and not be silently
# skipped on CI, but in all other test runs it's skipped.
if "ASTROPY_ALWAYS_TEST_FITSIO" in os.environ:
    import fitsio
else:
    fitsio = pytest.importorskip("fitsio")


@pytest.fixture(scope="session")
def numpy_rng():
    return np.random.default_rng()


@pytest.fixture(
    scope="module",
    params=_expand(
        [((10,),), ((5,), (1,), (3,))],
        [((12, 12),), ((1, 12), (4, 5), (6, 6))],
        [((15, 15),), ((1, 15), (5, 1), (5, 5))],
        [
            ((15, 15, 15),),
            ((5, 5, 1), (5, 7, 1), (1, 5, 4), (1, 1, 15), (15, 1, 5)),
        ],
        # >3D Data are not currently supported by cfitsio
        # [
        #     ((15, 15, 15, 15),),
        #     (
        #         (5, 5, 5, 5),
        #         (1, 5, 1, 5),
        #         (3, 1, 4, 5),
        #     ),
        # ],
    ),
    ids=lambda x: f"shape: {x[0]} tile_dims: {x[1]}",
)
def array_shapes_tile_dims(request, compression_type):
    shape, tile_dim = request.param
    # H_COMPRESS needs >=2D data and always 2D tiles
    if compression_type == "HCOMPRESS_1" and (
        len(shape) < 2 or np.count_nonzero(np.array(tile_dim) != 1) != 2
    ):
        pytest.xfail("HCOMPRESS is 2D only apparently")
    return shape, tile_dim


@pytest.fixture(scope="module")
def tile_dims(array_shapes_tile_dims):
    return array_shapes_tile_dims[1]


@pytest.fixture(scope="module")
def data_shape(array_shapes_tile_dims):
    return array_shapes_tile_dims[0]


@pytest.fixture(scope="module")
def base_original_data(data_shape, dtype, numpy_rng, compression_type):
    random = numpy_rng.uniform(high=255, size=data_shape)
    # There seems to be a bug with the fitsio library where HCOMPRESS doesn't
    # work with int16 random data, so use a bit for structured test data.
    if compression_type.startswith("HCOMPRESS") and "i2" in dtype or "u1" in dtype:
        random = np.arange(np.product(data_shape)).reshape(data_shape)
    return random.astype(dtype)


@pytest.fixture(scope="module")
def fitsio_compressed_file_path(
    tmp_path_factory,
    comp_param_dtype,
    base_original_data,
    data_shape,  # For debuging
    tile_dims,
):
    compression_type, param, dtype = comp_param_dtype
    if base_original_data.ndim > 2 and "u1" in dtype:
        pytest.xfail("These don't work")
    tmp_path = tmp_path_factory.mktemp("fitsio")
    original_data = base_original_data.astype(dtype)

    filename = tmp_path / f"{compression_type}_{dtype}.fits"
    fits = fitsio.FITS(filename, "rw")
    fits.write(original_data, compress=compression_type, tile_dims=tile_dims, **param)

    return filename


@pytest.fixture(scope="module")
def astropy_compressed_file_path(
    comp_param_dtype,
    tmp_path_factory,
    base_original_data,
    data_shape,  # For debuging
):
    compression_type, param, dtype = comp_param_dtype
    original_data = base_original_data.astype(dtype)

    tmp_path = tmp_path_factory.mktemp("astropy")
    filename = tmp_path / f"{compression_type}_{dtype}.fits"
    # Convert fitsio kwargs to astropy kwargs
    _map = {"qlevel": "quantize_level"}
    param = {_map[k]: v for k, v in param.items()}

    # Map quantize_level
    if param.get("quantize_level", "missing") is None:
        param["quantize_level"] = 0.0

    hdu = fits.CompImageHDU(
        data=original_data, compression_type=compression_type, **param
    )
    hdu.writeto(filename)

    return filename


def test_decompress(
    fitsio_compressed_file_path,
    base_original_data,
    compression_type,
    dtype,
):

    with fits.open(fitsio_compressed_file_path) as hdul:
        data = hdul[1].data

        assert hdul[1]._header["ZCMPTYPE"] == compression_type
        assert hdul[1].data.dtype.kind == np.dtype(dtype).kind
        assert hdul[1].data.dtype.itemsize == np.dtype(dtype).itemsize
        # assert hdul[1].data.dtype.byteorder == np.dtype(dtype).byteorder
    np.testing.assert_allclose(data, base_original_data)


def test_compress(
    astropy_compressed_file_path,
    base_original_data,
    compression_type,
    dtype,
):
    fits = fitsio.FITS(astropy_compressed_file_path, "r")
    header = fits[1].read_header()
    data = fits[1].read()

    assert header["ZCMPTYPE"] == compression_type
    assert data.dtype.kind == np.dtype(dtype).kind
    assert data.dtype.itemsize == np.dtype(dtype).itemsize
    # assert data.dtype.byteorder == np.dtype(dtype).byteorder
    np.testing.assert_allclose(data, base_original_data)