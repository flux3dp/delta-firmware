
from collections import deque
import logging

try:
    import cv2
    import numpy as np
    from fluxmonitor.misc.scan_checking import ScanChecking
except ImportError:
    cv2 = None
    ScanChecking = None

from fluxmonitor.interfaces.camera import (CameraTcpInterface,
                                           CameraCloudHandler,
                                           CameraUnixStreamInterface)

from fluxmonitor.hal.camera import Cameras
from .base import ServiceBase

logger = logging.getLogger(__name__)


class CameraService(ServiceBase):
    FPS = 4.0
    SPF = 1.0 / FPS
    cameras = None
    cloud_conn = None

    def __init__(self, options):
        super(CameraService, self).__init__(logger)
        self.cameras = Cameras()

        self.public_ifce = CameraTcpInterface(self)
        self.internal_ifce = CameraUnixStreamInterface(self)

        self.live_queue = deque()
        self.live_timer = self.loop.timer(self.SPF, self.SPF, self.on_live)

    def on_start(self):
        logger.info("Camera service started")

    def on_shutdown(self):
        self.public_ifce.close()
        self.internal_ifce.close()

    def on_connected(self, handler):
        if not self.live_timer.active:
            self.live_timer.start()

    def on_disconnected(self, handler):
        if not self.internal_ifce.clients and not self.public_ifce.clients:
            self.cameras.release()
            if self.live_timer.active:
                self.live_timer.stop()

    def on_connect2cloud(self, camera_id, endpoint, token):
        if self.cloud_conn:
            self.cloud_conn.close()
            self.cloud_conn = None

        def on_close(agent):
            self.cloud_conn = None

        self.cloud_conn = CameraCloudHandler(self, endpoint, token, on_close)

    def on_live(self, watcher=None, revent=None):
        while self.live_queue:
            h = self.live_queue.popleft()
            try:
                h.next_frame()
            except Exception:
                h.close()
                logger.exception("Error at next frame in timer")

    def add_to_live_queue(self, handler):
        if handler not in self.live_queue:
            self.live_queue.append(handler)

    def live(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        ts = camera.live()
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
        img = cv2.imdecode(np.fromstring(camera.imagefile[2].getvalue(),
                                         np.uint8),
                           cv2.CV_LOAD_IMAGE_COLOR)
        return sc.check(img)

    def get_bias(self, camera_id):
        # API for client
        camera = self.cameras[camera_id]
        camera.fetch()
        img = cv2.imdecode(np.fromstring(camera.imagefile[2].getvalue(),
                                         np.uint8),
                           cv2.CV_LOAD_IMAGE_COLOR)
        flag, points = ScanChecking.find_board(img)
        cv2.imwrite('/home/pi/tmp1.jpg', img)

        if flag:
            return ScanChecking.get_bias(points)
        else:
            return 'nan'

    def compute_cab(self, camera_id, cmd):
        # API for client
        camera = self.cameras[camera_id]

        if cmd == 3:
            # no need to take photo again, just retrieve the img buffer
            camera.fetch()
            self.img_o = cv2.imdecode(
                np.fromstring(camera.imagefile[2].getvalue(), np.uint8),
                cv2.CV_LOAD_IMAGE_COLOR)
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
            img_r = cv2.imdecode(np.fromstring(camera.imagefile[2].getvalue(),
                                               np.uint8),
                                 cv2.CV_LOAD_IMAGE_COLOR)

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
