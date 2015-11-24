
from tempfile import TemporaryFile
from errno import errorcode
import logging
import socket

from fluxmonitor.err_codes import TOO_LARGE, PROTOCOL_ERROR, SUBSYSTEM_ERROR
from fluxmonitor.config import uart_config
from fluxmonitor.storage import Storage

logger = logging.getLogger(__name__)


class UpdateFwTask(object):
    def __init__(self, stack, handler, length):
        self.stack = stack
        self.tmpfile = TemporaryFile()
        self.padding_length = length
        handler.binary_mode = True

    def on_exit(self, handler):
        pass

    def on_text(self, message, handler):
        raise ProtocolError(PROTOCOL_ERROR, "UPLOADING_BINARY")

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

                self.server.exit_task(self, True)
        except RuntimeError as e:
            handler.send_text(("error %s" % e.args[0]).encode())
        except Exception:
            logger.exception("Unhandle Error")
            handler.send_text("error %s" % UNKNOW_ERROR)

    def send_upload_request(self):
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(uart_config["control"])
            s.send("update_fw")
        except socket.error:
            raise RuntimeError(SUBSYSTEM_ERROR)

