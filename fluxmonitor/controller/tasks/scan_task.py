
from shlex import split as shlex_split
from time import sleep
from io import BytesIO
import logging
import struct
import socket

from fluxmonitor.err_codes import DEVICE_ERROR, NOT_SUPPORT, UNKNOW_COMMAND
from fluxmonitor.config import hal_config, CAMERA_ENDPOINT
from fluxmonitor.storage import Storage

import pyev

from .base import CommandMixIn, DeviceOperationMixIn

logger = logging.getLogger(__name__)


class CameraInterface(object):
    def __init__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(CAMERA_ENDPOINT)

    def oneshot(self):
        self.sock.send(struct.pack("@BB", 0, 0))
        resp = self.recv_text()
        args = shlex_split(resp)
        if args[0] == "binary":
            mimetype = args[1]
            length = int(args[2])
            return mimetype, length, self.recv_binary(int(int(args[2])))
        elif args[0] == "ER":
            raise RuntimeError(*args[1:])
        else:
            raise SystemError("Unknow response: %s", resp)

    def check_camera_position(self):
        self.sock.send(struct.pack("@BB", 1, 0))
        return self.recv_text()

    def get_bias(self):
        self.sock.send(struct.pack("@BB", 2, 0))
        return self.recv_text()

    def compute_cab(self):
        self.sock.send(struct.pack("@BB", 3, 0))
        return self.recv_text()

    def recv_text(self):
        buf = self.sock.recv(1)
        textlen = struct.unpack("@B", buf)[0]
        return self.sock.recv(textlen).decode("ascii", "ignore")

    def recv_binary(self, length):
        l = 0
        f = BytesIO()
        while l < length:
            try:
                buf = self.sock.recv(min(length - l, 4096))
            except socket.error:
                raise SystemError("Camera service broken pipe")

            if buf:
                f.write(buf)
                l += len(buf)
            else:
                raise SystemError("Camera service broken pipe")
        f.seek(0)
        return f

    def close(self):
        self.sock.close()


class ScanTask(DeviceOperationMixIn, CommandMixIn):
    _device_busy = False
    step_length = 0.45

    def __init__(self, stack, handler, camera_id=None):
        self.camera = CameraInterface()
        super(ScanTask, self).__init__(stack, handler, enable_watcher=False)

        self.step_length = 0.45
        self.init_device()

    def on_exit(self, handler):
        self.camera.close()
        super(ScanTask, self).on_exit(handler)

    def init_device(self):
        try:
            init_gcodes = ["G28", "M302", "M907 Y0.4", "T2", "G91"]
            for cmd in init_gcodes:
                ret = self.make_gcode_cmd(cmd)
                if not ret.endswith("ok"):
                    erro_msg = "GCode '%s' return '%s'" % (cmd, ret)
                    logger.error(erro_msg)
                    raise RuntimeError(DEVICE_ERROR, erro_msg)
        except:
            raise

    def make_gcode_cmd(self, cmd):
        self._uart_mb.send(("%s\n" % cmd).encode())
        return self._uart_mb.recv(128).decode("ascii", "ignore").strip()

    def dispatch_cmd(self, handler, cmd, *args):
        if cmd == "oneshot":
            self.oneshot(handler)

        elif cmd == "scanimages":
            self.take_images(handler)

        elif cmd == "scan_check":
            self.scan_check(handler)

        elif cmd == "get_cab":
            self.get_cab(handler)

        elif cmd == "calibrate":
            self.calibrate(handler)

        elif cmd == "scanlaser":
            param = args[0] if args else ""
            l_on = "l" in param
            r_on = "r" in param
            handler.send_text(self.change_laser(left=l_on, right=r_on))

        elif cmd == "set":
            if args[0] == "steplen":
                self.step_length = float(args[1])
                handler.send_text("ok")
            else:
                print(args)
                raise RuntimeError(UNKNOW_COMMAND, args[1])

        elif cmd == "scan_backward":
            ret = self.make_gcode_cmd("G1 F500 E-%.5f" % self.step_length)
            if ret != "ok":
                raise RuntimeError(DEVICE_ERROR, ret)
            sleep(0.05)
            handler.send_text(ret)

        elif cmd == "scan_next":
            ret = self.make_gcode_cmd("G1 F500 E%.5f" % self.step_length)
            if ret != "ok":
                logger.error("Mainboard response %s rather then ok", repr(ret))
                raise RuntimeError(DEVICE_ERROR, ret)
            sleep(0.05)
            handler.send_text(ret)

        elif cmd == "quit":
            self.stack.exit_task(self)
            handler.send_text("ok")

        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    def change_laser(self, left, right):
        self.make_gcode_cmd("X1O1" if left else "X1F1")
        self.make_gcode_cmd("X1O2" if right else "X1F2")
        return "ok"

    def scan_check(self, handler):
        handler.send_text(self.camera.check_camera_position())

    def calibrate(self, handler):

        w = self.camera.get_bias()

        handler.send_text(w)

    def get_cab(self, handler):
        s = Storage('camera')
        a = s.readall('calibration')
        if a is None:
            a = '0 0'
        handler.send_text("ok " + a)

    def oneshot(self, handler):
        def cb(h):
            handler.send_text("ok")
        mimetype, length, stream = self.camera.oneshot()
        handler.async_send_binary(mimetype, length, stream, cb)

    def take_images(self, handler):
        def cb_complete(h):
            handler.send_text("ok")

        def cb_shot3(h):
            mimetype, length, stream = self.camera.oneshot()
            h.async_send_binary(mimetype, length, stream, cb_complete)

        def cb_shot2(h):
            mimetype, length, stream = self.camera.oneshot()
            h.async_send_binary(mimetype, length, stream, cb_shot3)
            self.change_laser(left=False, right=False)

        self.change_laser(left=True, right=False)
        sleep(0.03)
        mimetype, length, stream = self.camera.oneshot()

        handler.async_send_binary(mimetype, length, stream, cb_shot2)
        self.change_laser(left=False, right=True)
