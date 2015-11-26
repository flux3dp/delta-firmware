
from __future__ import absolute_import

from tempfile import NamedTemporaryFile
from errno import errorcode
from io import StringIO
from md5 import md5
import logging
import shutil
import os

from fluxmonitor.player.fcode_parser import fast_read_meta
from fluxmonitor.err_codes import (UNKNOW_COMMAND, NOT_EXIST, TOO_LARGE, NO_TASK, BAD_PARAMS, BAD_FILE_FORMAT, RESOURCE_BUSY)
from fluxmonitor.storage import CommonMetadata, UserSpace
from fluxmonitor.misc import mimetypes

from .base import CommandMixIn
from .scan_task import ScanTask
from .upload_task import UploadTask
from .raw_task import RawTask
from .maintain_task import MaintainTask
from .update_fw_task import UpdateFwTask
from .play_manager import PlayerManager

logger = logging.getLogger(__name__)


def empty_callback(*args):
    pass


class FileManagerMixIn(object):
    def dispatch_filemanage_cmd(self, handler, cmd, *args):
        if cmd == "ls":
            self.list_files(handler, *args)
            return True
        elif cmd == "select":
            self.select_file(handler, *args)
            return True
        elif cmd == "fileinfo":
            self.fileinfo(handler, *args)
            return True
        elif cmd == "mkdir":
            self.mkdir(handler, *args)
            return True
        elif cmd == "rmdir":
            self.rmdir(handler, *args)
            return True
        elif cmd == "cp":
            self.cpfile(handler, *args)
            return True
        elif cmd == "rm":
            self.rmfile(handler, *args)
            return True
        elif cmd == "upload":
            # upload [mimetype] [size] [entry] [path]
            self.upload_file(handler, *args)
            return True
        elif cmd == "md5":
            self.md5(handler, *args)
            return True
        else:
            return False

    def _storage_dispatch(self, entry, path, sd_only=False, require_file=False,
                          require_dir=False):
        return self.user_space.get_path(entry, path, sd_only, require_file,
                                        require_dir)

    def list_files(self, handler, entry, path=""):
        abspath = self._storage_dispatch(entry, path, require_dir=True)

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
            elif node.endswith(".fc"):
                buf_obj.write(u"F%s\x00" % n)
            elif node.endswith(".gcode"):
                buf_obj.write(u"F%s\x00" % n)

        buf = buf_obj.getvalue()
        handler.send_text("continue")
        handler.send_text(buf.encode("utf8"))
        handler.send_text("ok")

    def select_file(self, handler, entry, path):
        abspath = self._storage_dispatch(entry, path, require_file=True)

        if not os.path.isfile(abspath):
            raise RuntimeError(NOT_EXIST, "NOT_FILE")

        self._task_file = open(abspath, "rb")
        self._task_mimetype, _ = mimetypes.guess_type(abspath)
        handler.send_text("ok")

    def fileinfo(self, handler, entry, path):
        abspath = self._storage_dispatch(entry, path, require_file=True)
        if mimetypes.guess_type(abspath)[0] == mimetypes.MIMETYPE_FCODE:
            metadata, image = fast_read_meta(abspath)
            metadata["size"] = os.path.getsize(abspath)
            handler.send_text("binary image/png %i" % len(image))
            handler.send(image)
            handler.send_text(
                "ok %s" % "\x00".join("%s=%s" % (k, v) for k, v in metadata.items()))
        else:
            handler.send_text("ok size=%i" % os.path.getsize(abspath))

    def mkdir(self, handler, entry, path):
        abspath = self._storage_dispatch(entry, path, sd_only=True)
        try:
            os.mkdir(abspath)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def rmdir(self, handler, entry, path):
        abspath = self._storage_dispatch(entry, path, sd_only=True,
                                         require_dir=True)
        try:
            shutil.rmtree(abspath)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def cpfile(self, handler, from_entry, from_path, to_entry, to_path):
        try:
            abssource = self._storage_dispatch(from_entry, from_path,
                                               require_file=True)
            abstarget = self._storage_dispatch(to_entry, to_path,
                                               sd_only=True)
            shutil.copy(abssource, abstarget)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))
        except ValueError as e:
            raise RuntimeError(BAD_PARAMS)

    def rmfile(self, handler, entry, path):
        try:
            abspath = self._storage_dispatch(entry, path, sd_only=True,
                                             require_file=True)
            os.remove(abspath)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def md5(self, handler, entry, path):
        try:
            with open(self._storage_dispatch(entry, path,
                                             require_file=True), "rb") as f:
                buf = bytearray(4096)
                l = f.readinto(buf)
                m = md5()
                while l > 0:
                    if l == 4096:
                        m.update(buf)
                    else:
                        m.update(buf[:l])
                    l = f.readinto(buf)
            handler.send_text("md5 %s" % m.hexdigest())
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def upload_file(self, handler, mimetype, sfilesize, entry, path=""):
        filesize = int(sfilesize, 10)
        if filesize > 2 ** 30:
            raise RuntimeError(TOO_LARGE)

        if entry == "#":
            self._task_file = NamedTemporaryFile()
            self._task_mimetype = mimetype
        else:
            abspath = self._storage_dispatch(entry, path, sd_only=True)
            if mimetypes.validate_ext(abspath, mimetype):
                self._task_file = open(abspath, "wb")
            else:
                logger.debug("Upload filename ext not match to mimetype")
                raise RuntimeError(BAD_FILE_FORMAT)

        logger.debug("Upload task file '%s', size %i", mimetype, filesize)

        task = UploadTask(self.stack, handler, self._task_file, filesize)
        self.stack.enter_task(task, self.end_upload_file)
        handler.send_text("continue")

    def end_upload_file(self, is_success):
        if is_success:
            self._task_file.seek(0)
        else:
            self._task_file.close()
            self._task_file = None


class PlayManagerMixIn(object):
    def validate_status(callback):
        def wrapper(self, *args):
            component = self.stack.kernel.exclusive_component
            if isinstance(component, PlayerManager):
                callback(self, component, *args)
            else:
                raise RuntimeError(NO_TASK)
        return wrapper

    @validate_status
    def play_pause(self, manager, handler):
        handler.send_text(manager.pause())

    @validate_status
    def play_resume(self, manager, handler):
        handler.send_text(manager.resume())

    @validate_status
    def play_abort(self, manager, handler):
        handler.send_text(manager.abort())

    @validate_status
    def play_quit(self, manager, handler):
        if manager.is_terminated:
            handler.send_text(manager.quit())
        else:
            raise RuntimeError(RESOURCE_BUSY)

    def play_report(self, handler):
        component = self.stack.kernel.exclusive_component
        if isinstance(component, PlayerManager):
            handler.send_text(component.report())
        elif component:
            handler.send_text('{"st_id": 0, "st_label": "OCCUPIED"}')
        else:
            raise RuntimeError(NO_TASK)

    def dispatch_playmanage_cmd(self, handler, cmd, *args):
        kernel = self.stack.kernel
        if cmd == "pause":
            self.play_pause(handler)
            return True
        elif cmd == "resume":
            self.play_resume(handler)
            return True
        elif cmd == "abort":
            self.play_abort(handler)
            return True
        elif cmd == "report":
            self.play_report(handler)
            return True
        elif cmd == "load_filament":
            return False
        elif cmd == "eject_filament":
            return False
        elif cmd == "quit" or cmd == "quit_play":
            self.play_quit(handler)
            return True
        else:
            return False


class CommandTask(CommandMixIn, PlayManagerMixIn, FileManagerMixIn):
    _task_file = None
    _task_mimetype = None

    def __init__(self, stack):
        self.stack = stack
        self.settings = CommonMetadata()
        self.user_space = UserSpace()

    def dispatch_cmd(self, handler, cmd, *args):
        if self.dispatch_filemanage_cmd(handler, cmd, *args):
            pass
        elif self.dispatch_playmanage_cmd(handler, cmd, *args):
            pass
        elif cmd == "scan":
            return self.scan(handler)
        elif cmd == "start":
            self.play(handler)
        elif cmd == "raw":
            self.raw_access(handler)
        elif cmd == "maintain":
            return self.maintain(handler)
        elif cmd == "update_fw":
            mimetype, filesize, upload_to = args
            return self.update_fw(handler, int(filesize, 10))
        elif cmd == "set":
            if len(args) != 2:
                raise RuntimeError(BAD_PARAMS)
            return self.setting_setter(*params)
        elif cmd == "kick":
            self.stack.kernel.destory_exclusive()
            # TODO: more message?
            handler.send_text("ok")
        else:
            logger.debug("Can not handle: %s" % repr(cmd))
            raise RuntimeError(UNKNOW_COMMAND)

    def update_fw(self, handler, filesize):
        if filesize > 2 ** 20:
            raise RuntimeError(TOO_LARGE)

        logger.info("Upload fireware file size: %i" % filesize)
        task = UpdateFwTask(self.stack, sender, filesize)
        self.stack.enter_task(task, empty_callback)

        return "continue"

    def raw_access(self, handler):
        task = RawTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)
        handler.send_text("continue")

    def play(self, handler):
        if self._task_file:
            kernel = self.stack.kernel
            if kernel.is_exclusived():
                raise RuntimeError(RESOURCE_BUSY)
            else:
                pm = PlayerManager(self.stack.loop, self._task_file.name,
                                   terminated_callback=kernel.release_exclusive)
                kernel.exclusive(pm)
            handler.send_text("ok")
        else:
            raise RuntimeError(NO_TASK)

    def scan(self, sender):
        task = ScanTask(self.stack, sender)
        self.stack.enter_task(task, empty_callback)
        return "ok"

    def maintain(self, handler):
        task = MaintainTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)
        handler.send_text("ok")

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
