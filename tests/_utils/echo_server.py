
from threading import Thread
from select import select
import socket


class EchoServer(object):
    def __init__(self, endpoint, family=socket.AF_UNIX,
                 type=socket.SOCK_STREAM):
        self.sock = socket.socket(family, type)
        self.sock.bind(endpoint)
        self.sock.listen(1)
        self.running = True
        self.thread = Thread(target=self.serve_forever)
        self.thread.setDaemon(True)
        self.thread.start()

    def serve_forever(self):
        rlist = [self.sock]

        while self.running:
            rl = select(rlist, (), (), 0.5)[0]
            for r in rl:
                if r == self.sock:
                    req, addr = self.sock.accept()
                    rlist.append(req)
                else:
                    buf = r.recv(4096)
                    if buf:
                        r.send(buf)
                    else:
                        rlist.remove(r)

    def shutdown(self):
        self.running = False
        self.thread.join(3)
        self.sock.close()
        if self.thread.isAlive():
            raise SystemError("Can not stop echo server")


if __name__ == "__main__":
    from random import randint
    from time import sleep
    import tempfile
    import os
    endpoint = tempfile.gettempdir() + "/echo." + \
        str(randint(10000, 99999)) + ".sock"

    echo = EchoServer(endpoint)
    print("Listen at %s" % endpoint)

    try:
        while True:
            sleep(3)
    except KeyboardInterrupt:
        pass
    print("Shutdown")
    echo.shutdown()
    os.unlink(endpoint)
