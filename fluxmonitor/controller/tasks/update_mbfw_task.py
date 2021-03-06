from tempfile import TemporaryFile
import logging

from fluxmonitor.interfaces.hal_internal import HalControlClientHandler
from fluxmonitor.err_codes import PROTOCOL_ERROR, SUBSYSTEM_ERROR, \
    UNKNOWN_ERROR
from fluxmonitor.storage import Storage

logger = logging.getLogger(__name__)


class UpdateMbFwTask(object):
    def __init__(self, stack, handler, length):
        self.stack = stack
        self.tmpfile = TemporaryFile()
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
                handler.binary_mode = False

                self.tmpfile.seek(0)
                s = Storage("update_fw")

                with s.open("mainboard.bin", "wb") as f:
                    f.write(self.tmpfile.read())

                logging.warn("Fireware uploaded, start processing")
                self.send_upload_request()
                handler.send_text("ok")

                self.stack.exit_task(self, True)
        except RuntimeError as e:
            handler.send_text(("error %s" % e.args[0]).encode())
        except Exception:
            logger.exception("Unhandle Error")
            handler.send_text("error %s" % UNKNOWN_ERROR)

    def send_upload_request(self):
        try:
            h = HalControlClientHandler(self.stack)
            h.request_update_atmel()
            h.close()
        except IOError:
            raise RuntimeError(SUBSYSTEM_ERROR)
