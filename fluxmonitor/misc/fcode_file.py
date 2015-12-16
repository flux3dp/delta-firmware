
from zipfile import crc32
import struct

INT_PACKER = struct.Struct("<i")
UINT_PACKER = struct.Struct("<I")


class FCodeFile(object):
    def __init__(self, filename):
        with open(filename, "rb") as f:
            self._load(f)

    def _load(self, f):
        if f.read(8) != b"FCx0001\n":
            raise FCodeError("HEADER_ERROR")

        script_size = UINT_PACKER.unpack(f.read(4))[0]
        script_crc32 = 0
        f_ptr = 0

        self.script_ptr = f.tell()
        self.script_size = script_size

        while f_ptr < script_size:
            buf = f.read(min(script_size - f_ptr, 4096))
            if buf:
                f_ptr += len(buf)
                script_crc32 = crc32(buf, script_crc32)
            else:
                raise FCodeError("SIZE_ERROR", "SCRIPT")

        req_script_crc32 = INT_PACKER.unpack(f.read(4))[0]
        if req_script_crc32 != script_crc32:
            raise FCodeError("CRC_ERROR", "SCRIPT")

        # Check meta
        meta_size = UINT_PACKER.unpack(f.read(4))[0]
        meta_buf = f.read(meta_size)
        req_metadata_crc32 = INT_PACKER.unpack(f.read(4))[0]
        if req_metadata_crc32 != crc32(meta_buf, 0):
            raise FCodeError("CRC_ERROR", "META")

        metadata = {}
        for item in meta_buf.split("\x00"):
            sitem = item.split("=", 1)
            if len(sitem) == 2:
                metadata[sitem[0]] = sitem[1]
        self.metadata = metadata

        # Load image
        image_size = UINT_PACKER.unpack(f.read(4))[0]
        self.image_buf = f.read(image_size)


class FCodeError(Exception):
    pass
