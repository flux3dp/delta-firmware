from tempfile import TemporaryFile
import logging

from fluxmonitor.interfaces.hal_internal import HalControlClientHandler
from fluxmonitor.err_codes import (PROTOCOL_ERROR,
                                   SUBSYSTEM_ERROR,
                                   TIMEOUT,
                                   UNKNOWN_ERROR)
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.storage import Storage

logger = logging.getLogger(__name__)


class UpdateHbFwTask(object):
    timer_watcher = None
    hal_handler = None

    def __init__(self, stack, handler, length):
        self.stack = stack
        self.tmpfile = TemporaryFile()
        self.padding_length = length
        handler.binary_mode = True

    def on_exit(self):
        if self.timer_watcher:
            self.timer_watcher.stop()
            self.timer_watcher = None
        if self.hal_handler:
            self.hal_handler.close()
            self.hal_handler = None

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

                logger.info("Head fireware uploaded, start processing")
                handler.send_text("ok")
                self.process_update(handler)
                # Note: self.process_update will invoke self.stack.exit_task
        except RuntimeError as e:
            handler.send_text(("error %s" % e.args[0]).encode())
        except Exception:
            logger.exception("Unhandle Error")
            handler.send_text("error " + UNKNOWN_ERROR)

    def process_update(self, handler):
        shared_st = {"ts": time(), "closed": False}

        def on_timer(watcher, revent):
            if time() - shared_st["ts"] > 15 and shared_st["closed"] is False:
                shared_st["closed"] is True
                handler.send_text("er " + TIMEOUT)
                self.stack.exit_task(self, False)

        def on_callback(params, hal_handler):
            shared_st["ts"] = time()

            if params[0] == "proc":
                if "BHE" in params[1]:
                    logger.debug("STAGE: %s", params[1])
                    handler.send_text("CTRL INIT")
                elif params[1] == "W":
                    logger.debug("STAGE: RTG")
                    handler.send_text("CTRL RTG")
                elif params[1][0] == "0":
                    left = int(params[1], 16)
                    logger.debug("WRITE: %i", left)
                    handler.send_text("CTRL WRITE %i" % left)
            elif params[0] == "ok":
                handler.send_text("ok")
                shared_st["closed"] = True
                self.stack.exit_task(self, True)
            elif params[0] == "error":
                handler.send_text("er " + " ".join(params[1:]))
                shared_st["closed"] = True
                self.stack.exit_task(self, False)

        def on_hal_close(*args):
            if shared_st["closed"] is False:
                shared_st["closed"] is True
                handler.send_text("error %s" % SUBSYSTEM_ERROR)
                self.stack.exit_task(self, True)

        self.timer_watcher = self.stack.loop.timer(3, 3, on_timer)
        self.timer_watcher.start()

        self.hal_handler = HalControlClientHandler(
            self.stack, on_close_callback=on_hal_close)

        self.hal_handler.request_update_toolhead(on_callback)
