
from tempfile import TemporaryFile
import logging
import glob
import json
import os

from fluxmonitor.config import robot_config
from fluxmonitor.err_codes import UNKNOW_COMMAND, NOT_EXIST, \
    TOO_LARGE, NO_TASK, RESOURCE_BUSY
from .tasks_base import ExclusiveTaskBase, DeviceOperationMixIn, \
    CommandTaskBase
from .play_task import PlayTask

logger = logging.getLogger(__name__)


class CommandTask(CommandTaskBase):
    _task_file = None

    def __init__(self, server):
        self.server = server
        self.filepool = os.path.abspath(robot_config["filepool"])

    def dispatch_cmd(self, cmd, sender):
        if cmd == "ls":
            return self.list_files()
        elif cmd.startswith("select "):
            filename = cmd.split(" ", 1)[-1]
            return self.select_file(filename)
        elif cmd.startswith("upload "):
            filesize = cmd.split(" ", 1)[-1]
            return self.upload_file(int(filesize, 10), sender)
        elif cmd == "raw":
            return self.raw_access(sender)
        elif cmd == "start":
            return self.play(sender)
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    def list_files(self):
        # TODO: a rough method
        pool = self.filepool

        files = glob.glob(os.path.join(pool, "*.gcode")) + \
            glob.glob(os.path.join(pool, "*", "*.gcode")) + \
            glob.glob(os.path.join(pool, "*", "*", "*.gcode"))

        return json.dumps(files)

    def select_file(self, filename):
        abs_filename = os.path.abspath(
            os.path.join(robot_config["filepool"], filename))

        if not abs_filename.startswith(self.filepool) or \
           not abs_filename.endswith(".gcode") or \
           not os.path.isfile(abs_filename):
                raise RuntimeError(NOT_EXIST)

        self._task_file = open(filename, "rb")
        return "ok"

    def upload_file(self, filesize, sender):
        if filesize > 2 ** 30:
            raise RuntimeError(TOO_LARGE)

        self._task_file = TemporaryFile()

        logger.info("Upload task file size: %i" % filesize)

        task = UploadTask(self.server, sender, self._task_file, filesize)
        self.server.enter_task(task, self.end_upload_file)

        return "continue"

    def end_upload_file(self, is_success):
        if is_success:
            self._task_file.seek(0)
        else:
            self._task_file.close()
            self._task_file = None

    def raw_access(self, sender):
        task = RawTask(self.server, sender)
        self.server.enter_task(task, self.end_no_result_task)
        return "continue"

    def play(self, sender):
        if self._task_file:
            task = PlayTask(self.server, sender, self._task_file)
            self.server.enter_task(task, self.end_no_result_task)
            self._task_file = None
            return "ok"
        else:
            raise RuntimeError(NO_TASK)

    def end_no_result_task(self, *args):
        pass


class UploadTask(ExclusiveTaskBase):
    def __init__(self, server, sender, task_file, length):
        super(UploadTask, self).__init__(server, sender)
        self.task_file = task_file
        self.padding_length = length

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
                sender.send(b"ok")
                self.server.exit_task(self, True)

        else:
            if message.rstrip("\x00") == b"kick":
                self.on_dead(self.owner, "Kicked")
                sender.send("kicked")
            else:
                sender.send(("error %s uploding" % RESOURCE_BUSY).encode())


class RawTask(ExclusiveTaskBase, DeviceOperationMixIn):
    def __init__(self, server, sender):
        super(RawTask, self).__init__(server, sender)
        self.connect()

    def on_dead(self, sender, reason=None):
        try:
            self.disconnect()
        finally:
            super(RawTask, self).on_dead(sender, reason)

    def on_mainboard_message(self, sender):
        try:
            buf = sender.obj.recv(4096)
            self.owner().send(buf)
        except Exception as e:
            self.on_dead(repr(e))

    def on_headboard_message(self, sender):
        try:
            buf = sender.obj.recv(4096)
            self.owner().send(buf)
        except Exception as e:
            self.on_dead(repr(e))

    def on_message(self, buf, sender):
        buf = buf.rstrip("\x00")

        if self.owner() == sender:
            if buf == b"quit":
                sender.send(b"ok")
                self.disconnect()
                self.server.exit_task(self, True)
            else:
                self._uart_mb.send(buf)
        else:
            if buf == b"kick":
                self.on_dead(self.sender, "Kicked")
                sender.send("kicked")
            else:
                sender.send(("error %s raw" % RESOURCE_BUSY).encode())
