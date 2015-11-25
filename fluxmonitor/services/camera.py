
from io import BytesIO
import logging
import struct
import socket
import pyev
import os

try:
    import cv2
    from fluxmonitor.misc.scan_checking import ScanChecking
except ImportError:
    cv2 = None
    ScanChecking = None

from fluxmonitor.config import CAMERA_ENDPOINT
from .base import ServiceBase

logger = logging.getLogger(__name__)
IMAGE_QUALITY = 80


class CameraService(ServiceBase):
    cameras = None

    def __init__(self, options):
        super(CameraService, self).__init__(logger)

        logger.info("Open internal socket at %s", CAMERA_ENDPOINT)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(CAMERA_ENDPOINT)
        s.listen(2)
        self.sys_sock_watcher = self.loop.io(s, pyev.EV_READ,
                                             self.on_internal_connected, s)
        self.sys_sock_watcher.start()

        self.internal_conn = []

    def on_start(self):
        logger.info("Camera service started")

    def on_shutdown(self):
        self.sys_sock_watcher.data.close()
        self.sys_sock_watcher = None
        os.unlink(CAMERA_ENDPOINT)

    def update_camera_status(self):
        if self.internal_conn:
            if not self.cameras:
                self.initial_cameras()
        else:
            if self.cameras:
                self.release_cameras()

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

    def on_internal_connected(self, watcher, revent):
        sock, endpoint = watcher.data.accept()
        w = self.loop.io(sock, pyev.EV_READ, self.on_internal_request,
                         InternalSocketWrapper(sock))
        w.start()
        self.internal_conn.append(w)
        self.update_camera_status()

    # def on_external_connected(self, watcher, revent):
    #     pass

    def on_internal_request(self, watcher, revent):
        try:
            watcher.data.on_recv()
            cmd = watcher.data.fetch_command()
            if cmd:
                self.handle_command(watcher, cmd[0], cmd[1])
        except CameraProtocolError:
            watcher.data.close()
            watcher.stop()
            self.internal_conn.remove(watcher)
            self.update_camera_status()

    def handle_command(self, watcher, cmd_id, camera_id):
        camera = self.cameras[camera_id]
        if cmd_id == 0:
            camera.fetch()
            mimetype, length, stream = camera.imagefile
            watcher.data.send_image(mimetype, length, stream, self.loop)


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


class InternalSocketWrapper(object):
    writer = None

    def __init__(self, s):
        self.s = s
        self.buf = b""

    def on_recv(self):
        buf = self.s.recv(2 - len(self.buf))
        if not buf:
            raise CameraProtocolError("DISCONNECTED")
        self.buf += buf

    def fetch_command(self):
        if len(self.buf) == 2:
            swap = self.buf
            self.buf = b""
            return struct.unpack("<BB", swap)

    def send_text(self, message):
        buf = struct.pack("<H", len(message)) + message
        self.s.send(buf)

    def send_image(self, mimetype, length, stream, loop):
        self.send_text(msg)

        if self.writer:
            raise CameraProtocolError(PROTOCOL_ERROR)

        self.writer = loop.io(self.s, pyev.EV_WRITE, self.on_send, stream)
        self.writer.start()

    def on_send(self, watcher, revent):
        buf = watcher.data.read(4096)
        if buf:
            self.s.send(buf)
        else:
            watcher.stop()
            self.writer = None

    def close(self):
        self.s.close()


class CameraProtocolError(SystemError):
    pass