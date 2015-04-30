
from tempfile import TemporaryFile
import logging
import socket
import json
import glob
import os

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.event_base import EventBase
from fluxmonitor.config import uart_config, robot_config
from fluxmonitor.err_codes import *

from fluxmonitor.controller.interfaces.local import LocalControl

STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger("fluxrobot")


class RobotTask(object):
    _uart_mb = None

    _status = STATUS_IDLE
    _connected = False

    @property
    def is_idle(self):
        return self._status == STATUS_IDLE

    @property
    def is_running(self):
        return self._status == STATUS_RUNNING

    def start_task(self):
        if not self.is_idle:
            raise RuntimeError("ALREADY_RUNNING")

    def on_mainboard_message(self, sender):
        pass

    def each_loop(self):
        pass

    def enable_robot(self):
        self._uart_mb = mb = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        mb.connect(uart_config["mainboard"])

        self.async_mb = AsyncIO(mb, self.on_mainboard_message)

        self.add_read_event(self.async_mb)

    def disable_robot(self):
        if not self._uart_mb:
            return

        self.remove_read_event(self.async_mb)
        self.async_mb = self.async_nb = None

        self._uart_mb.close()
        self._uart_mb = None


class RobotCommands(object):
    """RobotCommands is using for recvie and process commands"""

    _task_file = None

    @property
    def has_task(self):
        return self._task_file != None

    def execute_cmd(self, cmd, sender):
        if self.is_idle:
            if cmd == "ls":
                return self.list_files()
            elif cmd.startswith("select "):
                filename = cmd.split(" ", 1)[-1]
                return self.select_file(filename)
            elif cmd.startswith("upload "):
                filesize = cmd.split(" ", 1)[-1]
                return self.upload_file(int(filesize, 10), sender)
            else:
                raise RuntimeError(UNKNOW_COMMAND)
        else:
            return "!!"

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
                raise RuntimeError(FILE_NOT_EXIST)

        self._task_file = open(filename, "rb")
        return "ok"

    def upload_file(self, filesize, sender):
        if filesize > 2 ** 30:
            raise RuntimeError(FILE_TOO_LARGE)

        recived = 0
        _buf = bytearray(4096)
        buf = memoryview(_buf)
        self._task_file = f = TemporaryFile()

        sender.obj.send(b"continue")

        while recived < filesize:
            l = sender.obj.recv_into(buf)
            f.write(buf[:l])
            recived += l

        return "ok"

class Robot(EventBase, RobotCommands, RobotTask):
    def __init__(self, options):
        EventBase.__init__(self)
        self.filepool = os.path.abspath(robot_config["filepool"])
        self.local_control = LocalControl(self, logger=logger)

    def on_cmd(self, cmd, sender):
        try:
            response = self.execute_cmd(cmd, sender)
            sender.obj.send(response.encode())
        except RuntimeError as e:
            sender.obj.send(("error %s" % e.args[0]).encode())
        except Exception:
            sender.obj.send(b"error %s" % UNKNOW_ERROR)
            logger.exception(UNKNOW_ERROR)

    def close(self):
        self.local_control.close()
