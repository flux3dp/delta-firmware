
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

from fluxmonitor.err_codes import PROTOCOL_ERROR, DEVICE_ERROR
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

    def on_internal_disconnected(self, watcher):
        watcher.stop()
        watcher.data = None
        self.internal_conn.remove(watcher)
        self.update_camera_status()

    def on_internal_request(self, watcher, revent):
        try:
            watcher.data.on_recv()
            command = watcher.data.fetch_command()
            if command:
                self.handle_command(watcher, command[0], command[1])
        except CameraProtocolError as e:
            logger.debug("%s", e)
            self.on_internal_disconnected(watcher)
        except Exception:
            logger.exception("Unhandle error")
            self.on_internal_disconnected(watcher)

    def shake_check(self, camera):
        img = camera.fetch()
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

    def do_calib(self, handler, camera):
        _ScanChecking = ScanChecking()
        init_find = False
        tmp_cout = 4
        while tmp_cout:
            img = camera.fetch()
            init_find = _ScanChecking.find_board(img)[0]
            handler.send_text("ER BOARD_NOT_FIND")
            if init_find:
                break
            else:
                ret = self.make_gcode_cmd("G1 F500 E%.5f" % (90))
                sleep(1)
            tmp_cout -= 1
        if tmp_cout == 0:
            logger.info('fail')
            # handler.send_text('fail')
        else:
            logger.info('find init')
            # handler.send_text('ok')
        sub_step = 100
        logger.info(self.shake_check(camera))

        handler.send_text('yeah')

    def handle_command(self, watcher, cmd_id, camera_id):
        camera = self.cameras[camera_id]
        if cmd_id == 0:
            camera.fetch()
            mimetype, length, stream = camera.imagefile
            watcher.data.send_image(mimetype, length, stream, self.loop)
        elif cmd_id == 1:
            sc = ScanChecking()
            img = camera.fetch()
            watcher.data.send_text("ok " + sc.check(img))
        elif cmd_id == 2:
            self.do_calib(watcher.data, camera)
        else:
            raise CameraProtocolError("Unknow command")


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
            return struct.unpack("@BB", swap)

    def send_text(self, message):
        buf = struct.pack("@B", len(message)) + message
        self.s.send(buf)

    def send_image(self, mimetype, length, stream, loop):
        if self.writer:
            raise CameraProtocolError(PROTOCOL_ERROR)

        self.send_text("binary %s %i" % (mimetype, length))
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
