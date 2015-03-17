
from time import sleep
import threading
import select
import os

from fluxmonitor.misc.async_signal import AsyncSignal


class DelayWrite(object):
    def __init__(self, fd, delay=3.0):
        self.fd = fd
        self.sig = AsyncSignal()
        self.delay = 3.0
        self.start()

    def run(self):
        rl = select.select((self.fd, self.sig,), (), (), self.delay)[0]
        if self.fd && rl == []:
            os.write(target_df, b"!")

    def close(self):
        self.sig.send()
        self.join()
