
from json import dumps
import logging


logger = logging.getLogger(__name__)


class UpnpSubsystem(CommandMixIn):
    def __init__(self, stack, handler):
        super(UpnpSubsystem, self).__init__(stack, handler)
        self.stack = stack
        self.handler = handler
        handler.send_text("ok")

    def dispatch_cmd(self, handler, cmd, *args):
        if cmd == "stop_load_filament":
            self.mainboard.send_cmd("@HOME_BUTTON_TRIGGER\n", raw=1)
            return
        elif self._busy:
            raise RuntimeError(RESOURCE_BUSY)

        if cmd == "home":
            self.do_home(handler)

        elif cmd == "calibration" or cmd == "calibrate":
            try:
                threshold = float(args[0])
                if threshold < 0.01:
                    threshold = 0.01
            except (ValueError, IndexError):
                threshold = float("inf")

            clean = "clean" in args
            self.do_calibrate(handler, threshold, clean=clean)

        elif cmd == "zprobe":
            if len(args) > 0:
                h = float(args[0])
                self.do_h_correction(handler, h=h)
            else:
                self.do_h_correction(handler)

        elif cmd == "load_filament":
            self.do_load_filament(handler, int(args[0]), float(args[1]))

        elif cmd == "unload_filament":
            self.do_unload_filament(handler, int(args[0]), float(args[1]))

        elif cmd == "headinfo":
            self.head_info(handler)

        elif cmd == "headstatus":
            self.head_status(handler)

        elif cmd == "reset_mb":
            reset_mb()
            self.stack.exit_task(self)
            handler.send_text("ok")

        elif cmd == "extruder_temp":
            self.do_change_extruder_temperature(handler, *args)

        elif cmd == "x78":
            self.do_x78(handler)

        elif cmd == "update_head":
            self.update_toolhead_fw(handler, *args)

        elif cmd == "quit":
            self.stack.exit_task(self)
            handler.send_text("ok")
        else:
            logger.debug("Can not handle: '%s'" % cmd)
            raise RuntimeError(UNKNOWN_COMMAND)

    def on_exit(self):
        return True
