
from io import BytesIO

try:
    import cv2
except ImportError:
    cv2 = None

from fluxmonitor.err_codes import HARDWARE_ERROR
from fluxmonitor.misc.systime import systime

IMAGE_QUALITY = 80


class Cameras(object):
    def __init__(self):
        self._camera = Camera(0)

    def __getitem__(self, camera_id):
        return self._camera

    def attach(self):
        self._camera.attach()

    def release(self):
        self._camera.release()


class Camera(object):
    ts = 0
    obj = None
    img_buf = None

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.img_buf = None
        self._img_file = None

    def fetch(self):
        # Take a new photo immediately
        if not self.obj:
            self.attach()

        for i in range(4):
            ttl = 4
            while not self.obj.grab() and ttl > 0:
                ttl -= 1

        ret, self.img_buf = self.obj.read(self.img_buf)
        self.ts = systime()
        while not ret:
            raise RuntimeError(HARDWARE_ERROR, "CAMERA", str(self.camera_id))
        self._img_file = None
        return self.img_buf

    @property
    def imagefile(self):
        if not self._img_file:
            ret, buf = cv2.imencode(".jpg", self.img_buf,
                                    [int(cv2.IMWRITE_JPEG_QUALITY),
                                     IMAGE_QUALITY])
            self._img_file = buf
        return ("image/jpeg", len(buf), BytesIO(self._img_file))

    def attach(self):
        if self.obj:
            self.release()
        self.obj = cv2.VideoCapture(0)

    def release(self):
        if self.obj:
            self.obj.release()
            self.obj = None
