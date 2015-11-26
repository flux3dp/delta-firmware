
import logging

from fluxmonitor.err_codes import TOO_LARGE, PROTOCOL_ERROR

logger = logging.getLogger(__name__)


class UploadTask(object):
    def __init__(self, stack, handler, task_file, length):
        self.stack = stack
        self.task_file = task_file
        self.padding_length = length
        handler.binary_mode = True

    def on_exit(self, handler):
        pass

    def on_text(self, message, handler):
        raise SystemError(PROTOCOL_ERROR, "UPLOADING_BINARY")

    def on_binary(self, buf, handler):
        l = len(buf)

        if self.padding_length > l:
            self.task_file.write(buf)
            self.padding_length -= l

        elif self.padding_length == l:
            self.task_file.write(buf)
            handler.binary_mode = False
            handler.send_text("ok")
            self.stack.exit_task(self, True)

        else:
            raise SystemError(TOO_LARGE)
