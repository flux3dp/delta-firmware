
from __future__ import absolute_import

from tempfile import NamedTemporaryFile
from io import StringIO, BytesIO
from errno import errorcode
from md5 import md5
import logging
import shutil
import json
import os

from fluxmonitor.player.fcode_parser import fast_read_meta
from fluxmonitor.err_codes import (UNKNOWN_COMMAND, NOT_EXIST, TOO_LARGE,
                                   NO_TASK, BAD_PARAMS, BAD_FILE_FORMAT,
                                   RESOURCE_BUSY, SUBSYSTEM_ERROR,
                                   HARDWARE_FAILURE)
from fluxmonitor.storage import Storage, Metadata, UserSpace
from fluxmonitor.diagnosis.god_mode import allow_god_mode
from fluxmonitor.misc import mimetypes
from fluxmonitor import halprofile
import fluxmonitor

from .base import CommandMixIn
from .scan_task import ScanTask
from .upload_task import UploadTask
from .raw_task import RawTask
from .maintain_task import MaintainTask
from .update_fw_task import UpdateFwTask
from .play_manager import PlayerManager
from .update_mbfw_task import UpdateMbFwTask

logger = logging.getLogger(__name__)


def empty_callback(*args):
    pass


class FileManagerMixIn(object):
    def dispatch_filemanage_cmd(self, handler, cmd, *args):
        if cmd == "ls":
            self.list_files(handler, *args)
        elif cmd == "info":
            self.fileinfo(handler, *args)
        elif cmd == "mkdir":
            self.mkdir(handler, *args)
        elif cmd == "rmdir":
            self.rmdir(handler, *args)
        elif cmd == "cp":
            self.cpfile(handler, *args)
        elif cmd == "rm":
            self.rmfile(handler, *args)
        elif cmd == "upload":
            # upload [mimetype] [size] [entry] [path]
            self.upload_file(handler, *args)
        elif cmd == "download":
            self.download_file(handler, *args)
        elif cmd == "md5":
            self.md5(handler, *args)
        else:
            raise RuntimeError(UNKNOWN_COMMAND)

    def list_files(self, handler, entry, path=""):
        abspath = self.storage_dispatch(entry, path, require_dir=True)

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

    def fileinfo(self, handler, entry, path):
        abspath = self.storage_dispatch(entry, path, require_file=True)
        if mimetypes.guess_type(abspath)[0] == mimetypes.MIMETYPE_FCODE:
            metadata, images = fast_read_meta(abspath)
            for img in images:
                handler.send_text("binary image/png %i" % len(img))
                handler.send(img)
            metadata["size"] = os.path.getsize(abspath)
            handler.send_text(
                "ok %s" % "\x00".join(
                    "%s=%s" % (k, v)for k, v in metadata.items()))
        else:
            handler.send_text("ok size=%i" % os.path.getsize(abspath))

    def mkdir(self, handler, entry, path):
        abspath = self.storage_dispatch(entry, path, sd_only=True)
        try:
            os.mkdir(abspath)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def rmdir(self, handler, entry, path):
        abspath = self.storage_dispatch(entry, path, sd_only=True,
                                        require_dir=True)
        try:
            shutil.rmtree(abspath)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def cpfile(self, handler, from_entry, from_path, to_entry, to_path):
        try:
            abssource = self.storage_dispatch(from_entry, from_path,
                                              require_file=True)
            abstarget = self.storage_dispatch(to_entry, to_path,
                                              sd_only=True)
            shutil.copy(abssource, abstarget)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))
        except ValueError as e:
            raise RuntimeError(BAD_PARAMS)

    def rmfile(self, handler, entry, path):
        try:
            abspath = self.storage_dispatch(entry, path, sd_only=True,
                                            require_file=True)
            os.remove(abspath)
            handler.send_text("ok")
        except OSError as e:
            raise RuntimeError("OSERR_" + errorcode.get(e.args[0], "UNKNOW"))

    def md5(self, handler, entry, path):
        try:
            with open(self.storage_dispatch(entry, path,
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

    def download_file(self, handler, entry, path):
        def cb(h):
            handler.send_text("ok")

        try:
            abspath = self.storage_dispatch(entry, path, require_file=True)
            mimetype = mimetypes.guess_type(abspath)[0]
            length = os.path.getsize(abspath)
            stream = open(abspath, "rb")
            handler.async_send_binary(mimetype, length, stream, cb)
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
            abspath = self.storage_dispatch(entry, path, sd_only=True)
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
    def __get_manager(self):
        component = self.stack.kernel.exclusive_component
        if isinstance(component, PlayerManager):
            return component
        else:
            raise RuntimeError(NO_TASK)

    def __select_file(self, handler, entry, path):
        abspath = self.storage_dispatch(entry, path, require_file=True)

        if not os.path.isfile(abspath):
            raise RuntimeError(NOT_EXIST, "NOT_FILE")

        self._task_file = open(abspath, "rb")
        self._task_mimetype, _ = mimetypes.guess_type(abspath)
        handler.send_text("ok")

    def __start(self, handler):
        if self._task_file:
            kernel = self.stack.kernel
            if kernel.is_exclusived():
                raise RuntimeError(RESOURCE_BUSY)
            else:
                try:
                    pm = PlayerManager(
                        self.stack.loop, self._task_file.name,
                        terminated_callback=kernel.release_exclusive)
                except Exception:
                    logger.exception("Launch playmanager failed")
                    raise RuntimeError(SUBSYSTEM_ERROR, HARDWARE_FAILURE)
                kernel.exclusive(pm)
            handler.send_text("ok")
        else:
            raise RuntimeError(NO_TASK)

    def __play_pause(self, handler):
        manager = self.__get_manager()
        handler.send_text(manager.pause())

    def __play_resume(self, handler):
        manager = self.__get_manager()
        handler.send_text(manager.resume())

    def __play_abort(self, handler):
        manager = self.__get_manager()
        handler.send_text(manager.abort())

    def __play_quit(self, handler):
        manager = self.__get_manager()
        if manager.is_terminated:
            handler.send_text(manager.quit())
        else:
            raise RuntimeError(RESOURCE_BUSY)

    def __play_info(self, handler):
        manager = self.__get_manager()
        metadata, imgbuf = manager.playinfo

        def end_img(h):
            h.send_text("ok")

        def end_meta__send_img(h):
            if imgbuf:
                h.async_send_binary("image/png", len(imgbuf[0]),
                                    BytesIO(imgbuf[0]), end_img)
            else:
                h.send_text("ok")

        metabuf = json.dumps(metadata)
        handler.async_send_binary("text/json", len(metabuf), BytesIO(metabuf),
                                  end_meta__send_img)

    def __play_report(self, handler):
        component = self.stack.kernel.exclusive_component
        if isinstance(component, PlayerManager):
            handler.send_text(component.report())
        elif component:
            handler.send_text('{"st_id": %i, "st_label": "OCCUPIED", '
                              '"info": "%s"}' % (component.st_id,
                                                 component.label))
        else:
            handler.send_text('{"st_id": 0, "st_label": "IDLE"}')

    def dispatch_playmanage_cmd(self, handler, cmd, *args):
        if cmd == "pause":
            self.__play_pause(handler)
        elif cmd == "resume":
            self.__play_resume(handler)
        elif cmd == "abort":
            self.__play_abort(handler)
        elif cmd == "report":
            self.__play_report(handler)
        elif cmd == "select":
            self.__select_file(handler, *args)
        elif cmd == "info":
            self.__play_info(handler)
        elif cmd == "start":
            self.__start(handler)
        elif cmd == "load_filament":
            raise RuntimeError(UNKNOWN_COMMAND)
        elif cmd == "eject_filament":
            raise RuntimeError(UNKNOWN_COMMAND)
        elif cmd == "quit":
            self.__play_quit(handler)
        else:
            raise RuntimeError(UNKNOWN_COMMAND)


class ConfigMixIn(object):
    __VALUES = {
        "correction": {
            "type": str, "enum": ("A", "a", "H", "N"),
            "key": "auto_correction"},
        "filament_detect": {
            "type": str, "enum": ("Y", "N"),
            "key": "filament_detect"},
        "head_error_level": {
            "type": int, "key": "head_error_level"},
    }

    def dispatch_config_cmd(self, handler, cmd, *args):
        if cmd == "set":
            self.__config_set(args[0], args[1])
            handler.send_text("ok")
        elif cmd == "get":
            val = self.__config_get(args[0])
            if val is not None:
                handler.send_text("ok VAL %s" % val)
            else:
                handler.send_text("ok EMPTY")
        elif cmd == "del":
            self.__config_del(args[0])
            handler.send_text("ok")
        else:
            raise RuntimeError(UNKNOWN_COMMAND)

    def __config_set(self, key, val):
        storage = Storage("general", "meta")
        if key in self.__VALUES:
            struct = self.__VALUES[key]

            # Check input correct
            struct["type"](val)
            # Check enum
            if "enum" in struct and val not in struct["enum"]:
                raise RuntimeError(BAD_PARAMS)

            storage[struct["key"]] = val
        elif key == "nickname":
            self.settings.nickname = val
        else:
            raise RuntimeError(BAD_PARAMS)

    def __config_get(self, key):
        storage = Storage("general", "meta")
        if key in self.__VALUES:
            struct = self.__VALUES[key]
            return storage[struct["key"]]
        elif key == "nickname":
            return self.settings.nickname
        else:
            raise RuntimeError(BAD_PARAMS)

    def __config_del(self, key):
        storage = Storage("general", "meta")
        if key in self.__VALUES:
            struct = self.__VALUES[key]
            del storage[struct["key"]]
        else:
            raise RuntimeError(BAD_PARAMS)


class TasksMixIn(object):
    def dispatch_task_cmd(self, handler, cmd, *args):
        if cmd == "maintain":
            self.__maintain(handler)
        elif cmd == "scan":
            self.__scan(handler)
        elif cmd == "raw" and allow_god_mode():
            self.__raw_access(handler)

    def __raw_access(self, handler):
        task = RawTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)
        handler.send_text("continue")

    def __scan(self, handler):
        task = ScanTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)
        handler.send_text("ok")

    def __maintain(self, handler):
        task = MaintainTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)


class CommandTask(CommandMixIn, PlayManagerMixIn, FileManagerMixIn,
                  ConfigMixIn, TasksMixIn):
    _task_file = None
    _task_mimetype = None

    def __init__(self, stack):
        self.stack = stack
        self.settings = Metadata()
        self.user_space = UserSpace()

    def dispatch_cmd(self, handler, cmd, *args):
        if cmd == "player":
            self.dispatch_playmanage_cmd(handler, *args)
        elif cmd == "file":
            self.dispatch_filemanage_cmd(handler, *args)
        elif cmd == "update_fw":
            mimetype, filesize, upload_to = args
            if mimetype != mimetypes.MIMETYPE_FLUX_FIRMWARE:
                raise RuntimeError(BAD_FILE_FORMAT)
            self.update_fw(handler, int(filesize, 10))
        elif cmd == "config":
            self.dispatch_config_cmd(handler, *args)
        elif cmd == "task":
            self.dispatch_task_cmd(handler, *args)
        elif cmd == "kick":
            self.stack.kernel.destory_exclusive()
            # TODO: more message?
            handler.send_text("ok")
        elif cmd == "update_mbfw" and allow_god_mode():
            mimetype, filesize, upload_to = args
            return self.update_mbfw(handler, int(filesize, 10))
        elif cmd == "deviceinfo":
            self.deviceinfo(handler)
        elif cmd == "scan":
            # TODO: going tobe remove
            self.dispatch_task_cmd(handler, "scan")
        elif cmd == "start":
            # TODO: going tobe removed
            self.dispatch_playmanage_cmd(handler, "start")
            self.play(handler)
        elif cmd == "maintain":
            # TODO: going tobe removed
            self.dispatch_task_cmd(handler, "maintain")
        elif cmd == "oracle":
            s = Storage("general", "meta")
            s["debug"] = args[0].encode("utf8")
            handler.send_text("oracle")
        else:
            logger.debug("Can not handle: %s" % repr(cmd))
            raise RuntimeError(UNKNOWN_COMMAND)

    def storage_dispatch(self, entry, path, sd_only=False, require_file=False,
                         require_dir=False):
        return self.user_space.get_path(entry, path, sd_only, require_file,
                                        require_dir)

    def update_fw(self, handler, filesize):
        if filesize > 100 * (2 ** 20):
            raise RuntimeError(TOO_LARGE)

        logger.info("Upload firmware file size: %i" % filesize)
        task = UpdateFwTask(self.stack, handler, filesize)
        self.stack.enter_task(task, empty_callback)
        handler.send_text("continue")

    def update_mbfw(self, handler, filesize):
        if filesize > 10 * (2 ** 20):
            raise RuntimeError(TOO_LARGE)

        logger.info("Upload MB firmware file size: %i" % filesize)
        task = UpdateMbFwTask(self.stack, handler, filesize)
        self.stack.enter_task(task, empty_callback)
        handler.send_text("continue")

    def deviceinfo(self, handler):
        handler.send_text("ok\nversion:%s\nmodel:%s" % (
            fluxmonitor.__version__,
            halprofile.get_model_id()))
