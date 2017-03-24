
from __future__ import absolute_import

from tempfile import NamedTemporaryFile
from binascii import b2a_base64
from io import StringIO, BytesIO
from errno import errorcode
from md5 import md5
import logging
import shutil
import json
import sys
import os

from fluxmonitor.player.fcode_parser import fast_read_meta
from fluxmonitor.err_codes import (UNKNOWN_COMMAND, NOT_EXIST, TOO_LARGE,
                                   NO_TASK, BAD_PARAMS, BAD_FILE_FORMAT,
                                   RESOURCE_BUSY, SUBSYSTEM_ERROR,
                                   HARDWARE_FAILURE)
from fluxmonitor.diagnosis.god_mode import allow_god_mode
from fluxmonitor.hal.misc import get_deviceinfo
from fluxmonitor.storage import Storage, UserSpace, Preference, metadata
from fluxmonitor.config import DEFAULT_H
from fluxmonitor.misc import mimetypes

from .base import CommandMixIn
from .scan_task import ScanTask
from .upload_task import UploadTask
from .raw_task import RawTask
from .maintain_task import MaintainTask
from .update_fw_task import UpdateFwTask
from .play_manager import PlayerManager
from .icontrol_task import IControlTask
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
            f_metadata, images = fast_read_meta(abspath)

            imagestack = list(images)

            def imagesender(*args):
                if imagestack:
                    img = imagestack.pop(0)
                    logger.debug("Sending fcode preview size: %i", len(img))
                    handler.async_send_binary("image/png", len(img),
                                              BytesIO(img), imagesender)
                else:
                    f_metadata["size"] = os.path.getsize(abspath)
                    handler.send_text("ok %s" % "\x00".join(
                        "%s=%s" % (k, v)for k, v in f_metadata.items()))
            imagesender()

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

    def end_upload_file(self, is_success=None):
        if is_success:
            self._task_file.seek(0)
        else:
            self._task_file.close()
            self._task_file = None
            logger.debug("Upload task failed (is_success=%s)", is_success)


class PlayManagerMixIn(object):
    _last_playing_file = None

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
                    self._last_playing_file = self._task_file
                    kernel.exclusive(pm)
                except RuntimeError:
                    raise
                except Exception:
                    logger.exception("Launch playmanager failed")
                    raise RuntimeError(SUBSYSTEM_ERROR, HARDWARE_FAILURE)
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
        f_metadata, imgbuf = manager.playinfo

        def end_img(h):
            h.send_text("ok")

        def end_meta__send_img(h):
            if imgbuf:
                h.async_send_binary("image/png", len(imgbuf[0]),
                                    BytesIO(imgbuf[0]), end_img)
            else:
                h.send_text("ok")

        metabuf = json.dumps(f_metadata)
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

    def __play_set_toolhead_operating(self, handler):
        manager = self.__get_manager()
        handler.send_text(manager.set_toolhead_operating())

    def __play_set_toolhead_standby(self, handler):
        manager = self.__get_manager()
        handler.send_text(manager.set_toolhead_standby())

    def __play_load_filament(self, handler, index):
        if index != "0":
            raise RuntimeError(BAD_PARAMS)
        else:
            manager = self.__get_manager()
            handler.send_text(manager.load_filament(index))

    def __play_unload_filament(self, handler, index):
        if index != "0":
            raise RuntimeError(BAD_PARAMS)
        else:
            manager = self.__get_manager()
            handler.send_text(manager.unload_filament(index))

    def __set_toolhead_header(self, handler, index, temp):
        if index != "0":
            raise RuntimeError(BAD_PARAMS)
        else:
            manager = self.__get_manager()
            handler.send_text(
                manager.set_toolhead_header(int(index), float(temp)))

    def __play_press_button(self, handler):
        manager = self.__get_manager()
        handler.send_text(manager.press_button())

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
        elif cmd == "set_toolhead_operating":
            self.__play_set_toolhead_operating(handler)
        elif cmd == "set_toolhead_standby":
            self.__play_set_toolhead_standby(handler)
        elif cmd == "load_filament":
            self.__play_load_filament(handler, args[0])
        elif cmd == "unload_filament":
            self.__play_unload_filament(handler, args[0])
        elif cmd == "set_toolhead_header":
            self.__set_toolhead_header(handler, args[0], args[1])
        elif cmd == "press_button":
            self.__play_press_button(handler)
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
        "movement_test": {
            "type": str, "enum": ("Y", "N"),
            "key": "movement_test"},
        "autoresume": {
            "type": str, "enum": ("Y", "N"),
            "key": "autoresume"},
        "broadcast": {
            "type": str, "enum": ("L", "A", "N"),
            "key": "broadcast"},
        "enable_cloud": {
            "type": str, "enum": ("A", "N"),
            "key": "enable_cloud"},
        "zoffset": {
            "type": float, "min": -1.0, "max": 1.0,
            "key": "zoffset"
        },
        "zprobe_dist": {
            "type": int, "min": DEFAULT_H - 100, "max": DEFAULT_H,
            "key": "zprobe_dist"
        },
        "replay": {
            "type": str, "enum": ("Y", "N"),
            "key": "replay"},
        "enable_backlash": {
            "type": str, "enum": ("Y", "N"),
            "key": "enable_backlash"
        },
        "plus_extrusion": {
            "type": str, "enum": ("Y", "N"),
            "key": "plus_extrusion"
        },
        "camera_version": {
            "type": str, "enum": ("0", "1"),
            "key": "camera_version"
        },
        "bare": {
            "type": str, "enum": ("Y", "N"),
            "key": "bare"
        },
        "player_postback_url": {
            "type": str, "key": "player_postback_url", "maxlen": 128
        }
    }

    def dispatch_config_cmd(self, handler, cmd, key, *args):
        val = " ".join(args)
        if cmd == "set":
            self.__config_set(key, val)
            handler.send_text("ok")
        elif cmd == "get":
            val = self.__config_get(key)
            if val is not None:
                handler.send_text("ok VAL %s" % val)
            else:
                handler.send_text("ok EMPTY")
        elif cmd == "del":
            self.__config_del(key)
            handler.send_text("ok")
        else:
            raise RuntimeError(UNKNOWN_COMMAND)

    def __config_set(self, key, val):
        storage = Storage("general", "meta")
        if key in self.__VALUES:
            struct = self.__VALUES[key]

            # Check input correct
            cval = struct["type"](val)
            # Check enum
            if "enum" in struct and cval not in struct["enum"]:
                raise RuntimeError(BAD_PARAMS)
            if "min" in struct and cval < struct["min"]:
                raise RuntimeError(BAD_PARAMS)
            if "max" in struct and cval > struct["max"]:
                raise RuntimeError(BAD_PARAMS)
            if "maxlen" in struct and len(cval) > struct["maxlen"]:
                raise RuntimeError(BAD_PARAMS)

            if hasattr(metadata, struct["key"]):
                setattr(metadata, struct["key"], val)
            else:
                storage[struct["key"]] = val
        elif key == "backlash":
            d = {}
            for kv in val.split(" "):
                if ":" in kv:
                    k, sv = kv.split(":")
                    try:
                        v = float(sv)
                        if k in "ABC" and v >= 0 and v <= 100:
                            d[k] = v
                    except ValueError:
                        pass
            Preference.instance().backlash = d

        elif key == "leveling":
            d = {}
            for kv in val.split(" "):
                if ":" in kv:
                    k, sv = kv.split(":")
                    try:
                        v = float(sv)
                        if k in "XYZ" and v <= 0 and v >= -2:
                            d[k] = v
                        elif k in "R" and v <= 101 and v >= 92:
                            d[k] = v
                        elif k == "H" and v > 120 and v < 243:
                            d[k] = v
                    except ValueError:
                        pass
            Preference.instance().plate_correction = d
        else:
            raise RuntimeError(BAD_PARAMS)

    def __config_get(self, key):
        storage = Storage("general", "meta")
        if key in self.__VALUES:
            struct = self.__VALUES[key]
            if hasattr(metadata, struct["key"]):
                return getattr(metadata, struct["key"])
            else:
                return storage[struct["key"]]
        elif key == "backlash":
            return " ".join("%s:%.4f" % (k, v)
                            for k, v in Preference.instance().backlash.items())
        elif key == "leveling":
            return " ".join(
                "%s:%.4f" % (k, v)
                for k, v in Preference.instance().plate_correction.items()
                if k in "XYZRH")
        else:
            raise RuntimeError(BAD_PARAMS)

    def __config_del(self, key):
        storage = Storage("general", "meta")
        if key in self.__VALUES:
            struct = self.__VALUES[key]
            if hasattr(metadata, struct["key"]):
                delattr(metadata, struct["key"])
            else:
                del storage[struct["key"]]
        else:
            raise RuntimeError(BAD_PARAMS)


class TasksMixIn(object):
    def dispatch_task_cmd(self, handler, cmd, *args):
        if cmd == "maintain":
            self.__maintain(handler)
        elif cmd == "scan":
            self.__scan(handler)
        elif cmd == "icontrol":
            self.__icontrol(handler)
        elif cmd == "raw":
            self.__raw_access(handler)
        else:
            raise RuntimeError(UNKNOWN_COMMAND)

    def __raw_access(self, handler):
        task = RawTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)
        handler.send_text("continue")

    def __scan(self, handler):
        task = ScanTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)

    def __maintain(self, handler):
        task = MaintainTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)

    def __icontrol(self, handler):
        task = IControlTask(self.stack, handler)
        self.stack.enter_task(task, empty_callback)


class CommandTask(CommandMixIn, PlayManagerMixIn, FileManagerMixIn,
                  ConfigMixIn, TasksMixIn):
    _task_file = None
    _task_mimetype = None

    def __init__(self, stack):
        self.stack = stack
        self.user_space = UserSpace()

    def dispatch_cmd(self, handler, cmd, *args):
        try:
            if cmd == "player":
                return self.dispatch_playmanage_cmd(handler, *args)
            elif cmd == "file":
                return self.dispatch_filemanage_cmd(handler, *args)
            elif cmd == "task":
                return self.dispatch_task_cmd(handler, *args)
            elif cmd == "config":
                return self.dispatch_config_cmd(handler, *args)

        except TypeError:
            tb = sys.exc_info()[2]
            if tb.tb_next is None or tb.tb_next.tb_next is None:
                raise RuntimeError(BAD_PARAMS)
            else:
                raise

        try:
            if cmd == "update_fw":
                mimetype, filesize, upload_to = args
                if mimetype != mimetypes.MIMETYPE_FLUX_FIRMWARE:
                    raise RuntimeError(BAD_FILE_FORMAT)
                self.update_fw(handler, int(filesize, 10))
            elif cmd == "kick":
                self.stack.kernel.destory_exclusive()
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
            elif cmd == "cloud_validation_code":
                self.cloud_validation_code(handler)
            elif cmd == "oracle":
                s = Storage("general", "meta")
                s["debug"] = args[0].encode("utf8")
                handler.send_text("oracle")
            elif cmd == "fetch_log":
                self.fetch_log(handler, *args)
            else:
                logger.debug("Can not handle: %s" % repr(cmd))
                raise RuntimeError(UNKNOWN_COMMAND)

        except TypeError:
            tb = sys.exc_info()[2]
            if tb.tb_next is None:
                raise RuntimeError(BAD_PARAMS)
            else:
                raise

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
        buf = "\n".join(
            ("%s:%s" % kv for kv in get_deviceinfo(metadata).items()))
        handler.send_text("ok\n%s" % buf)

    def cloud_validation_code(self, handler):
        handler.send_text("ok %s %s" % (Storage("cloud")["token"],
                                        b2a_base64(metadata.cloud_hash)))

    def fetch_log(self, handler, path):
        filename = os.path.abspath(
            os.path.join("/var/db/fluxmonitord/run", path))
        if filename.startswith("/var/db/fluxmonitord/run"):
            def cb(h):
                handler.send_text("ok")

            try:
                mimetype = mimetypes.guess_type(filename)[0]
                length = os.path.getsize(filename)
                stream = open(filename, "rb")
                handler.async_send_binary(mimetype or "binary", length, stream,
                                          cb)
            except OSError as e:
                raise RuntimeError(
                    "OSERR_" + errorcode.get(e.args[0], "UNKNOW"))
        else:
            raise RuntimeError(BAD_PARAMS)
