
from select import select
from errno import ECONNREFUSED, ENOENT
from time import sleep
from io import BytesIO
import logging
import msgpack
import socket

from fluxmonitor.player.main_controller import MainController
from fluxmonitor.err_codes import (
    SUBSYSTEM_ERROR, NO_RESPONSE, RESOURCE_BUSY, UNKNOWN_COMMAND)
from fluxmonitor.storage import Storage, Metadata
from fluxmonitor.config import CAMERA_ENDPOINT
from fluxmonitor.player import macro

from .base import CommandMixIn, DeviceOperationMixIn, \
    DeviceMessageReceiverMixIn

logger = logging.getLogger(__name__)


class CameraInterface(object):
    def __init__(self):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(CAMERA_ENDPOINT)
            self.unpacker = msgpack.Unpacker()
        except socket.error as err:
            if err.args[0] in [ECONNREFUSED, ENOENT]:
                raise RuntimeError(SUBSYSTEM_ERROR, NO_RESPONSE)
            else:
                raise

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

    def oneshot(self):
        self.sock.send(msgpack.packb((0, 0)))
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

    def check_camera_position(self):
        self.sock.send(msgpack.packb((1, 0)))
        return " ".join(self.recv_object())

    def get_bias(self):
        self.sock.send(msgpack.packb((2, 0)))
        return " ".join(("%s" % i for i in self.recv_object()))

    def compute_cab(self, step):
        if step == 'O':
            self.sock.send(msgpack.packb((3, 0)))
        elif step == 'L':
            self.sock.send(msgpack.packb((4, 0)))
        elif step == 'R':
            self.sock.send(msgpack.packb((5, 0)))
        return " ".join(("%s" % i for i in self.recv_object()))

    def close(self):
        self.sock.close()


class ScanTask(DeviceOperationMixIn, DeviceMessageReceiverMixIn,
               CommandMixIn):
    st_id = -2
    mainboard = None
    step_length = 0.45

    _macro = None

    def __init__(self, stack, handler, camera_id=None):
        self.camera = CameraInterface()
        super(ScanTask, self).__init__(stack, handler)

        def on_mainboard_ready(ctrl):
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
            self._uart_mb.fileno(), bufsize=14,
            empty_callback=on_mainboard_empty,
            sendable_callback=on_mainboard_sendable,
            ctrl_callback=on_mainboard_ctrl)
        self.mainboard.bootstrap(on_mainboard_ready)

        self.metadata = Metadata()
        self.timer_watcher = stack.loop.timer(1, 1, self.on_timer)
        self.timer_watcher.start()

    def clean(self):
        if self.timer_watcher:
            self.timer_watcher.stop()
            self.timer_watcher = None

        if self.mainboard:
            self.mainboard.send_cmd("X1E0")

        try:
            if self.mainboard:
                self.mainboard.close()
                self.mainboard = None
        except Exception:
            logger.exception("Mainboard error while quit")

        if self.camera:
            self.camera.close()
            self.camera = None
        self.metadata.update_device_status(0, 0, "N/A", "")

    def make_gcode_cmd(self, cmd):
        def cb():
            self._macro = None
        self._macro = macro.CommandMacro(cb, (cmd, ))
        self._macro.start(self)

        while self._macro:
            rl = select((self._uart_mb, ), (), (), 1.0)[0]
            if rl:
                self.on_mainboard_message(self._mb_watcher, 0)

    def dispatch_cmd(self, handler, cmd, *args):
        if self._macro:
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
            self.calibrate(handler)

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
                rl = select((self._uart_mb, ), (), (), 1.0)[0]
                if rl:
                    self.on_mainboard_message(self._mb_watcher, 0)

    def scan_check(self, handler):
        handler.send_text(self.camera.check_camera_position())

    def calibrate(self, handler):
        # this is measure by data set
        table = {8: 60, 7: 51, 6: 40, 5: 32, 4: 26, 3: 19, 2: 11, 1: 6, 0: 1}
        flag = 0

        self.change_laser(left=False, right=False)
        while True:
            if flag > 10:
                break
            flag += 1
            m = self.camera.get_bias()
            w = float(m.split()[1])
            logger.info('w = {}'.format(w))
            thres = 0.2
            if w == w:  # w is not nan
                if abs(w) < thres:  # good enough to calibrate
                    calibrate_parameter = []
                    for step, l, r in [("O", False, False), ("L", True, False),
                                       ("R", False, True)]:
                        self.change_laser(left=l, right=r)
                        sleep(0.5)
                        m = self.camera.compute_cab(step)
                        m = m.split()[1]
                        calibrate_parameter.append(m)

                    output = ' '.join(calibrate_parameter)
                    logger.info(output)

                    if 'fail' in calibrate_parameter:
                        flag = 12
                    elif all(abs(float(r) - float(calibrate_parameter[0])) < 72
                             for r in calibrate_parameter[1:]):
                        # so naive check
                        s = Storage('camera')
                        s['calibration'] = ' '.join(
                            map(lambda x: str(round(float(x))),
                                calibrate_parameter))
                        break
                    else:
                        flag = 13
                elif w < 0:
                    self.make_gcode_cmd(
                        "G1 F500 E{}".format(table.get(round(abs(w)), 60)))
                elif w > 0:
                    self.make_gcode_cmd(
                        "G1 F500 E-{}".format(table.get(round(abs(w)), 60)))
                table[round(abs(w))]
                thres += 0.05
            else:  # TODO: what about nan
                pass
        self.change_laser(left=False, right=False)
        if flag < 10:
            handler.send_text('ok ' + output)
        elif flag == 11:
            handler.send_text('ok fail chess')
        elif flag == 12:
            handler.send_text('ok fail laser {}'.format(flag))
        else:
            handler.send_text('ok fail laser {}'.format(flag))

    def get_cab(self, handler):
        s = Storage('camera')
        a = s.readall('calibration')
        if a is None:
            a = '320 320 320'
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
            self.change_laser(left=False, right=False,
                              callback=lambda: sleep(0.04))

        def cb_shot1():
            mimetype, length, stream = self.camera.oneshot()
            handler.async_send_binary(mimetype, length, stream, cb_shot2)
            self.change_laser(left=False, right=True,
                              callback=lambda: sleep(0.04))

        self.change_laser(left=True, right=False, callback=cb_shot1)

    def on_mainboard_message(self, watcher, revent):
        try:
            self.mainboard.handle_recv()
        except IOError:
            logger.error("Mainboard connection broken")
            self.stack.exit_task(self)
        except RuntimeError:
            pass
        except Exception:
            logger.exception("Unhandle Error")

    def on_timer(self, watcher, revent):
        self.metadata.update_device_status(self.st_id, 0, "N/A", "")
