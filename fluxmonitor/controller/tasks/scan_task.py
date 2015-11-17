
from importlib import import_module
from threading import Thread
from time import sleep
import logging

from fluxmonitor.err_codes import DEVICE_ERROR, NOT_SUPPORT, UNKNOW_COMMAND
from fluxmonitor.config import hal_config
from fluxmonitor.storage import Storage


from .base import ExclusiveMixIn, CommandMixIn, DeviceOperationMixIn

logger = logging.getLogger(__name__)
ScanChecking = None
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

        m = import_module("fluxmonitor.misc.scan_checking")
        global ScanChecking
        ScanChecking = m.ScanChecking

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

        self._background_job = None
        t = Thread(target=self._background_thread)
        t.daemon = True
        t.start()

    def _background_thread(self):
        while self.camera:
            if self._background_job:
                logger.debug("Proc %s" % repr(self._background_job))
                try:
                    self._background_job[0](*self._background_job[1])
                except Exception:
                    logger.exception("Unhandle Error")
                finally:
                    self._background_job = None
            else:
                sleep(0.005)
        logger.debug("Scan background thread quit")

    def on_exit(self, sender):
        self.disconnect()
        if self.camera:
            self.camera.release()
            self.camera = None

    def init_device(self, camera_id):
        self.connect(mainboard_only=True)
        self.camera = cv2.VideoCapture(camera_id)

        try:
            init_gcodes = ["G28", "M302", "M907 Y0.4", "T2", "G91"]
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
            self.oneshot(sock)

        elif cmd == "scanimages":
            self.take_images(sock)

        elif cmd == "scan_check":
            self.scan_check(sock)

        elif cmd == "get_cab":
            self.get_cab(sock)

        elif cmd == "calib":
            self.calib(sock)

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

        elif cmd == "scan_backward":
            ret = self.make_gcode_cmd("G1 F500 E-%.5f" % self.step_length)
            if ret != "ok":
                raise RuntimeError(DEVICE_ERROR, ret)
            sleep(0.05)
            return ret

        elif cmd == "scan_next":
            ret = self.make_gcode_cmd("G1 F500 E%.5f" % self.step_length)
            if ret != "ok":
                logger.error("Mainboard response %s rather then ok", repr(ret))
                raise RuntimeError(DEVICE_ERROR, ret)
            sleep(0.05)
            return ret

        elif cmd == "quit":
            self.server.exit_task(self)
            return "ok"

        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOW_COMMAND)

    def change_laser(self, left, right):
        self.make_gcode_cmd("X1O1" if left else "X1F1")
        self.make_gcode_cmd("X1O2" if right else "X1F2")
        sleep(0.02)
        return "ok"

    def scan_check(self, sock):
        self.server.remove_read_event(sock)
        self._background_job = (self.scan_check_worker, (sock, ))

    def get_cab(self, sock):
        s = Storage('camera')
        a = s.readall('calibration')
        if a is None:
            a = '0 0'
        self.sock.send_text(a)

    def get_img(self):
        self.camera_read()
        return self._img_buf

    def scan_check_worker(self, sock):
        # self.change_laser(left=True, right=True)
        img_o = self.get_img()
        _ScanChecking = ScanChecking()
        sock.send_text(str(_ScanChecking.check(img_o)))

        # self.change_laser(left=False, right=False)
        # self.camera_read()
        # img_l = self._img_buf

        self.server.add_read_event(sock)

    def calib(self, sock):
        _ScanChecking = ScanChecking()
        init_find = False
        tmp_cout = 4
        while tmp_cout:
            img = self.get_img()
            init_find = _ScanChecking.find_board(img)[0]
            if init_find:
                break
            else:
                ret = self.make_gcode_cmd("G1 F500 E%.5f" % (90))
                sleep(1)
            tmp_cout -= 1
        if tmp_cout == 0:
            logger.info('fail')
            # sock.send_text('fail')
        else:
            logger.info('find init')
            # sock.send_text('ok')
        sub_step = 100
        logger.info(self.shake_check())

        sock.send_text('yeah')

    def shake_check(self):
        img = self.get_img()
        if ScanChecking.find_board(img)[0]:
            base_a = [ScanChecking.chess_area(img)]

        for step_l in [0.9, -0.9]:
            i = 0
            now = 0
            while True:  # try this way
                ret = self.make_gcode_cmd("G1 F500 E%.5f" % (step_l))
                if ret == 'ok':
                    now += step_l
                    sleep(1)
                else:
                    logger.debug(ret)
                    continue

                img = self.get_img()
                if ScanChecking.find_board(img)[0]:
                    i += 1
                else:
                    pass
                a = ScanChecking.chess_area(img)
                base_a.append(a)
                logger.info('shake %f' % a)

                if i == 1:
                    break
            ret = self.make_gcode_cmd("G1 F500 E%.5f" % (-now))

        if base_a[0] < base_a[1] and base_a[0] > base_a[2]:
            return True  # keep going
        elif base_a[0] < base_a[1] and base_a[0] > base_a[2]:
            return False

    def oneshot(self, sock):
        self.server.remove_read_event(sock)
        self._background_job = (self._oneshot_worker, (sock, ))

    def _oneshot_worker(self, sock):
        try:
            self._take_image(sock)
            sock.send_text("ok")
        finally:
            self.server.add_read_event(sock)

    def take_images(self, sock):
        self.server.remove_read_event(sock)
        self.server.remove_read_event(self._async_mb)
        self._background_job = (self._take_images_worker, (sock, ))

    def _take_images_worker(self, sock):
        try:
            self.change_laser(left=True, right=False)
            self._take_image(sock)
            self.change_laser(left=False, right=True)
            self._take_image(sock)
            self.change_laser(left=False, right=False)
            self._take_image(sock)
            sock.send_text("ok")
        finally:
            self.server.add_read_event(self._async_mb)
            self.server.add_read_event(sock)

    def _take_image(self, sock):
        try:
            self.camera_read()
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

    def camera_read(self):
        try:
            for i in range(4):
                while not self.camera.grab():
                    pass
            ret, self._img_buf = self.camera.read(self._img_buf)
            while not ret:
                logger.error("Take image failed")
                ret, self._img_buf = self.camera.read(self._img_buf)
            return

        except Exception:
            logger.exception("ERR")
