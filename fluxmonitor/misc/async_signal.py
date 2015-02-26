
import os

class AsyncSignal(object):
    def __init__(self):
        self.__w_closed = False
        self.__r_closed = False
        self.read_fd, self.write_fd = os.pipe()

    def fileno(self):
        return self.read_fd

    def recv(self):
        os.read(self.read_fd, 1)

    def send(self):
        os.write(self.write_fd, b" ")

    def __del__(self):
        self.close()

    def close_write(self):
        if self.__w_closed == False:
            self.__w_closed = True
            os.close(self.write_fd)

    def close_read(self):
        if self.__r_closed == False:
            self.__r_closed = True
            os.close(self.read_fd)

    def close(self):
        self.close_write()
        self.close_read()
