
from weakref import WeakSet
from io import BytesIO
import logging

try:
    import cv2
    import numpy as np
    from fluxmonitor.misc.scan_checking import ScanChecking
except ImportError:
    cv2 = None
    ScanChecking = None

from fluxmonitor.interfaces.camera import CameraUnixStreamInterface
from .base import ServiceBase

logger = logging.getLogger(__name__)
IMAGE_QUALITY = 80


class CameraService(ServiceBase):
    cameras = None

    def __init__(self, options):
        super(CameraService, self).__init__(logger)

        self.internal_ifce = CameraUnixStreamInterface(self)
        self.internal_conn = WeakSet()
        self.live_conn = WeakSet()

        self.timer_w = self.loop.timer(0.1, 0, self.on_timer)

    def on_timer(self, watcher, revent):
        pass

    def on_start(self):
        logger.info("Camera service started")

    def on_shutdown(self):
        self.internal_ifce.close()

    def initial_cameras(self):
        try:
            self.cameras = [CameraControl(0)]
        except Exception:
            logger.exception("Camera initial failed")

    def release_cameras(self):
        if self.cameras:
            for c in self.cameras:
                c.release()
            self.cameras = None

    def update_camera_status(self):
        if self.internal_conn:
            if not self.cameras:
                self.initial_cameras()
        else:
            if self.cameras:
                self.release_cameras()

    def makeshot(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        camera.fetch()
        return camera.imagefile

    def scan_checking(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        sc = ScanChecking()
        img = camera.fetch()
        return sc.check(img)

    def get_bias(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        img = camera.fetch()
        flag, points = ScanChecking.find_board(img)
        cv2.imwrite('/home/pi/tmp1.jpg', img)

        if flag:
            ################################
            tmp = np.copy(camera.img_buf)
            cv2.drawChessboardCorners(tmp, ScanChecking.corner, points, flag)
            cv2.imwrite('/home/pi/tmp.jpg', tmp)
            ################################

        if flag:
            return ScanChecking.get_bias(points)
        else:
            return 'nan'

    def compute_cab(self, camera_id, cmd):
        # API for client
        camera = self.cameras[camera_id]

        if cmd == 3:
            # no need to take photo again, just retrieve the img buffer
            self.img_o = np.copy(camera.img_buf)
            _, points = ScanChecking.find_board(self.img_o)
            self.s = 0
            for i in xrange(16):
                self.s += points[i][0][0]
            self.s /= 16

            logger.info('find calibrat board center ' + str(self.s))
            # cv2.imwrite('/home/pi/tmp_O.jpg', self.img_o)
            return self.s
        else:
            img_r = camera.fetch()

            result = ScanChecking.find_red(self.img_o, img_r)
            logger.info('{}:red at {}'.format(cmd, result))
            ################################
            for h in xrange(img_r.shape[0]):
                img_r[h][result][0] = 255
                img_r[h][result][1] = 255
                img_r[h][result][2] = 255
            cv2.imwrite('/home/pi/tmp_R{}.jpg'.format(cmd), img_r)
            ################################
            # w = img_r.shape[1] / 2  # 640 / 2 = 320
            if cmd == 5:
                del self.img_o
                del self.s

            if result:
                return result
            else:
                return 'fail'


class CameraControl(object):
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.camera = cv2.VideoCapture(0)
        self.img_buf = None
        self._img_file = None

    def fetch(self):
        for i in range(4):
            while not self.camera.grab():
                pass
        ret, self.img_buf = self.camera.read(self.img_buf)
        while not ret:
            logger.error("Take image failed (camera id=%i)", self.camera_id)
            ret, self.img_buf = self.camera.read(self.img_buf)
        self._img_file = None
        return self.img_buf

    @property
    def imagefile(self):
        if not self._img_file:
            ret, buf = cv2.imencode(".jpg", self.img_buf,
                                    [int(cv2.IMWRITE_JPEG_QUALITY),
                                     IMAGE_QUALITY])
        return ("image/jpeg", len(buf), BytesIO(buf))

    def release(self):
        self.camera.release()
        self.camera = None
        self.img_buf = None
        self._img_file = None
