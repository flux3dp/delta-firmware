
from select import select
from time import time
import socket


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


def usb2camera(usb_serial):
    try:
        from fluxmonitor.hal.camera import get_scan_camera
        import cv2

        camera = get_scan_camera(0)
        for i in range(4):
            while not camera.grab():
                pass
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
