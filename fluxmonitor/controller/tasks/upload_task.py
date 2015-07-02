
import logging

from .base import ExclusiveMixIn

logger = logging.getLogger(__name__)


class UploadTask(ExclusiveMixIn):
    def __init__(self, server, sender, task_file, length):
        super(UploadTask, self).__init__(server, sender)
        self.task_file = task_file
        self.padding_length = length
        sender.binary_mode = True

    def on_exit(self, sender):
        pass

    def on_owner_message(self, message, sender):
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
