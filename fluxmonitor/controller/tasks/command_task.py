
from tempfile import TemporaryFile
import logging
import glob
import os

from fluxmonitor.config import robot_config
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.err_codes import UNKNOW_COMMAND, NOT_EXIST, \
    TOO_LARGE, NO_TASK, BAD_PARAMS

from .base import CommandMixIn
from .play_task import PlayTask
from .scan_task import ScanTask
from .upload_task import UploadTask
from .raw_task import RawTask
from .maintain_task import MaintainTask

logger = logging.getLogger(__name__)


def empty_callback(*args):
    pass


class CommandTask(CommandMixIn):
    _task_file = None

    def __init__(self, server):
        self.server = server
        self.settings = CommonMetadata()
        self.filepool = os.path.abspath(robot_config["filepool"])

    def dispatch_cmd(self, cmd, sender):
        if cmd == "ls":
            return self.list_files(sender)
        elif cmd.startswith("select "):
            filename = cmd.split(" ", 1)[-1]
            return self.select_file(filename)
        elif cmd.startswith("upload "):
            filesize = cmd.split(" ", 1)[-1]
            return self.upload_file(int(filesize, 10), sender)
        elif cmd.startswith("scan"):
            return self.scan(sender)
        elif cmd == "start":
            return self.play(sender)
        elif cmd == "raw":
            return self.raw_access(sender)
        elif cmd == "maintain":
            return self.maintain(sender)
        elif cmd.startswith("set "):
            params = cmd.split(" ", 2)[1:]
            if len(params) != 2:
                raise RuntimeError(BAD_PARAMS)
            return self.setting_setter(*params)
        else:
            logger.debug("Can not handle: %s" % repr(cmd))
            raise RuntimeError(UNKNOW_COMMAND)

    def list_files(self, sender):
        # TODO: a rough method
        pool = self.filepool

        files = glob.glob(os.path.join(pool, "*.gcode")) + \
            glob.glob(os.path.join(pool, "*", "*.gcode")) + \
            glob.glob(os.path.join(pool, "*", "*", "*.gcode"))

        for file in files:
            sender.send_text("file " + file)

        return "ok"

    def select_file(self, filename, raw=False):
        abs_filename = os.path.abspath(
            os.path.join(robot_config["filepool"], filename))

        if not raw and not abs_filename.startswith(self.filepool):
            raise RuntimeError(NOT_EXIST)

        if not os.path.isfile(abs_filename) or \
           not abs_filename.endswith(".gcode"):
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
        self.server.enter_task(task, empty_callback)
        return "continue"

    def play(self, sender):
        if self._task_file:
            task = PlayTask(self.server, sender, self._task_file)
            self.server.enter_task(task, empty_callback)
            self._task_file = None
            return "ok"
        else:
            raise RuntimeError(NO_TASK)

    def scan(self, sender):
        task = ScanTask(self.server, sender)
        self.server.enter_task(task, empty_callback)
        return "ok"

    def maintain(self, sender):
        task = MaintainTask(self.server, sender)
        self.server.enter_task(task, empty_callback)
        return "ok"

    def setting_setter(self, key, raw_value):
        try:
            if key == "playbuf":
                self.settings.play_bufsize = int(raw_value)
                return "ok"
            else:
                raise RuntimeError(BAD_PARAMS, "NO_KEY %s" % key)
        except ValueError:
            raise RuntimeError(BAD_PARAMS)

    def setting_getter(self):
        pass
