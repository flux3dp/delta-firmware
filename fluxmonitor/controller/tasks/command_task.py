
from tempfile import TemporaryFile
from errno import errorcode
from io import StringIO
import logging
import shutil
import os

from fluxmonitor.config import robot_config
from fluxmonitor.storage import CommonMetadata
from fluxmonitor.err_codes import UNKNOW_COMMAND, NOT_EXIST, \
    TOO_LARGE, NO_TASK, BAD_PARAMS, BAD_FILE_FORMAT
from fluxmonitor.hal.usbmount import get_usbmount_hal

from .base import CommandMixIn
from .play_task import PlayTask
from .scan_task import ScanTask
from .upload_task import UploadTask
from .raw_task import RawTask
from .maintain_task import MaintainTask
from .update_fw_task import UpdateFwTask

logger = logging.getLogger(__name__)


def empty_callback(*args):
    pass


class FileManagerMixIn(object):
    def dispatch_filemanage_cmd(self, cmd, sender):
        if cmd.startswith("ls "):
            self.list_files(cmd[3:], sender)
            return True
        elif cmd.startswith("select "):
            self.select_file(cmd[7:], sender)
            return True
        elif cmd.startswith("fileinfo "):
            self.fileinfo(cmd[9:], sender)
            return True
        elif cmd.startswith("mkdir "):
            self.mkdir(cmd[6:], sender)
            return True
        elif cmd.startswith("rmdir "):
            self.rmdir(cmd[6:], sender)
            return True
        elif cmd.startswith("cp "):
            self.cpfile(cmd[3:], sender)
            return True
        elif cmd.startswith("rm "):
            self.rmfile(cmd[3:], sender)
            return True
        elif cmd.startswith("upload "):
            filesize = cmd.split(" ", 1)[-1]
            self.upload_file(int(filesize, 10), sender)
            return True
        else:
            return False

    def _storage_dispatch(self, rawpath, sd_only=False, require_file=False,
                          require_dir=False):
        if rawpath.startswith("SD "):
            entry, path = self.filepool, rawpath[3:]
        elif rawpath.startswith("USB "):
            if sd_only:
                raise RuntimeError(BAD_PARAMS, "USB_NOT_ACCESSABLE")
            filepool = self.usbmount.get_entry()
            if filepool:
                entry, path = filepool, rawpath[4:]
            else:
                raise RuntimeError(NOT_EXIST, "BAD_NODE")
        else:
            raise RuntimeError(NOT_EXIST, "BAD_ENTRY")

        abspath = os.path.realpath(os.path.join(entry, path))
        if not abspath.startswith(entry):
            raise RuntimeError(NOT_EXIST, "SECURITY_ISSUE")
        if require_file and (not os.path.isfile(abspath)):
            raise RuntimeError(NOT_EXIST, "NOT_FILE")
        if require_dir and (not os.path.isdir(abspath)):
            raise RuntimeError(NOT_EXIST, "NOT_DIR")
        return abspath

    def list_files(self, path, sender):
        abspath = self._storage_dispatch(path, require_dir=True).decode("utf8")

        buf_obj = StringIO()
        for n in os.listdir(abspath):
            # python2 encoding issue ...
            if not isinstance(n, unicode):
                # python2 encoding issue ...
                n = n.decode("utf8")
            # python2 encoding issue ...
            node = os.path.join(abspath, n).encode("utf8")
            if os.path.isdir(node):
                buf_obj.write(u"D%s\x00" % n)
            elif node.endswith(".fcode"):
                buf_obj.write(u"F%s\x00" % n)
            elif node.endswith(".gcode"):
                buf_obj.write(u"F%s\x00" % n)

        buf = buf_obj.getvalue()
        sender.send_text("continue")
        sender.send_text(buf.encode("utf8"))
        sender.send_text("ok")

    def select_file(self, path, sender, raw=False):
        if raw:
            abspath = os.path.realpath(path)
        else:
            abspath = self._storage_dispatch(path, require_file=True)

        if not os.path.isfile(abspath):
            raise RuntimeError(NOT_EXIST, "NOT_FILE")

        self._task_file = open(abspath, "rb")
        sender.send_text("ok")

    def fileinfo(self, path, sender):
        abspath = self._storage_dispatch(path, require_file=True)
        if abspath.endswith(".gcode"):
            sender.send_text("ok size=%i" % os.path.getsize(abspath))
        elif abspath.endswith(".fcode"):
            sender.send_text("ok size=%i" % os.path.getsize(abspath))
        else:
            raise RuntimeError(BAD_FILE_FORMAT)

    def mkdir(self, path, sender):
        abspath = self._storage_dispatch(path, sd_only=True)
        try:
            os.mkdir(abspath)
            sender.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def rmdir(self, path, sender):
        abspath = self._storage_dispatch(path, sd_only=True, require_dir=True)
        if abspath == os.path.realpath(self.filepool):
            raise RuntimeError("OSERR_EACCES")

        try:
            shutil.rmtree(abspath)
            sender.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def cpfile(self, path, sender):
        try:
            source, target = path.split("\x00", 1)
            abssource = self._storage_dispatch(source, require_file=True)
            abstarget = self._storage_dispatch(target, sd_only=True)
            shutil.copy(abssource, abstarget)
            sender.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))
        except ValueError as e:
            raise RuntimeError(BAD_PARAMS)

    def rmfile(self, path, sender):
        try:
            abspath = self._storage_dispatch(path, sd_only=True,
                                             require_file=True)
            os.remove(abspath)
            sender.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def upload_file(self, filesize, sender):
        if filesize > 2 ** 30:
            raise RuntimeError(TOO_LARGE)

        self._task_file = TemporaryFile()

        logger.debug("Upload task file size: %i" % filesize)

        task = UploadTask(self.server, sender, self._task_file, filesize)
        self.server.enter_task(task, self.end_upload_file)
        sender.send_text("continue")

    def end_upload_file(self, is_success):
        if is_success:
            self._task_file.seek(0)
        else:
            self._task_file.close()
            self._task_file = None


class CommandTask(CommandMixIn, FileManagerMixIn):
    _task_file = None

    def __init__(self, server):
        self.server = server
        self.settings = CommonMetadata()
        self.usbmount = get_usbmount_hal()
        self.filepool = os.path.realpath(robot_config["filepool"])

    def dispatch_cmd(self, cmd, sender):
        if self.dispatch_filemanage_cmd(cmd, sender):
            pass
        elif cmd.startswith("scan"):
            return self.scan(sender)
        elif cmd == "start":
            return self.play(sender)
        elif cmd == "raw":
            return self.raw_access(sender)
        elif cmd == "maintain":
            return self.maintain(sender)
        elif cmd.startswith("update_fw "):
            filesize = cmd.split(" ", 1)[-1]
            return self.update_fw(int(filesize, 10), sender)
        elif cmd.startswith("set "):
            params = cmd.split(" ", 2)[1:]
            if len(params) != 2:
                raise RuntimeError(BAD_PARAMS)
            return self.setting_setter(*params)
        else:
            logger.debug("Can not handle: %s" % repr(cmd))
            raise RuntimeError(UNKNOW_COMMAND)

    def update_fw(self, filesize, sender):
        if filesize > 2 ** 20:
            raise RuntimeError(TOO_LARGE)

        logger.info("Upload fireware file size: %i" % filesize)
        task = UpdateFwTask(self.server, sender, filesize)
        self.server.enter_task(task, empty_callback)

        return "continue"

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
