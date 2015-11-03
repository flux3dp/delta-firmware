
import os


def get_entry():
    base = "/media/usb"
    for i in xrange(10):
        node = base + str(i)
        if os.path.ismount(node):
            return node
    return None
