
cdef extern from "usb_txrx.h":
    struct usb_data:
        short thread_flag[2]
    int discover_usb()
    int setup_usb(usb_data**) except -1
    int start_usb(usb_data *data) except -1
    void close_usb(usb_data *data)
    void free_usb(usb_data *data)


def attached_usb_devices():
    return discover_usb()


cdef class USBCable:
    cdef usb_data *usbdata
    cdef readonly int outside_sockfd

    def __init__(self):
        self.outside_sockfd = setup_usb(&(self.usbdata))

    def start(self):
        start_usb(self.usbdata)
        self.outside_sockfd = -1

    def is_alive(self):
        if self.usbdata == NULL:
            return 0
        else:
            return self.usbdata.thread_flag[0] and self.usbdata.thread_flag[1]

    def close(self):
        if self.usbdata != NULL:
            close_usb(self.usbdata);
            free_usb(self.usbdata);
            self.usbdata = NULL

    def __dealloc__(self):
        if self.usbdata != NULL:
            free_usb(self.usbdata)


