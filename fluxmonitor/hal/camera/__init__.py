
from fluxmonitor import halprofile

if halprofile.PLATFORM == halprofile.LINUX_PLATFORM:
    from ._v4l2_camera import V4l2Camera as Camera
else:
    from ._cv2_camera import CV2Camera as Camera


delta_camera_option = None


class Cameras(object):
    def __init__(self):
        camera_model = halprofile.PROFILE.get("scan_camera_model")
        if camera_model == 2:
            self._camera = Camera(0, width=1280, height=720)
        else:
            global delta_camera_option

            if delta_camera_option is None:
                from fluxmonitor.storage import Storage
                storage = Storage("general", "meta")
                delta_camera_option = 1 if storage["camera_version"] == "1" \
                    else 0

            if delta_camera_option == 1:
                self._camera = Camera(0, width=1280, height=720)
            else:
                self._camera = Camera(0)

    def __getitem__(self, camera_id):
        return self._camera

    def attach(self):
        self._camera.attach()

    def release(self):
        self._camera.release()
