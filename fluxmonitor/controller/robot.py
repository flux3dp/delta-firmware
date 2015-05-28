
from errno import ECONNREFUSED
from tempfile import TemporaryFile
from select import select
import logging
import socket
import json
import glob
import os
import re

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor.event_base import EventBase
from fluxmonitor.config import uart_config, robot_config
from fluxmonitor.controller.interfaces.local import LocalControl
from fluxmonitor.err_codes import UNKNOW_COMMAND, FILE_NOT_EXIST, \
    FILE_TOO_LARGE, UNKNOW_ERROR, ALREADY_RUNNING, RESOURCE_BUSY, NO_TASK, \
    NOT_RUNNING, NO_RESPONSE


STATUS_IDLE = 0x0
STATUS_RUNNING = 0x1
STATUS_PAUSE = 0x3

logger = logging.getLogger(__name__)


class RobotTask(object):
    connected = False

    _async_mb = _uart_mb = None
    _status = STATUS_IDLE
    _task_file = None

    # GCode executed size
    _task_executed = None
    # GCode size
    _task_total = None
    # Last g code
    _task_last = None
    # GCode in queue
    _task_in_queue = None

    @property
    def has_task(self):
        return True if self._task_file else False

    @property
    def is_idle(self):
        return self._status == STATUS_IDLE

    @property
    def is_running(self):
        return self._status == STATUS_RUNNING

    def start_task(self):
        if not self.is_idle:
            raise RuntimeError(ALREADY_RUNNING)

        if not self.has_task:
            raise RuntimeError(NO_TASK)

        if not self.connected:
            self.connect()

        self._task_total = os.fstat(self._task_file.fileno()).st_size
        self._task_executed = 0
        self._task_in_queue = 0

        self._status = STATUS_RUNNING
        logger.info("Start task with size %i" , (self._task_total))
        self._next_cmd()

    def pause_task(self):
        if self._status == STATUS_RUNNING:
            self._status = STATUS_PAUSE
        else:
            raise RuntimeError(NOT_RUNNING)

    def abort_task(self):
        if self._status in (STATUS_RUNNING, STATUS_PAUSE):
            self._clean_task()
        else:
            raise RuntimeError(NOT_RUNNING)

    def resume_task(self):
        if self._status == STATUS_PAUSE:
            self._status = STATUS_RUNNING
            self._next_cmd()
        else:
            raise RuntimeError(NOT_RUNNING)

    def report_task(self):
        return "%i/%i/%s" % (self._task_executed, self._task_total,
                             self._task_last)

    def on_mainboard_message(self, sender):
        buf = sender.obj.recv(4096)
        messages = buf.decode("ascii")

        for msg in re.split("\r\n|\n", messages):
            logger.debug("MB: %s" % msg)
            if msg.startswith("ok"):
                if self._task_in_queue != None:
                    self._task_in_queue -= 1

        if self._status == STATUS_RUNNING:
            self._next_cmd()

    def _next_cmd(self):
        while self._task_in_queue < 3:
            buf = self._task_file.readline()
            if not buf:
                self._clean_task()
                return

            self._task_executed += len(buf)
            logger.debug("GCODE: %s" % buf.decode("ascii").strip())

            cmd = buf.split(b";", 1)[0].rstrip()

            if cmd:
                self._uart_mb.send(cmd + b"\n")
                self._task_last = cmd
                self._task_in_queue += 1

    def _clean_task(self):
        self._status = STATUS_IDLE
        self._task_file = self._task_total = self._task_executed = None
        self._task_in_queue = None

    def each_loop(self):
        pass

    def connect(self):
        try:
            self.connected = True
            self._uart_mb = mb = socket.socket(socket.AF_UNIX,
                                               socket.SOCK_STREAM)

            logging.info("Connect to %s" % uart_config["mainboard"])
            mb.connect(uart_config["mainboard"])

            self._async_mb = AsyncIO(mb, self.on_mainboard_message)
            self.add_read_event(self._async_mb)

        except socket.error as err:
            logger.exception("Connect to %s failed" % uart_config["mainboard"])
            self.disconnect()

            if err.args[0] == ECONNREFUSED:
                raise RuntimeError(NO_RESPONSE)
            else:
                raise

    def disconnect(self):
        if self._async_mb:
            self.remove_read_event(self._async_mb)
            self._async_mb = None

        if self._uart_mb:
            self._uart_mb.close()
            self._uart_mb = None

        self.connected = False


class RobotCommands(object):
    """RobotCommands is using for recvie and process commands"""

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
            elif cmd == "raw":
                return self.raw_access(sender)
            elif cmd == "start":
                self.start_task()
                return "ok"
            else:
                logger.debug("Can not handle: '%s'" % cmd)
                raise RuntimeError(UNKNOW_COMMAND)
        else:
            if cmd == "pause":
                self.pause_task()
                return "ok"
            elif cmd == "abort":
                self.abort_task()
                return "ok"
            elif cmd == "resume":
                self.resume_task()
                return "ok"
            elif cmd == "report":
                return self.report_task()
            else:
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
                raise RuntimeError(FILE_NOT_EXIST)

        self._task_file = open(filename, "rb")
        return "ok"

    # Block method
    def upload_file(self, filesize, sender):
        if filesize > 2 ** 30:
            raise RuntimeError(FILE_TOO_LARGE)

        recived = 0
        _buf = bytearray(4096)
        buf = memoryview(_buf)
        self._task_file = f = TemporaryFile()

        try:
            logger.info("Upload task file size: %i" % filesize)
            logger.warning("Enter upload mode. Connectoin EXCLUSIVE.")
            sender.obj.send(b"continue")

            while recived < filesize:
                l = sender.obj.recv_into(buf)
                if l == 0:
                    self._task_file = None
                    break

                f.write(buf[:l])
                recived += l

            f.seek(0)
            return "ok"
        finally:
            logger.warning("Quit upload mode.")

    # Block method
    def raw_access(self, sender):
        try:
            logger.warning("Enter RAW mode. Connectoin EXCLUSIVE.")
            if not self.connected:
                self.connect()

            cli = sender.obj
            mb = self._uart_mb
            sender.obj.send(b"continue")

            while True:  # Loop untile disconnect or recive quit
                rl = select((cli, mb), (), (), 5.0)[0]
                if cli in rl:
                    buf = cli.recv(128)
                    if not buf:  # Disconnected
                        return ""
                    elif buf == b"quit":  # Recive quit
                        return "ok"
                    else:
                        mb.send(buf)
                if mb in rl:
                    buf = mb.recv(4096)
                    cli.send(buf)
        finally:
            logger.warning("Quit RAW mode.")
            if self.connected:
                self.disconnect()


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
