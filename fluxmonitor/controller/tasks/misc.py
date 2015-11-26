
from multiprocessing import Process
from select import select, error
from errno import EINTR
import socket

from setproctitle import setproctitle


class TaskLoader(Process):
    def __init__(self, task_file):
        self.io_in, self.io_out = socket.socketpair()
        self.fout = self.io_out.makefile("rb", -1)
        self.task_file = task_file

        super(TaskLoader, self).__init__(target=self.serve_forever)
        self.daemon = True
        self.start()

        # Remember to close after forked !!
        self.io_in.close()

    def serve_forever(self):
        setproctitle("fluxrobot TaskLoader")

        buf = bytearray(4096)
        view = memoryview(buf)
        l = 0
        offset = 0

        try:
            while True:
                if l == offset:
                    l = self.task_file.readinto(buf)
                    if l == 0:
                        self.io_in.close()
                        return
                    else:
                        offset = 0

                wl = select((), (self.io_in, ), (), 3.0)[1]
                if wl:
                    offset += self.io_in.send(view[offset:l])
        except error as e:
            if e.args[0] == EINTR:
                pass
            else:
                raise

    def readline(self):
        return self.fout.readline()

    def close(self):
        if self.is_alive():
            self.terminate()
        self.task_file.close()
        self.io_in.close()
        self.io_out.close()
        self.fout.close()
