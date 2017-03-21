
from select import select
from errno import ECONNREFUSED, ENOENT
from time import sleep
from math import isnan
from io import BytesIO
import logging
import msgpack
import socket

import pyev

from fluxmonitor.player.main_controller import MainController
from fluxmonitor.err_codes import (
    SUBSYSTEM_ERROR, NO_RESPONSE, RESOURCE_BUSY, UNKNOWN_COMMAND)
from fluxmonitor.storage import Storage, metadata
from fluxmonitor.config import CAMERA_ENDPOINT
from fluxmonitor.player import macro

from .base import CommandMixIn, DeviceOperationMixIn

logger = logging.getLogger(__name__)


class CameraInterface(object):
    def __init__(self, kernel):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(CAMERA_ENDPOINT)
            self.unpacker = msgpack.Unpacker()

            self.watcher = kernel.loop.io(self.fileno(), pyev.EV_READ,
                                          lambda *args: None)
        except socket.error as err:
            if err.args[0] in [ECONNREFUSED, ENOENT]:
                raise RuntimeError(SUBSYSTEM_ERROR, NO_RESPONSE)
            else:
                raise

    def fileno(self):
        return self.sock.fileno()

    def recv_object(self):
        buf = self.sock.recv(4096)
        if buf:
            self.unpacker.feed(buf)
            for payload in self.unpacker:
                return payload
        else:
            raise SystemError(SUBSYSTEM_ERROR, NO_RESPONSE)

    def recv_binary(self, length):
        self.sock.send("\x00")
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

    def async_oneshot(self, callback):
        def overlay(w, r):
            w.stop()
            callback(self.end_oneshot())

        self.begin_oneshot()
        self.watcher.callback = overlay
        self.watcher.start()

    def begin_oneshot(self):
        self.sock.send(msgpack.packb((0, 0)))

    def end_oneshot(self):
        args = self.recv_object()
        if args[0] == "binary":
            mimetype = args[1]
            length = args[2]
            return mimetype, length, self.recv_binary(int(int(args[2])))
        elif args[0] == "er":
            raise RuntimeError(*args[1:])
        else:
            logger.error("Got unknown response from camera service: %s", args)
            raise SystemError("UNKNOWN_ERROR")

    def async_check_camera_position(self, callback):
        def overlay(w, r):
            w.stop()
            callback(self.end_check_camera_position())

        self.begin_check_camera_position()
        self.watcher.callback = overlay
        self.watcher.start()

    def begin_check_camera_position(self):
        self.sock.send(msgpack.packb((1, 0)))

    def end_check_camera_position(self):
        return " ".join(self.recv_object())

    def async_get_bias(self, callback):
        def overlay(w, r):
            w.stop()
            callback(self.end_get_bias())

        self.begin_get_bias()
        self.watcher.callback = overlay
        self.watcher.start()

    def begin_get_bias(self):
        self.sock.send(msgpack.packb((2, 0)))

    def end_get_bias(self):
        return " ".join(("%s" % i for i in self.recv_object()))

    def async_compute_cab(self, step, callback):
        def overlay(w, r):
            w.stop()
            callback(step, self.end_compute_cab())

        self.begin_compute_cab(step)
        self.watcher.callback = overlay
        self.watcher.start()

    def begin_compute_cab(self, step):
        if step == 'O':
            self.sock.send(msgpack.packb((3, 0)))
        elif step == 'L':
            self.sock.send(msgpack.packb((4, 0)))
        elif step == 'R':
            self.sock.send(msgpack.packb((5, 0)))

    def end_compute_cab(self):
        return " ".join(("%s" % i for i in self.recv_object()))

    def close(self):
        self.sock.close()


class ScanTask(DeviceOperationMixIn, CommandMixIn):
    st_id = -2
    mainboard = None
    step_length = 0.45
    busying = False

    _macro = None

    def __init__(self, stack, handler, camera_id=None):
        self.camera = CameraInterface(stack)
        super(ScanTask, self).__init__(stack, handler)

        def on_mainboard_ready(ctrl):
            self.busying = False
            for cmd in ("G28", "G91", "M302", "M907 Y0.4", "T2"):
                ctrl.send_cmd(cmd)
            handler.send_text("ok")

        def on_mainboard_empty(sender):
            if self._macro:
                self._macro.on_command_empty(self)

        def on_mainboard_sendable(sender):
            if self._macro:
                self._macro.on_command_sendable(self)

        def on_mainboard_ctrl(sender, data):
            if self._macro:
                self._macro.on_ctrl_message(self, data)

        self.mainboard = MainController(
            self._sock_mb.fileno(), bufsize=14,
            empty_callback=on_mainboard_empty,
            sendable_callback=on_mainboard_sendable,
            ctrl_callback=on_mainboard_ctrl)
        self.mainboard.bootstrap(on_mainboard_ready)
        self.busying = True

    def make_gcode_cmd(self, cmd, callback=None):
        def cb():
            self._macro = None
            if callback:
                callback()
        self._macro = macro.CommandMacro(cb, (cmd, ))
        self._macro.start(self)

    def dispatch_cmd(self, handler, cmd, *args):
        if self._macro or self.busying:
            raise RuntimeError(RESOURCE_BUSY)

        elif cmd == "oneshot":
            self.oneshot(handler)

        elif cmd == "scanimages":
            self.take_images(handler)

        elif cmd == "scan_check":
            self.scan_check(handler)

        elif cmd == "get_cab":
            self.get_cab(handler)

        elif cmd == "calibrate":
            self.async_calibrate(handler)

        elif cmd == "scanlaser":
            param = args[0] if args else ""
            l_on = "l" in param
            r_on = "r" in param

            def cb():
                handler.send_text("ok")
            self.change_laser(left=l_on, right=r_on, callback=cb)

        elif cmd == "set":
            if args[0] == "steplen":
                self.step_length = float(args[1])
                handler.send_text("ok")
            else:
                raise RuntimeError(UNKNOWN_COMMAND, args[1])

        elif cmd == "scan_backward":
            def cb():
                self._macro = None
                handler.send_text("ok")
            cmd = "G1 F500 E-%.5f" % self.step_length
            self._macro = macro.CommandMacro(cb, (cmd, ))
            self._macro.start(self)

        elif cmd == "scan_next":
            def cb():
                self._macro = None
                handler.send_text("ok")
            cmd = "G1 F500 E%.5f" % self.step_length
            self._macro = macro.CommandMacro(cb, (cmd, ))
            self._macro.start(self)

        elif cmd == "quit":
            self.stack.exit_task(self)
            handler.send_text("ok")

        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOWN_COMMAND)

    def change_laser(self, left, right, callback=None):
        def cb():
            self._macro = None
            if callback:
                callback()

        flag = (1 if left else 0) + (2 if right else 0)
        self._macro = macro.CommandMacro(cb, ("X1E%i" % flag, ))
        self._macro.start(self)

        if not callback:
            while self._macro:
                rl = select((self._sock_mb, ), (), (), 1.0)[0]
                if rl:
                    self.on_mainboard_message(self._watcher_mb, 0)

    def scan_check(self, handler):
        def callback(m):
            self.busying = False
            handler.send_text(m)
        self.camera.async_check_camera_position(callback)
        self.busying = True

    def async_calibrate(self, handler):
        # this is measure by data set
        table = {8: 60, 7: 51, 6: 40, 5: 32, 4: 26, 3: 19, 2: 11, 1: 6, 0: 1}
        compute_cab_ref = (("O", False, False),
                           ("L", True, False),
                           ("R", False, True))

        data = {"flag": 0, "thres": 0.2, "calibrate_param": []}
        self.change_laser(left=False, right=False)

        def on_loop(output=None):
            if output:
                self.busying = False
                handler.send_text('ok ' + output)

            elif data["flag"] == 11:
                self.busying = False
                handler.send_text('ok fail chess')
            elif data["flag"] == 12:
                self.busying = False
                handler.send_text('ok fail laser {}'.format(data["flag"]))
            elif data["flag"] > 10:
                self.busying = False
                handler.send_text('ok fail laser {}'.format(data["flag"]))
            else:
                data["flag"] += 1
                self.camera.async_get_bias(on_get_bias)

        def on_compute_cab(step, m):
            m = m.split()[1]
            data["calibrate_param"].append(m)
            if len(data["calibrate_param"]) < 3:
                step, l, r = compute_cab_ref[0]
                self.change_laser(left=l, right=r)
                self.camera.async_compute_cab(step, on_compute_cab)
            else:
                if 'fail' in data["calibrate_param"]:
                    data["flag"] = 12
                elif all(abs(float(r) - float(data["calibrate_param"][0])) < 72
                         for r in data["calibrate_param"][1:]):
                    # so naive check
                    s = Storage('camera')
                    s['calibration'] = ' '.join(
                        map(lambda x: str(round(float(x))),
                            data["calibrate_param"]))
                    output = ' '.join(data["calibrate_param"])
                    on_loop(output)
                else:
                    data["flag"] = 13

        def begin_compute_cab():
            step, l, r = compute_cab_ref[0]
            self.change_laser(left=l, right=r)
            self.camera.async_compute_cab(step, on_compute_cab)

        def on_get_bias(m):
            data["flag"] += 1
            w = float(m.split()[1])
            logger.debug("Camera calibrate w = %s", w)
            if isnan(w):
                on_loop()
            else:
                if abs(w) < data["thres"]:  # good enough to calibrate
                    begin_compute_cab()
                elif w < 0:
                    self.make_gcode_cmd(
                        "G1 F500 E{}".format(table.get(round(abs(w)), 60)),
                        on_loop)
                elif w > 0:
                    self.make_gcode_cmd(
                        "G1 F500 E-{}".format(table.get(round(abs(w)), 60)),
                        on_loop)
                data["thres"] += 0.05

        on_loop()
        self.busying = True

    def get_cab(self, handler):
        s = Storage('camera')
        a = s.readall('calibration')
        if a is None:
            a = '320 320 320'
        handler.send_text("ok " + a)

    def oneshot(self, handler):
        def sent_callback(h):
            self.busying = False
            handler.send_text("ok")

        def recv_callback(result):
            mimetype, length, stream = result
            handler.async_send_binary(mimetype, length, stream, sent_callback)

        self.camera.async_oneshot(recv_callback)
        self.busying = True

    def take_images(self, handler):
        def cb_complete(h):
            self.busying = False
            handler.send_text("ok")

        def cb_shot3_ready(result):
            mimetype, length, stream = result
            handler.async_send_binary(mimetype, length, stream, cb_complete)

        def cb_shot3(h):
            self.camera.async_oneshot(cb_shot3_ready)

        def cb_shot2_ready(result):
            mimetype, length, stream = result
            self.change_laser(left=False, right=False,
                              callback=lambda: sleep(0.04))
            handler.async_send_binary(mimetype, length, stream, cb_shot3)

        def cb_shot2(h):
            self.camera.async_oneshot(cb_shot2_ready)

        def cb_shot1_ready(result):
            mimetype, length, stream = result
            self.change_laser(left=False, right=True,
                              callback=lambda: sleep(0.04))
            handler.async_send_binary(mimetype, length, stream, cb_shot2)

        def cb_shot1():
            self.camera.async_oneshot(cb_shot1_ready)

        self.change_laser(left=True, right=False, callback=cb_shot1)
        self.busying = True

    def on_mainboard_message(self, watcher, revent):
        try:
            self.mainboard.handle_recv()
        except IOError:
            logger.exception("Mainboard connection broken")
            self.handler.send_text("error SUBSYSTEM_ERROR")
            self.stack.exit_task(self)
        except RuntimeError:
            pass
        except Exception:
            logger.exception("Unhandle Error")

    def on_timer(self, watcher, revent):
        metadata.update_device_status(self.st_id, 0, "N/A",
                                      self.handler.address)

    def clean(self):
        try:
            if self.mainboard:
                if self.mainboard.ready:
                    self.mainboard.send_cmd("X1E0")
                self.mainboard.close()
                self.mainboard = None
        except Exception:
            logger.exception("Mainboard error while quit")

        if self.camera:
            self.camera.close()
            self.camera = None

        metadata.update_device_status(0, 0, "N/A", "")
