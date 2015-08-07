
from importlib import import_module
import logging

from fluxmonitor.config import hal_config
from fluxmonitor.err_codes import DEVICE_ERROR, NOT_SUPPORT, UNKNOW_COMMAND
from .base import ExclusiveMixIn, CommandMixIn, DeviceOperationMixIn

logger = logging.getLogger(__name__)
cv2 = None


class ScanTask(ExclusiveMixIn, CommandMixIn, DeviceOperationMixIn):
    camera = None
    _img_buf = None

    @staticmethod
    def check_opencv():
        global cv2
        if not cv2:
            try:
                cv2 = import_module("cv2")
            except ImportError:
                logger.error("Import cv2 error, please make sure opencv for "
                             "python is installed")
                raise RuntimeError(NOT_SUPPORT)

    def __init__(self, server, sock, camera_id=None):
        if camera_id is None:
            camera_id = hal_config.get("scan_camera")
            if camera_id is None:
                raise RuntimeError(NOT_SUPPORT, "Camera id nog given")

        self.quality = 80
        self.step_length = 0.45

        self.check_opencv()
        self.server = server
        self.init_device(camera_id)
        ExclusiveMixIn.__init__(self, server, sock)

    def on_exit(self, sender):
        self.disconnect()
        self.camera.release()

    def init_device(self, camera_id):
        self.connect(mainboard_only=True)
        self.camera = cv2.VideoCapture(camera_id)

        try:
            init_gcodes = ["G28", "M302", "M907 Y0.4", "T1", "G91"]
            for cmd in init_gcodes:
                ret = self.make_gcode_cmd(cmd)
                if not ret.endswith("ok"):
                    erro_msg = "GCode '%s' return '%s'" % (cmd, ret)
                    logger.error(erro_msg)
                    raise RuntimeError(DEVICE_ERROR, erro_msg)
        except:
            self.camera.release()
            raise

    def make_gcode_cmd(self, cmd):
        self._uart_mb.send(("%s\n" % cmd).encode())
        return self._uart_mb.recv(128).decode("ascii", "ignore").strip()

    def dispatch_cmd(self, cmd, sock):
        if cmd == "oneshot":
            self._take_image(sock)
            return "ok"

        elif cmd == "scanlaser":
            return self.change_laser(left=False, right=False)

        elif cmd.startswith("scanlaser "):
            params = cmd.split(" ")[-1]
            l_on = "l" in params
            r_on = "r" in params
            return self.change_laser(left=l_on, right=r_on)

        elif cmd.startswith("set steplen "):
            self.step_length = float(cmd.split(" ")[-1])
            return "ok"

        elif cmd == "scanimages":
            self.take_images(sock)
            return "ok"

        elif cmd == "scan_forword":
            ret = self.make_gcode_cmd("G1 F500 E-%.5f" % self.step_length)
            if ret == "ok":
                return ret
            else:
                raise RuntimeError(DEVICE_ERROR, ret)

        elif cmd == "scan_next":
            ret = self.make_gcode_cmd("G1 F500 E%.5f" % self.step_length)
            if ret == "ok":
                return ret
            else:
                raise RuntimeError(DEVICE_ERROR, ret)

        elif cmd == "quit":
            self.server.exit_task(self)
            return "ok"

        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    def change_laser(self, left, right):
        self.make_gcode_cmd("X1O" if left else "X1F")
        self.make_gcode_cmd("X2O" if right else "X2F")
        return "ok"

    def take_images(self, sock):
        self.change_laser(left=True, right=False)
        self._take_image(sock)
        self.change_laser(left=False, right=True)
        self._take_image(sock)
        self.change_laser(left=False, right=False)
        self._take_image(sock)
        return "ok"

    def _take_image(self, sock):
        try:
            for i in range(4):
                while not self.camera.grab():
                    pass
            ret, self._img_buf = self.camera.read(self._img_buf)
            while not ret:
                logger.error("Take image failed")
                ret, self._img_buf = self.camera.read(self._img_buf)

            # Convert IMWRITE_JPEG_QUALITY from long type to int (a bug)
            ret, buf = cv2.imencode(".jpg", self._img_buf,
                                    [int(cv2.IMWRITE_JPEG_QUALITY),
                                     self.quality])

            total, sent = len(buf), 0
            sock.send_text("binary image/jpeg %i" % total)
            while sent < total:
                sent += sock.send(buf[sent:sent + 4096].tostring())

        except Exception:
            logger.exception("ERR")
