
from binascii import b2a_hex as to_hex
import logging
import socket

from fluxmonitor.misc.async_signal import AsyncIO
from fluxmonitor import security

PRIVATE_KEY = security.get_private_key()


class LocalControl(object):
    def __init__(self, server, callback=None, logger=None, port=23811):
        self.server = server
        self.callback = callback if callback else server.on_cmd
        self.logger = logger.getChild("lc") if logger \
            else logging.getLogger(__name__)

        self.serve_sock = s = socket.socket()
        s.bind(("", port))
        s.listen(1)
        self.server.add_read_event(AsyncIO(s, self.on_accept))

        self.logger.info("Listen on %s:%i" % ("", port))

    def on_accept(self, sender):
        request, client = sender.obj.accept()
        io = AsyncIO(request)
        io.client = client

        self.on_connected(io)

    def on_connected(self, sender):
        """
        Send handshake payload:
            "FLUX0001" (8 bytes)
            signed random bytes (private keysize)
            random bytes (128 bytes)
        """
        sender.randbytes = security.randbytes()
        buf = b"FLUX0001" + \
              PRIVATE_KEY.sign(sender.randbytes) + \
              sender.randbytes

        sender.obj.send(buf)
        sender.set_on_read(self.on_handshake)
        self.server.add_read_event(sender)

    def on_handshake(self, sender):
        """
        Recive handshake payload:
            access id (20 bytes)
            signature (remote private key size)

        Send final handshake payload:
            message (16 bytes)
        """
        self.server.remove_read_event(sender)
        request = sender.obj

        buf = request.recv(20)
        access_id = to_hex(buf)

        if access_id == "0" * 40:
            raise RuntimeError("Not implement")
        else:
            keyobj = security.get_keyobj(access_id=access_id)
            signature = request.recv(keyobj.size())

            if keyobj and keyobj.verify(sender.randbytes, signature):
                sender.obj.send(b"OK" + b"\x00" * 14)
                self.server.add_read_event(AsyncIO(request, self.on_message))
                self.logger.info(
                    "Client %s connected (access_id=%s)" % (sender.client,
                                                            access_id))
            else:
                sender.obj.send(b"AUTH_FAILED" + b"\x00" * 5)
                sender.close()

    def on_message(self, sender):
        buf = sender.obj.recv(4096)

        if buf:
            self.callback(buf, sender.obj)
        else:
            self.server.remove_read_event(sender)