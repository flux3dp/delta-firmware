
from zipfile import crc32
import struct

from fluxmonitor.err_codes import FILE_BROKEN

INT_PACKER = struct.Struct("<i")
UINT_PACKER = struct.Struct("<I")


def fast_read_meta(filename):
    with open(filename, "rb") as f:
        try:
            # Check header
            assert f.read(8) == b"FCx0001\n", "MAGIC_NUMBER_ERROR"

            # Skip script size/crc32/body
            script_size = UINT_PACKER.unpack(f.read(4))[0]
            f.seek(script_size + 4, 1)  # crc32 + size

            # Load metadata
            meta_size = UINT_PACKER.unpack(f.read(4))[0]
            assert meta_size < 65536, "METADATA_TOO_LARGE"
            meta_buf = f.read(meta_size)
            meta_crc32 = INT_PACKER.unpack(f.read(4))[0]
            assert meta_crc32 == crc32(meta_buf, 0), "METADATA_CRC32_ERROR"

            metadata = {}
            for item in meta_buf.split("\x00"):
                sitem = item.split("=", 1)
                if len(sitem) == 2:
                    metadata[sitem[0]] = sitem[1]

            # Load image
            images = []
            size_buf = f.read(4)
            while len(size_buf) == 4:
                img_s = UINT_PACKER.unpack(size_buf)[0]
                if img_s > 0:
                    images.append(f.read(img_s))
                    size_buf = f.read(4)
                else:
                    break
            return metadata, images

        except struct.error as e:
            raise RuntimeError(FILE_BROKEN)
        except AssertionError as e:
            raise RuntimeError(FILE_BROKEN, e.args[0] if e.args else "#")
