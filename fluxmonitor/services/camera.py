
import logging

try:
    import cv2
    import numpy as np
    from fluxmonitor.misc.scan_checking import ScanChecking
except ImportError:
    cv2 = None
    ScanChecking = None

from fluxmonitor.interfaces.camera import (CameraTcpInterface,
                                           CameraUnixStreamInterface)

from fluxmonitor.hal.camera import Cameras
from .base import ServiceBase

logger = logging.getLogger(__name__)


class CameraService(ServiceBase):
    cameras = None

    def __init__(self, options):
        super(CameraService, self).__init__(logger)
        self.cameras = Cameras()

        self.public_ifce = CameraTcpInterface(self)
        self.internal_ifce = CameraUnixStreamInterface(self)

    def on_start(self):
        logger.info("Camera service started")

    def on_shutdown(self):
        self.public_ifce.close()
        self.internal_ifce.close()

    def on_client_connected(self):
        self.cameras.attach()

    def on_client_gone(self):
        if not self.internal_ifce.clients and not self.public_ifce.clients:
            self.cameras.release()

    def live(self, camera_id, ts):
        # API for client
        camera = self.cameras[camera_id]
        ts = camera.live(ts)
        return ts, camera.imagefile

    def makeshot(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        camera.fetch()
        return camera.imagefile

    def scan_checking(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        sc = ScanChecking()
        camera.fetch()
        img = cv2.imdecode(np.fromstring(camera.imagefile[2].getvalue(), np.uint8), cv2.CV_LOAD_IMAGE_COLOR)
        return sc.check(img)

    def get_bias(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        camera.fetch()
        img = cv2.imdecode(np.fromstring(camera.imagefile[2].getvalue(), np.uint8), cv2.CV_LOAD_IMAGE_COLOR)
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
            camera.fetch()
            img_r = cv2.imdecode(np.fromstring(camera.imagefile[2].getvalue(), np.uint8), cv2.CV_LOAD_IMAGE_COLOR)

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
