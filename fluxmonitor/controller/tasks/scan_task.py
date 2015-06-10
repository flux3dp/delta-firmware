
from importlib import import_module
from time import sleep
import logging

from fluxmonitor.config import hal_config
from fluxmonitor.err_codes import DEVICE_ERROR, NOT_SUPPORT, UNKNOW_COMMAND
from .base import CommandMixIn, DeviceOperationMixIn

logger = logging.getLogger(__name__)
cv2 = None


class ScanTask(CommandMixIn, DeviceOperationMixIn):
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
        self.step_length = 0.46545

        self.check_opencv()
        self.server = server
        self.init_device(camera_id)

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

    def on_mainboard_message(self, sender):
        logger.warn("Recive additional message from mainboard: %s" % 
                    sender.obj.recv(4096).decode("utf8", "ignore"))

    def dispatch_cmd(self, cmd, sock):
        if cmd == "oneshot":
            self._take_image(sock)
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
            self.disconnect()
            self.camera.release()
            self.server.exit_task(self)

        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    def take_images(self, sock):
        ret = self.make_gcode_cmd("@X1O")
        self._take_image(sock)
        ret = self.make_gcode_cmd("@X2O")
        ret = self.make_gcode_cmd("@X1F")
        self._take_image(sock)
        ret = self.make_gcode_cmd("@X2F")
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
            sock.send("binary image/jpeg %i" % total)
            while sent < total:
                sent += sock.send(buf[sent:sent + 4096].tostring())

        except Exception as e:
            logger.exception("ERR")
