
from fluxmonitor.config import hal_config


def get_scan_camera(camera_id=None):
    from cv2 import VideoCapture

    profile = halprofile.get_model_id()

    if camera_id is not None:
        return VideoCapture(int(camera_id))
    elif hal_config["scan_camera"] is not None:
        return VideoCapture(camera_id)
    else:
        raise RuntimeError("NOT_SUPPORT", "can not find scan camera")
