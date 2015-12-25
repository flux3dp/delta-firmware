
from fluxmonitor.config import SCAN_CAMERA_ID


def get_scan_camera(camera_id=None):
    from cv2 import VideoCapture

    if camera_id is not None:
        return VideoCapture(int(camera_id))
    elif SCAN_CAMERA_ID is not None:
        return VideoCapture(SCAN_CAMERA_ID)
    else:
        raise RuntimeError("NOT_SUPPORT", "can not find scan camera")
