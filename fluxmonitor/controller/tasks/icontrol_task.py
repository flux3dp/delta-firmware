
from collections import deque
from logging import getLogger
from weakref import proxy
import socket

from msgpack import Unpacker, packb

from fluxmonitor.player.main_controller import MainController
from fluxmonitor.player.head_controller import (HeadController,
                                                check_toolhead_errno,
                                                HeadError,
                                                HeadOfflineError,
                                                HeadResetError,
                                                HeadTypeError)


from fluxmonitor.err_codes import SUBSYSTEM_ERROR

# from fluxmonitor.player import macro
from fluxmonitor.storage import Metadata

from .base import DeviceOperationMixIn

logger = getLogger(__name__)

# TCP Connection part:
#   Send Command:
#     (INDEX, CMD_CODE, params_0, params_1, ..., keywords_dict)
#   Recv Message:
#     Cmd error
#     *NOTE: command will not be queued, cmd index will not shift either
#       (0xff, CMD_INDEX, ERROR_CODE)
#     Exec result:
#       (0x00 ~ 0xfe, params_0, params_1, ..., keywords_dict)
#
# Example:
# SEND -> (0, CMD_G028)
# SEND -> (1, CMD_G001, {"X": 3.2, "F": 10})     # Correct command
# RECV <- (0xff, 1, 0x01)                        # 0xff: ERROR occour
#                                                # 1: Command index 1
#                                                # 0x01: OPERATION_ERROR
# RECV <- (CMD_G028, 0, 20.0, 30.0, 20.0)        # G28 result
#
# SEND -> (1, CMD_G001, {"X": 3.2, "F": 10})     # Correct command
# SEND -> (2, CMD_G001, {"X": 100000, "F": 10})  # X overlimit
# RECV <- (0xff, 1, 0x01)
#
# SEND -> (2, CMD_G028)
# RECV <- (CMD_G028, 1, nan, nan, nan)           # G28 failed
#
#
# UDP Connection part
#   (i:0, s:salt, i:cmd_index, i:queued_size)
#       * First integer 0 means it is a status message
#       * salt: reserved
#       * cmd_index: next command index should given
#       * queued_size: command is waitting to be execute in system
#
#   (i:1, s:salt, i:timestamp, i:head_error_code, obj:headstatus)
#       * First integer 1 means it is a toolhead status message
#       * salt: reserved
#       * timestamp: reserved
#       * head_error_code:
#           == -2: Head Offline
#           == -1: Not ready
#            == 0: Ready
#             > 0: Follow toolhead error table
#
#   (i:2, s:salt, i:timestamp, ...)
#       * Please assume array size is dynamic
#       * First integer 2 means it is a user toolhead status message
#       * salt: reserved
#       * timestamp: reserved
#       * Element 3: Toolhead response message stack size

CMD_G001 = 0x01
# Move position
# ({i:F, f:X, f:Y, f:Z, f:E1, f:E2 , f:E3})
#
# E1, E2, E3 can not set at same time
# Dict must contains at least 1 key/value, otherwhise will get operation error

CMD_G004 = 0x02
# Sleep (seconds)
# (f:seconds)
#
# seconds must be positive

CMD_SLSR = 0x03
# Control red scan laser (On/Off)
# (i:flags)
#
# flags is a composite bit
# Bit 0: Left laser On/Off
# Bit 1: Right lasser On/Off

CMD_G028 = 0x10
# Home and return position
# ()
# TCP => (0x10, i:flag, f:X, f:Y, f:Z)
#
# if flag == 0:
#    Home successed
# else:
#    Error occour and X/Y/Z will be nan
#
# ATTENTION: G001 and G030 can not be used before G028 return successed

CMD_M017 = 0x11
# Lock all motors
# ()

CMD_M084 = 0x12
# Release all motors
# ()
#
# ATTENTION: G028 is required before using G001 and G030

CMD_G030 = 0x13
# Z-probe
# (f:x, f:y)
#            => (0x13, i:flag, f:z)
#
# if flag == 0:
#   Z-probe sucessed and the third value is z probe value.
# else:
#   Z-probe error and third value will always be nan.

CMD_M666 = 0x14
# Adjust
# ({f:X, f:Y, f:Z, f:H})
#
# X/Y/Z value must given at same time and one of them must be 0
# operation error will be raised if any value over hardware limit

CMD_VALU = 0x50
# Get device values, F: require flags
# (i:flags)
#           => (0x50, {f:X, f:Y, f:Z, b:F0, b:F1, b:thERR, b:MB})
#
# flags:
#  1: FSR           2: Filament 0      4: Filament 1
#  8: Master button

CMD_THPF = 0x51
# Get toolhead profile
# ()
#    => (0x51, {"module": "EXTRUDER", "vendor": "FLUX .inc", "id": "...", }, )

CMD_THRC = 0x5e
# Send raw command to toolhead, only vaild when toolhead type is USER/*
# (s:command)

CMD_THRR = 0x5f
# Recv raw command data from toolhead, only valid when toolhead type is USER/*
# ()
#    = (0x5f, ["COMMAND RESPONSE n", "COMMAND RESPONSE n + 1", ...])

CMD_M104 = 0x60
# Set toolhead extruder temperature
# (i:index, i:temperature)
#
# index: toolhead index, 0 or 1
# temperature should positive
# operation error raised if index out of range or temperature over limit

CMD_M106 = 0x61
# Set fandspeed
# (i:index, f:speed)
#
# index: toolhead index, 0 or 1
# speed is a value from 0.0 to 1.0

CMD_HLSR = 0x62
# Toolhead pwm
# (f:pwm)
#
# pwm is a value from 0.0 to 1.0

CMD_SYNC = 0xf0
# Set sync endpoint
# (s:ipv4address, i:port, s:salt)

CMD_REQH = 0xf1
# Set required toolhead type
# (s:toolhead symbol)
#
# Toolhead must be "EXTRUDER" or "LASER" or "N/A", default is "N/A"
# After CMD_REQH, A CMD_BSTH command is required to enable head, otherwise
# toolhead will keep status at -2 (offline)

CMD_BSTH = 0xf2
# bootstrap toolhead if toolhead status is == -2 (offline)

CMD_CLHE = 0xf3
# Clear toolhead error code
# ()
#
# When toolhead raise an error, this error will appear in UDP message frame
# until this command send.

CMD_QUIT = 0xfe
# Quit iContrl
#              => (0xfe, i:ST)
#
# Quit iControl, operation error will be raised if queue is not empty

CMD_KILL = 0xff
# KILL, iControl will quit and mainboard will be reset
#              => (0xfe, i:ST)


MSG_OPERATION_ERROR = 0x01
MSG_QUEUE_FULL = 0x02
MSG_BAD_PARAMS = 0x03
MSG_UNKNOWN_ERROR = 0xff

TARGET_MAINBOARD = 0
TARGET_TOOLHEAD = 1


class IControlTask(DeviceOperationMixIn):
    st_id = -3  # Device status ID
    main_e_axis = 0  # E axis control
    cmd_index = 0  # Command counter
    cmd_queue = None  # Command store queue
    udp_sock = None  # UDP socket to send status
    handler = None  # Client TCP connection object
    known_position = None  # Is toolhead position is known or not
    mainboard = None  # Mainborad Controller
    toolhead = None  # Headboard Controller
    head_resp_stack = None  # Toolhead raw rasponse stack

    def __init__(self, stack, handler):
        super(IControlTask, self).__init__(stack, handler)
        self.handler = proxy(handler)
        self.handler.binary_mode = True
        self.cmd_queue = deque()
        self.meta = Metadata.instance()

        self._ready = 0

        def on_mainboard_ready(ctrl):
            self._ready |= 1
            self.mainboard.send_cmd("X8F")
            self.mainboard.send_cmd("T0")
            self.mainboard.send_cmd("G90")
            self.mainboard.send_cmd("G92E0")
            handler.send_text("ok")

        self.mainboard = MainController(
            self._sock_mb.fileno(), bufsize=14,
            empty_callback=self.on_mainboard_empty,
            sendable_callback=self.on_mainboard_sendable,
            ctrl_callback=self.on_mainboard_result)
        self.toolhead = HeadController(
            self._sock_th.fileno(),
            msg_callback=self.toolhead_message_callback)

        self.mainboard.bootstrap(on_mainboard_ready)
        self.unpacker = Unpacker()

    def on_toolhead_ready(self, ctrl):
        self._ready |= 2

    @property
    def buflen(self):
        return len(self.cmd_queue) + self.mainboard.buffered_cmd_size

    def on_mainboard_empty(self, caller):
        self.fire()

    def on_mainboard_sendable(self, caller):
        self.fire()

    def toolhead_message_callback(self, sender, data):
        if data and self.head_resp_stack is not None and \
                len(self.head_resp_stack) <= 32:
            self.head_resp_stack.append(data)
            self.send_udp1(sender)

    def on_binary(self, buf, handler):
        self.unpacker.feed(buf)
        for payload in self.unpacker:
            self.process_cmd(handler, *payload)

    def process_cmd(self, handler, index, cmd, *params):
        if index != self.cmd_index:
            logger.debug("Ignore %s 0x%02x %s", index, cmd, params)
            return

        fn = CMD_MATRIX.get(cmd)
        try:
            if cmd < 0xf0:
                fn(self, handler, *params)
            else:
                fn(self, handler, *params)

            self.cmd_index += 1

        except InternalError as e:
            self.handler.send(packb((0xff, self.cmd_index, e[1])))

        except Exception:
            logger.exception("Unknown error during processing command")
            self.handler.send(packb((0xff, self.cmd_index, MSG_UNKNOWN_ERROR)))
            self.on_require_kill(handler)

    def fire(self):
        if self.cmd_queue:
            target, cmd = self.cmd_queue[0]
            if target == TARGET_MAINBOARD:
                if self.mainboard.queue_full:
                    return
                else:
                    self.cmd_queue.popleft()
                    self.mainboard.send_cmd(cmd)
            elif target == TARGET_TOOLHEAD:
                if self.mainboard.buffered_cmd_size == 0:
                    if self.toolhead.sendable():
                        self.cmd_queue.popleft()
                        # TODO
                        self.toolhead.send_cmd(cmd, self)
                else:
                    return

    def on_mainboard_message(self, watcher, revent):
        try:
            self.mainboard.handle_recv()
        except IOError:
            logger.error("Mainboard connection broken")
            self.stack.exit_task(self)
            self.send_udp0()
        except Exception:
            logger.exception("Unhandle Error")

    def on_headboard_message(self, watcher, revent):
        try:
            self.toolhead.handle_recv()
            check_toolhead_errno(self.toolhead, self.th_error_flag)
            self.fire()

        except IOError:
            logger.error("Headboard connection broken")
            self.stack.exit_task(self)

        except (HeadResetError, HeadOfflineError, HeadTypeError):
            self._ready &= ~2

        except HeadError as e:
            logger.info("Head Error: %s", e)

        except Exception:
            logger.exception("Unhandle Error")

    def on_mainboard_result(self, controller, message):
        # Note: message will be...
        #   "DATA HOME 12.3 -23.2 122.3"
        if message.startswith("DATA HOME"):
            position = [float(val) for val in message[10:].split(" ")]
            if float("nan") in position:
                self.handler.send(packb((CMD_G028, 1, None)))
            else:
                self.handler.send(packb((CMD_G028, 0, position)))
                self.known_position = [0, 0, 240]

        #   "DATA READ X:0.124 Y:0.234 Z:0.534 F0:1 F1:0 MB:0"
        if message.startswith("DATA READ "):
            output = {}
            for key, val in ((p.split(":") for p in message[10:].split(" "))):
                if key in ("X", "Y", "Z"):
                    output[key] = float(val)
                elif key in ("F0", "F1"):
                    output[key] = (val == "1")
                elif key == "MB":
                    output[key] = (val == "1")
            self.handler.send(packb((CMD_VALU, output)))
        #   "DATA ZPROBE -0.5"
        if message.startswith("DATA ZPROBE "):
            self.handler.send(packb((CMD_G030, float(message[12:]))))

    def send_udp0(self):
        if self.udp_sock:
            try:
                buf = packb((0, "", self.cmd_index, self.buflen))
                self.udp_sock.send(buf)
            except socket.error:
                pass

    def send_udp1(self, toolhead):
        if self.udp_sock:
            try:
                if self.head_resp_stack is not None:
                    buf = packb((2, "", 0, len(self.head_resp_stack)))
                    self.udp_sock.send(buf)

                if toolhead.ready:
                    buf = packb((1, "", 0, toolhead.error_code,
                                toolhead.status))
                    self.udp_sock.send(buf)

                # elif toolhead.ready_flag > 0:
                #     buf = packb((1, "", 0, -1, {}))
                #     self.udp_sock.send(buf)

                else:
                    buf = packb((1, "", 0, -2, {}))
                    self.udp_sock.send(buf)

            except socket.error:
                pass

    def send_udps(self, signal):
        if self.udp_sock:
            try:
                self.udp_sock.send(packb((signal, )))
            except socket.error:
                pass

    def on_timer(self, watcher, revent):
        self.meta.update_device_status(self.st_id, 0, "N/A",
                                       self.handler.address)

        self.send_udp0()
        if not self._ready & 2:
            self.send_udp1(self.toolhead)

        try:
            self.mainboard.patrol()
        except RuntimeError as e:
            logger.info("%s", e)

        except Exception:
            logger.exception("Mainboard dead")
            self.handler.send_text(packb((0xff, -1, 0xff, SUBSYSTEM_ERROR)))
            self.on_require_kill(self.handler)
            return

        try:
            self.toolhead.patrol()
        except (HeadOfflineError, HeadResetError) as e:
            logger.debug("Head Offline/Reset: %s", e)

        except RuntimeError as e:
            logger.info("%s", e)

        except socket.error:
            logger.warn("Socket IO Error")
            self.handler.close()

        except Exception:
            logger.exception("Toolhead dead")
            self.handler.send_text(packb((0xff, -1, 0xff, SUBSYSTEM_ERROR)))
            self.on_require_kill(self.handler)
            return

    def clean(self):
        self.mainboard.send_cmd("@HOME_BUTTON_TRIGGER\n")

        if self.toolhead:
            if self.toolhead.ready:
                self.toolhead.shutdown()
            self.toolhead = None

        if self.mainboard:
            self.mainboard.close()
            self.mainboard = None

        self.handler.binary_mode = False

    def append_cmd(self, target, cmd):
        self.cmd_queue.append((target, cmd))
        self.fire()

    def create_movement_command(self, F=None, X=None, Y=None, Z=None, E0=None, E1=None, E2=None):  # noqa
        target = self.known_position
        yield "G1"

        if F:
            yield "F%i" % F

        if X is not None or Y is not None or Z is not None:
            if self.known_position:
                if X is not None:
                    target[0] = X
                    yield "X%.5f" % X
                if Y is not None:
                    target[1] = Y
                    yield "Y%.5f" % Y
                if Z is not None:
                    target[2] = Z
                    yield "Z%.5f" % Z

                if (target[0] ** 2 + target[1] ** 2) > 28900:
                    raise InternalError(CMD_G001, MSG_OPERATION_ERROR)
                elif target[2] > 240 or target[2] < 0:
                    raise InternalError(CMD_G001, MSG_OPERATION_ERROR)

            else:
                raise InternalError(CMD_G001, MSG_OPERATION_ERROR)

        eflag = False
        for i, e in ((0, E0), (1, E1), (2, E2)):
            if e is not None:
                if eflag:
                    raise InternalError(CMD_G001, MSG_OPERATION_ERROR)
                else:
                    eflag = True
                    if self.main_e_axis != i:
                        yield "T%i" % i
                        self.main_e_axis = i
                    yield "E%.5f" % e

        self.known_position = target

    def on_move(self, handler, kw):
        try:
            cmd = "".join(self.create_movement_command(**kw))
            self.append_cmd(TARGET_MAINBOARD, cmd)
        except TypeError:
            raise InternalError(CMD_G001, MSG_BAD_PARAMS)

    def on_sleep(self, handler, secondes):
        try:
            cmd = "G4S%.4f" % secondes
            self.append_cmd(TARGET_MAINBOARD, cmd)
        except TypeError:
            raise InternalError(CMD_G004, MSG_BAD_PARAMS)

    def on_scan_lasr(self, handler, flags):
        try:
            cmd = "X1E%i" % flags
            self.append_cmd(TARGET_MAINBOARD, cmd)
        except TypeError:
            raise InternalError(CMD_SLSR, MSG_BAD_PARAMS)

    def on_home(self, handler):
        self.append_cmd(TARGET_MAINBOARD, "X6")
        self.known_position = None

    def on_lock_motors(self, handler):
        self.append_cmd(TARGET_MAINBOARD, "M17")

    def on_release_motors(self, handler):
        self.append_cmd(TARGET_MAINBOARD, "M84")
        self.known_position = None

    def on_z_probe(self, handler, x, y):
        try:
            if self.known_position and x ** 2 + y ** 2 <= 7225:
                cmd = "G30X%.5fY%.5f" % (x, y)
                self.append_cmd(TARGET_MAINBOARD, cmd)

            else:
                raise InternalError(CMD_G030, MSG_OPERATION_ERROR)
        except TypeError:
            raise InternalError(CMD_G030, MSG_BAD_PARAMS)

    # def on_adjust(self, handler, kw):
    #     pass

    def on_set_toolhead_temperature(self, handler, index, temperature):
        if index == 0 and temperature >= 0 and temperature <= 220:
            cmd = "H%i%.1f" % (index, temperature)
            self.append_cmd(TARGET_TOOLHEAD, cmd)
        else:
            raise InternalError(CMD_M104, MSG_OPERATION_ERROR)

    def on_set_toolhead_fan_speed(self, handler, index, speed):
        if index == 0 and speed >= 0 and speed <= 1:
            cmd = "F%i%.3f" % (index, speed)
            self.append_cmd(TARGET_TOOLHEAD, cmd)
        else:
            raise InternalError(CMD_M106, MSG_OPERATION_ERROR)

    def on_set_toolhead_pwm(self, handler, pwm):
        if pwm >= 0 and pwm <= 1:
            cmd = "X2O" % (pwm * 255)
            self.append_cmd(TARGET_MAINBOARD, cmd)
        else:
            raise InternalError(CMD_HLSR, MSG_OPERATION_ERROR)

    def on_query_value(self, handler, flags):
        self.append_cmd(TARGET_MAINBOARD, "X87F%i" % flags)

    def on_toolhead_profile(self, handler):
        buf = packb((CMD_THPF, self.toolhead.info()))
        self.handler.send(buf)

    def on_toolhead_raw_command(self, handler, cmd):
        self.append_cmd(TARGET_TOOLHEAD, cmd)

    def on_toolhead_raw_response(self, handler):
        buf = packb((CMD_THRR, self.head_resp_stack))
        self.head_resp_stack = []
        self.handler.send(buf)

    def on_require_sync(self, handler, ipaddr, port, salt):
        endpoint = (ipaddr, port)
        logger.debug("Create sync udp endpoint at %s", repr(endpoint))
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(endpoint)
            s.send(packb((0xff, )))
        except (TypeError, OSError):
            raise InternalError(CMD_SYNC, MSG_OPERATION_ERROR)

        try:
            if self.udp_sock:
                self.udp_sock.close()
        finally:
            self.udp_sock = s

    def on_require_head(self, handler, head_type):
        self.toolhead = HeadController(
            self._sock_th.fileno(),
            required_module=head_type,
            msg_callback=self.toolhead_message_callback)

        self.head_resp_stack = [] if head_type == "USER" else None

    def on_bootstrap_toolhead(self, handler):
        self.toolhead.bootstrap(self.on_toolhead_ready)

    def on_clean_toolhead_error(self, handler):
        self.toolhead.errcode = 0

    def on_require_quit(self, handler):
        if self.buflen:
            raise InternalError(CMD_QUIT, MSG_OPERATION_ERROR)

        self.stack.exit_task(self)
        self.handler.send(packb((CMD_QUIT, 0)))

    def on_require_kill(self, handler):
        try:
            self.send_udps(0xfe)
            self.stack.exit_task(self)
        finally:
            from fluxmonitor.hal.tools import reset_mb
            reset_mb()
            self.handler.send(packb((CMD_QUIT, 0)))


class InternalError(RuntimeError):
    pass


CMD_MATRIX = {
    CMD_G001: IControlTask.on_move,
    CMD_G004: IControlTask.on_sleep,
    CMD_SLSR: IControlTask.on_scan_lasr,
    CMD_G028: IControlTask.on_home,
    CMD_M017: IControlTask.on_lock_motors,
    CMD_M084: IControlTask.on_release_motors,
    CMD_G030: IControlTask.on_z_probe,
    # CMD_M666: IControlTask.on_adjust,
    CMD_M104: IControlTask.on_set_toolhead_temperature,
    CMD_M106: IControlTask.on_set_toolhead_fan_speed,
    CMD_HLSR: IControlTask.on_set_toolhead_pwm,
    CMD_VALU: IControlTask.on_query_value,
    CMD_THPF: IControlTask.on_toolhead_profile,
    CMD_THRC: IControlTask.on_toolhead_raw_command,
    CMD_THRR: IControlTask.on_toolhead_raw_response,
    CMD_SYNC: IControlTask.on_require_sync,
    CMD_REQH: IControlTask.on_require_head,
    CMD_BSTH: IControlTask.on_bootstrap_toolhead,
    CMD_CLHE: IControlTask.on_clean_toolhead_error,
    CMD_QUIT: IControlTask.on_require_quit,
    CMD_KILL: IControlTask.on_require_kill,
}
