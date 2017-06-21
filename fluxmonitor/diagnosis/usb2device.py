
from select import select
from time import time
import socket
import os


def get_scan_camera(camera_id=None):
    from cv2 import VideoCapture

    if camera_id is not None:
        return VideoCapture(int(camera_id))
    else:
        raise RuntimeError("NOT_SUPPORT", "can not find scan camera")


def usb2mainboard(usb_serial, mainboard_unixsocket_endpoint):
    mb_serial = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    mb_serial.connect(mainboard_unixsocket_endpoint)

    timer = time()
    zero_counter = 0

    while time() - timer < 60:
        rl = select((usb_serial, mb_serial), (), (), 0.05)[0]
        if usb_serial in rl:
            timer = time()
            b = usb_serial.recv(1)
            if b == b"\x00":
                zero_counter += 1
                if zero_counter >= 16:
                    break
            elif b == b";":
                zero_counter = 0
            else:
                zero_counter = 0
                mb_serial.send(b)
        if mb_serial in rl:
            buf = mb_serial.recv(4096)
            usb_serial.send(buf)

    mb_serial.close()


def usb2camera(usb_serial, ttl=100):
    try:
        import cv2

        camera = get_scan_camera(0)
        for i in range(4):
            while not camera.grab():
                if ttl > 0:
                    ttl -= 1
                else:
                    raise RuntimeError("CAMERA_ERROR")
        ret, img_buf = camera.read()
        if not ret:
            raise RuntimeError("Camera does not return image")
        ret, buf = cv2.imencode(".jpg", img_buf,
                                [int(cv2.IMWRITE_JPEG_QUALITY),
                                 80])
        usb_serial.send(b"Y")
        usb_serial.send(("%8x" % len(buf)).encode())

        ptr = 0
        while ptr < len(buf):
            l = usb_serial.send(buf[ptr:ptr + 4096])
            ptr += l
    except Exception as err:
        usb_serial.send(b"N")
        errstr = repr(err).encode()
        usb_serial.send(("%8x" % len(errstr)).encode())
        usb_serial.send(errstr)


def enable_console():
    return os.system("systemctl start serial-getty@ttyUSB0.service")


def enable_ssh():
    os.system("dpkg-reconfigure openssh-server")
    os.system("systemctl enable ssh.service")
    return os.system("systemctl start ssh.service")
