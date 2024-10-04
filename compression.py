import zlib


def deflate_decompress(data: bytes) -> bytes:
    return zlib.decompress(data, -zlib.MAX_WBITS)


def deflate_compress(data: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()
