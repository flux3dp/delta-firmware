
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

    def live(self, ts):

        if systime() - ts > 0.1:
            self.fetch(0)

        return self.ts

    def fetch(self, clear_cache=4):
        # Take a new photo immediately
        if not self.obj:
            self.attach()

        success_count = 0
        for i in range(16):  # try at most 16 times
            if success_count >= clear_cache:  # 4 success is enough
                break
            if self.obj.grab():
                success_count += 1

        ret, self.img_buf = self.obj.read(self.img_buf)
        if not ret:
            raise RuntimeError(HARDWARE_ERROR, "CAMERA", str(self.camera_id))
        self.ts = systime()
        self._img_file = None
        return self.img_buf

    @property
    def imagefile(self):
        if self._img_file is None:
            ret, buf = cv2.imencode(".jpg", self.img_buf,
                                    [int(cv2.IMWRITE_JPEG_QUALITY),
                                     IMAGE_QUALITY])
            self._img_file = buf
        return ("image/jpeg", len(self._img_file), BytesIO(self._img_file))

    def attach(self):
        if self.obj:
            self.release()
        self.obj = cv2.VideoCapture(0)

    def release(self):
        if self.obj:
            self.obj.release()
            self.obj = None
