
from tempfile import NamedTemporaryFile
import logging
import socket
import shutil
import os

from fluxmonitor.err_codes import PROTOCOL_ERROR, SUBSYSTEM_ERROR, \
    FILE_BROKEN, UNKNOWN_ERROR
from fluxmonitor.config import FIRMWARE_UPDATE_PATH, HALCONTROL_ENDPOINT
from fluxmonitor.storage import Storage

logger = logging.getLogger(__name__)


class UpdateFwTask(object):
    def __init__(self, stack, handler, length):
        self.stack = stack
        self.tmpfile = NamedTemporaryFile()
        self.padding_length = length
        handler.binary_mode = True

    def on_exit(self):
        pass

    def on_text(self, message, handler):
        raise SystemError(PROTOCOL_ERROR, "UPLOADING_BINARY")

    def on_binary(self, buf, handler):
        try:
            l = len(buf)

            if self.padding_length > l:
                self.tmpfile.write(buf)
                self.padding_length -= l

            else:
                if self.padding_length == l:
                    self.tmpfile.write(buf)
                else:
                    self.tmpfile.write(buf[:self.padding_length])
                    logger.error("Recv data length error")

                handler.binary_mode = False

                logger.info("New firmware received")
                self.tmpfile.file.flush()
                self.tmpfile.seek(0)
                s = Storage("update_fw")
                with s.open("upload.fxfw", "wb") as f:
                    f.write(self.tmpfile.read())
                ret = os.system("fxupdate.py --dryrun %s" % self.tmpfile.name)
                logger.info("Firmware verify: %s", ret)

                if ret:
                    handler.send_text("error %s" % FILE_BROKEN)
                else:
                    shutil.copyfile(self.tmpfile.name, FIRMWARE_UPDATE_PATH)
                    handler.send_text("ok")
                    handler.close()
                    os.system("reboot")

                self.stack.exit_task(self, True)
        except RuntimeError as e:
            handler.send_text(("error %s" % e.args[0]).encode())
        except Exception:
            logger.exception("Unhandle Error")
            handler.send_text("error %s" % UNKNOWN_ERROR)

    def send_upload_request(self):
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(HALCONTROL_ENDPOINT)
            s.send("update_fw")
        except socket.error:
            raise RuntimeError(SUBSYSTEM_ERROR)
