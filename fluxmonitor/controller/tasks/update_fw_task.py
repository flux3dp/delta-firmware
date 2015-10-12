
from tempfile import TemporaryFile
from errno import errorcode
import logging
import socket

from fluxmonitor.err_codes import SUBSYSTEM_ERROR
from fluxmonitor.config import uart_config
from fluxmonitor.storage import Storage
from .base import ExclusiveMixIn

logger = logging.getLogger(__name__)


class UpdateFwTask(ExclusiveMixIn):
    def __init__(self, server, sender, length):
        super(UpdateFwTask, self).__init__(server, sender)
        self.tmpfile = TemporaryFile()
        self.padding_length = length
        sender.binary_mode = True

    def on_exit(self, sender):
        pass

    def send_upload_request(self):
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(uart_config["control"])
            s.send("update_fw")
        except socket.error:
            raise RuntimeError(SUBSYSTEM_ERROR)

    def on_owner_message(self, message, sender):
        try:
            l = len(message)

            if self.padding_length > l:
                self.tmpfile.write(message)
                self.padding_length -= l

            else:
                if self.padding_length == l:
                    self.tmpfile.write(message)
                else:
                    self.tmpfile.write(message[:self.padding_length])
                sender.binary_mode = False

                self.tmpfile.seek(0)
                s = Storage("update_fw")
            
                with s.open("mainboard.bin", "wb") as f:
                    f.write(self.tmpfile.read())

                logging.warn("Fireware uploaded, start processing")
                self.send_upload_request()
                sender.send_text("ok")

                self.server.exit_task(self, True)
        except RuntimeError as e:
            sender.send_text(("error %s" % e.args[0]).encode())
        except Exception:
            logger.exception("Unhandle Error")
            sender.send_text("error %s" % UNKNOW_ERROR)

