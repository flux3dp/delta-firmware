
# s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM); s.connect("/tmp/.uart-control"); s.send("update_fw")


from tempfile import TemporaryFile
import logging
import socket

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
                s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                s.connect("/tmp/.uart-control")
                s.send("update_fw")
            
                sender.send_text("ok")

                self.server.exit_task(self, True)
        except Exception:
            logger.exception("Unhandle Error")
