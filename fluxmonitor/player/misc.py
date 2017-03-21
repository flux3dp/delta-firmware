
from multiprocessing import Process
from zipfile import crc32
from shutil import copyfile
from select import select
from time import time
import logging
import struct
import socket
import os

from setproctitle import setproctitle

from fluxmonitor.err_codes import FILE_BROKEN, NOT_SUPPORT
from fluxmonitor.storage import UserSpace

# G0_G1_CMD_PARSER = re.compile("G[0-1]( F(?P<F>[0-9]+))?( X(?P<X>[\-0-9.]+))?"
#                               "( Y(?P<Y>[\-0-9.]+))?( Z(?P<Z>[\-0-9.]+))?"
#                               "( E(?P<E>[\-0-9.]+))?( F(?P<F2>[0-9]+))?")
# G28_PARSER = re.compile("(^G28|\ G28)(\ |$)")
# T_PARSER = re.compile("(^T\d|\ T\d)(\ |$)")

logger = logging.getLogger("TaskLoader")
INT_PACKER = struct.Struct("<i")
UINT_PACKER = struct.Struct("<I")


def place_recent_file(filename):
    space = UserSpace()
    use_swap = False
    if not os.path.exists(space.get_path("SD", "Recent")):
        os.makedirs(space.get_path("SD", "Recent"))

    if os.path.abspath(filename). \
            startswith(space.get_path("SD", "Recent/recent-")):
        userspace_filename = "Recent/" + os.path.split(filename)[-1]
        space.mv("SD", userspace_filename, "Recent/swap.fc")
        filename = space.get_path("SD", "Recent/swap.fc")
        use_swap = True

    def place_file(syntax, index):
        name = syntax % index
        if space.exist("SD", name):
            if index >= 5:
                space.rm("SD", name)
            else:
                place_file(syntax, index + 1)
                space.mv("SD", name, syntax % (index + 1))

    place_file("Recent/recent-%i.fc", 1)
    if use_swap:
        space.mv("SD", "Recent/swap.fc", "Recent/recent-1.fc")
    elif space.in_entry("SD", filename):
        os.link(filename,
                space.get_path("SD", "Recent/recent-1.fc"))
    else:
        copyfile(filename,
                 space.get_path("SD", "Recent/recent-1.fc"))
    os.system("sync")


class TaskLoader(Process):
    """
    Useable property:
        loader.fileno() - Endpoint to read stream data
        loader.close() - Close io and subprocess
        loader.script_size - Entire script size (bytes)
        loader.io_progress - Script alread readed (bytes)
        loader.metadata - Dict store metadata in file
    """

    def _check_task(self, task_file):
        t = task_file

        # Check header
        magic_num = t.read(8)
        if magic_num != b"FCx0001\n":
            if magic_num[:3] != b"FCx" or magic_num[3:].isdigit() is False:
                raise RuntimeError(FILE_BROKEN)
            else:
                ver = int(magic_num[3:])
                raise RuntimeError(FILE_BROKEN, NOT_SUPPORT, str(ver))

        # Check script
        script_size = UINT_PACKER.unpack(t.read(4))[0]
        script_crc32 = 0
        f_ptr = 0

        self.script_ptr = t.tell()
        self.script_size = script_size

        while f_ptr < script_size:
            buf = t.read(min(script_size - f_ptr, 4096))
            if buf:
                f_ptr += len(buf)
                script_crc32 = crc32(buf, script_crc32)
            else:
                raise RuntimeError(FILE_BROKEN, "LENGTH_ERROR")

        req_script_crc32 = INT_PACKER.unpack(t.read(4))[0]
        if req_script_crc32 != script_crc32:
            raise RuntimeError(FILE_BROKEN, "SCRIPT_CRC32")

        # Check meta
        meta_size = UINT_PACKER.unpack(t.read(4))[0]
        meta_buf = t.read(meta_size)
        req_metadata_crc32 = INT_PACKER.unpack(t.read(4))[0]
        if req_metadata_crc32 != crc32(meta_buf, 0):
            raise RuntimeError(FILE_BROKEN, "METADATA_CRC32")

        metadata = {}
        for item in meta_buf.split("\x00"):
            sitem = item.split("=", 1)
            if len(sitem) == 2:
                metadata[sitem[0]] = sitem[1]
        self.metadata = metadata

        t.seek(self.script_ptr)

    def __init__(self, task_file):
        self._check_task(task_file)
        self.task_file = task_file

        self.io_in, self.io_out = socket.socketpair()

        super(TaskLoader, self).__init__(target=self.__serve_forever)
        self.daemon = True
        self.start()

        self.fout = self.io_out.makefile("rb", -1)

        # Remember to close after forked !!
        self.io_in.close()
        del self.io_in

    @property
    def io_progress(self):
        return self.task_file.tell() - 12

    def __serve_forever(self):
        setproctitle("fluxplayer: TaskLoader")
        logger.debug("TaskLoader forked")

        self.io_out.close()
        del self.io_out

        try:
            readed = 0
            buf = bytearray(4096)
            view = memoryview(buf)

            while readed < self.script_size:
                l = self.task_file.readinto(buf)
                if l == 0:
                    # EOF
                    return
                elif readed + l < self.script_size:
                    readed += l
                else:
                    l = self.script_size - readed
                    readed = self.script_size

                offset = 0
                while offset < l:
                    rl, wl, _ = select((self.io_in, ), (self.io_in, ), (), 3.0)
                    if rl:
                        # Remote should not send anything, close socket
                        # directory
                        return
                    if wl:
                            offset += self.io_in.send(view[offset:l])

            logger.debug("TaskLoader close normally")
        except KeyboardInterrupt:
            pass
        except Exception:
            logger.exception("TaskLoader close with error")

        finally:
            self.io_in.shutdown(socket.SHUT_WR)
            t = time()
            while not select((self.io_in, ), (), (), 3)[0]:
                # Wait for remote close socket
                if time() - t > 28800:
                    # if wait for more then 8hr, interrupt it.
                    break
            self.io_in.close()

    def fileno(self):
        return self.fout.fileno()

    def close(self):
        self.io_out.close()
        self.fout.close()
        self.task_file.close()

        if self.is_alive():
            self.terminate()
