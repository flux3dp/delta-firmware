
from fluxmonitor import halprofile

if halprofile.PLATFORM == halprofile.LINUX_PLATFORM:
    from ._v4l2_camera import V4l2Camera as Camera
else:
    from ._cv2_camera import CV2Camera as Camera


class Cameras(object):
    def __init__(self):
        self._camera = Camera(0)

    def __getitem__(self, camera_id):
        return self._camera

    def attach(self):
        self._camera.attach()

    def release(self):
        self._camera.release()