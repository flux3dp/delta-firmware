
from weakref import proxy
import logging

from fluxmonitor.controller.tasks.command_task import CommandTask
from .tcp import TcpInterface, TcpConnectionHandler

__all__ = ["RobotTcpInterface", "RobotTcpConnectionHandler"]
logger = logging.getLogger(__name__)


class RobotTcpInterface(TcpInterface):
    def __init__(self, kernel, endpoint=("", 23811)):
        super(RobotTcpInterface, self).__init__(kernel, endpoint)

    def create_handler(self, sock, endpoint):
        return RobotTcpConnectionHandler(self.kernel, sock, endpoint,
                                         self.privatekey)


class RobotTcpConnectionHandler(TcpConnectionHandler):
    def on_ready(self):
        self.delegate = ServiceStack(self.kernel)


class ServiceStack(object):
    def __init__(self, kernel):
        self.kernel = kernel
        self.loop = kernel.loop
        self.task_callstack = []
        self.this_task = None

        cmd_task = CommandTask(proxy(self))
        self.this_task = cmd_task

    def __del__(self):
        logger.debug("ServiceStack GC")

    def on_text(self, message, handler):
        self.this_task.on_text(message, handler)

    def on_binary(self, buf, handler):
        self.this_task.on_binary(buf, handler)

    def on_close(self, handler):
        self.terminate()

    def enter_task(self, invoke_task, return_callback):
        logger.debug("Enter %s" % invoke_task.__class__.__name__)
        self.task_callstack.append((self.this_task, return_callback))
        self.this_task = invoke_task

    def exit_task(self, task, *return_args):
        if self.this_task != task:
            raise Exception("Task not match")

        try:
            task.on_exit()
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)

        try:
            current_task, callback = self.task_callstack.pop()
            callback(*return_args)
            logger.debug("Exit %s" % self.this_task.__class__.__name__)
        except Exception:
            logger.exception("Exit %s" % self.this_task.__class__.__name__)
        finally:
            self.this_task = current_task

    def terminate(self):
        while self.task_callstack:
            try:
                self.exit_task(self.this_task)
            except Exception:
                logger.exception("Unhandle error")
