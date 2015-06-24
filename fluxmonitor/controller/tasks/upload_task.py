
import logging

from fluxmonitor.err_codes import RESOURCE_BUSY
from .base import ExclusiveMixIn

logger = logging.getLogger(__name__)


class UploadTask(ExclusiveMixIn):
    def __init__(self, server, sender, task_file, length):
        super(UploadTask, self).__init__(server, sender)
        self.task_file = task_file
        self.padding_length = length
        sender.binary_mode = True

    def on_message(self, message, sender):
        if self.owner() == sender:
            l = len(message)

            if self.padding_length > l:
                self.task_file.write(message)
                self.padding_length -= l

            else:
                if self.padding_length == l:
                    self.task_file.write(message)
                else:
                    self.task_file.write(message[:self.padding_length])
                sender.binary_mode = False
                sender.send_text("ok")
                self.server.exit_task(self, True)

        else:
            if message.rstrip("\x00") == b"kick":
                self.on_dead(self.owner, "Kicked")
                sender.send("kicked")
            else:
                sender.send(("error %s uploding" % RESOURCE_BUSY).encode())
