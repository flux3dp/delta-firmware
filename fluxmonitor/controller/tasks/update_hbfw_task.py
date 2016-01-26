from tempfile import TemporaryFile
from select import select
import logging
import socket

from fluxmonitor.err_codes import PROTOCOL_ERROR, SUBSYSTEM_ERROR, \
    TIMEOUT, UNKNOWN_ERROR
from fluxmonitor.config import HALCONTROL_ENDPOINT
from fluxmonitor.storage import Storage

logger = logging.getLogger(__name__)


class UpdateHbFwTask(object):
    def __init__(self, stack, handler, length):
        self.stack = stack
        self.tmpfile = TemporaryFile()
        self.padding_length = length
        handler.binary_mode = True

    def on_exit(self):
        pass

    def on_text(self, message, handler):
        raise SystemError(PROTOCOL_ERROR, "UPLOADING_BINARY")

    def on_binary(self, buf, handler):
        try:
            l = len(buf)

            if self.padding_length > l:
                self.tmpfile.write(buf)
                self.padding_length -= l

            else:
                if self.padding_length == l:
                    self.tmpfile.write(buf)
                else:
                    self.tmpfile.write(buf[:self.padding_length])
                handler.binary_mode = False

                self.tmpfile.seek(0)
                s = Storage("update_fw")

                with s.open("head.bin", "wb") as f:
                    f.write(self.tmpfile.read())

                logging.info("Head fireware uploaded, start processing")
                handler.send_text("ok")
                self.process_update(handler)

                self.stack.exit_task(self, True)
        except RuntimeError as e:
            handler.send_text(("error %s" % e.args[0]).encode())
        except Exception:
            logger.exception("Unhandle Error")
            handler.send_text("error %s" % UNKNOWN_ERROR)

    def process_update(self, handler):
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(HALCONTROL_ENDPOINT)
            s.send("update_head_fw")
            stage = 0
            while True:
                rl = select((s, ), (), (), 15.0)[0]
                if not rl:
                    handler.send_text(b"er " + TIMEOUT.encode())
                    return
                if stage == 0:
                    buf = s.recv(1)
                    if buf in "BHE":
                        logger.debug("STAGE: %s", buf)
                        handler.send_text("CTRL INIT")
                    elif buf == "W":
                        stage = 1
                        logger.debug("STAGE: RTG")
                        handler.send_text("CTRL RTG")
                    elif buf == "e":
                        buf += s.recv(4096)
                        logger.debug("ERR: %s", buf)
                        if buf.startswith("er "):
                            handler.send_text("error " + buf[3:])
                        else:
                            handler.send_text("error " + UNKNOWN_ERROR + " " +
                                              buf)
                        return
                    else:
                        handler.send_text("error " + UNKNOWN_ERROR)
                elif stage == 1:
                    buf = s.recv(8, socket.MSG_WAITALL)
                    left = int(buf, 16)
                    logger.debug("WRITE: %i", left)
                    handler.send_text("CTRL WRITE %i" % left)
                    if left == 0:
                        stage = 2
                else:
                    buf = s.recv(8)
                    if buf == "ok":
                        logger.debug("done")
                        handler.send_text("ok")
                    elif buf.startswith("er "):
                        handler.send_text("error " + buf[3:])
                    else:
                        handler.send_text("error " + UNKNOWN_ERROR + " " + buf)
                    return
        except socket.error:
            raise RuntimeError(SUBSYSTEM_ERROR)
        finally:
            s.close()
