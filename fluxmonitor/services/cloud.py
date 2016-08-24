
from binascii import b2a_base64, a2b_base64, a2b_hex
from urlparse import urlparse
import msgpack
import logging
import struct
import socket
import pyev

from fluxmonitor.misc.httpclient import get_connection
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.storage import Metadata, Storage
from fluxmonitor import security, __version__

from .base import ServiceBase

logger = logging.getLogger(__name__)
# TOTAL_PRINT = "tp"
# SUCCESSED_PRINT = "sp"
# DURATION_OF_PRINT = "dp"
# TOTAL_LASER_GRAVE = "tl"
# SUCCESSED_LASER_GRAVE = "sl"
# DURATION_OF_LASER_GRAVE = "dl"
# TOTAL_NONHEAD_USE = "tn"
# SUCCESSED_NONHEAD_USE = "sn"
# DURATION_OF_NONHEAD_USE = "dn"


class Session(object):
    def __init__(self, sessionkey_hex, publickey_pem,
                 expire_after):
        self.sessionkey = a2b_hex(sessionkey_hex)
        self.rsakey = security.RSAObject(publickey_pem)
        self.expire_at = time() + expire_after - 60.0

    def fileno(self):
        return self.sock.fileno()

    @property
    def is_expired(self):
        return (self.expire_at - time() < 30.0)

    def pack(self, message):
        return self.sessionkey + self.rsakey.encrypt(message)


class CloudService(ServiceBase):
    cloud_netloc = None
    metadata = None
    storage = None
    session = None

    udp_sock = None
    udp_endpoint = None

    def __init__(self, options):
        super(CloudService, self).__init__(logger, options)
        self.storage = Storage("cloud")
        self.metadata = Metadata()
        self.privatekey = security.get_private_key()

        if options.cloud.endswith("/"):
            self.cloud_netloc = options.cloud[:-1]
        else:
            self.cloud_netloc = options.cloud

    def on_start(self):
        logger.info("Cloud service started")
        self.timer = self.loop.timer(5., 5., self.on_timer)
        self.timer.start()

    @property
    def require_identify_url(self):
        return urlparse("%s/axon/require_identify" % self.cloud_netloc)

    @property
    def identify_url(self):
        return urlparse("%s/axon/identify" % self.cloud_netloc)

    @property
    def session_url(self):
        return urlparse("%s/axon/begin_session" % self.cloud_netloc)

    def exec_identify(self):
        logger.debug("Exec identify")

        url = self.require_identify_url
        conn = get_connection(url)
        logger.debug("Cloud connected")

        pkey = self.privatekey

        publickey_base64 = b2a_base64(pkey.export_pubkey_der())
        serial = security.get_serial()
        uuidhex = security.get_uuid()
        model = get_model_id()
        identify = security.get_identify()

        try:
            # === Require identify ===
            logger.debug("Require identify request sent")
            conn.post_request(url.path, {
                "serial": serial, "uuid": uuidhex, "model": model,
                "version": __version__, "publickey": publickey_base64,
                "signature": identify
            })
            request_doc = conn.get_json_response()
            challange = a2b_base64(request_doc["challange"])
            signature = pkey.sign(challange)
        except socket.gaierror as e:
            raise RuntimeError("REQUIRE_IDENTIFY", "DNS_ERROR", e)
        except socket.error as e:
            raise RuntimeError("REQUIRE_IDENTIFY", "CONNECTION_ERROR", e)
        except RuntimeWarning as e:
            raise RuntimeError("REQUIRE_IDENTIFY", *e.args)
        except Exception as e:
            logger.exception("Error in require identify")
            raise RuntimeError("REQUIRE_IDENTIFY", "UNKNOWN_ERROR", e)

        try:
            # === Identify ===
            logger.debug("Identify request sent")
            url = self.identify_url
            conn.post_request(url.path, {
                "uuid": uuidhex, "challange": request_doc["challange"],
                "signature": b2a_base64(signature),
                "metadata": {"version": __version__}
            })
            identify_doc = conn.get_json_response()
            self.storage["token"] = identify_doc["token"]
            logger.debug("Identify suucessed")
        except socket.gaierror as e:
            raise RuntimeError("IDENTIFY", "DNS_ERROR", e)
        except socket.error as e:
            raise RuntimeError("IDENTIFY", "CONNECTION_ERROR", e)
        except RuntimeWarning as e:
            raise RuntimeError("IDENTIFY", *e.args)
        except Exception as e:
            logger.exception("Error in identify")
            raise RuntimeError("IDENTIFY", "UNKNOWN_ERROR", e)

    def begin_session(self):
        if not self.storage["token"]:
            self.exec_identify()

        uuidhex = security.get_uuid()

        url = self.session_url

        try:
            conn = get_connection(url)

            logger.debug("Begin session request")
            conn.post_request(url.path, {
                "uuid": uuidhex, "token": self.storage["token"],
                "v": __version__
            })

            doc = conn.get_json_response()
            session = Session(doc["session"], doc["key"], doc["expire_after"])
            self.setup_session(session, doc["endpoint"], doc["timestemp"])
            logger.debug("Session request successed, session=%(session)s, "
                         "expire_after=%(expire_after)i", doc)

        except socket.gaierror as e:
            raise RuntimeError("BEGIN_SESSION", "DNS_ERROR", e)
        except socket.error as e:
            raise RuntimeError("BEGIN_SESSION", "CONNECTION_ERROR", e)
        except RuntimeWarning as e:
            if e.args[0] == "BAD_TOKEN":
                del self.storage["token"]
            raise RuntimeError("BEGIN_SESSION", *e.args)
        except Exception as e:
            logger.exception("Error in begin session")
            raise RuntimeError("BEGIN_SESSION", "UNKNOWN_ERROR", e)

    def setup_session(self, session, endpoint, timestemp):
        self.session = session
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        ipaddr = endpoint[0] \
            if isinstance(endpoint[0], str) else endpoint[0].encode()
        self.udp_endpoint = (ipaddr, endpoint[1])
        self.udp_watcher = self.loop.io(self.udp_sock, pyev.EV_READ,
                                        self.on_udp_request)
        self.udp_watcher.start()
        self.udp_timestemp = timestemp

    def teardown_session(self):
        if self.udp_watcher:
            self.udp_watcher.stop()
        self.udp_watcher = None
        if self.udp_sock:
            self.udp_sock.close()
        self.udp_sock = None
        self.session = None
        self.udp_endpoint = None

    def push_update(self):
        flag = 0
        message = msgpack.packb((flag, self.metadata.device_status))

        try:
            payload = self.session.pack(message)
            self.udp_sock.sendto(payload, self.udp_endpoint)
        except socket.gaierror:
            raise
        except OSError:
            logger.exception("Push message failed, teardown session")
            self.teardown_session()

    def on_udp_request(self, watcher, revent):
        try:
            buf = self.udp_sock.recv(1024)
            if buf == "\x00":
                return
            elif buf.startswith("\x01"):
                data = self.privatekey.decrypt(buf[1:])
                timestemp = struct.unpack("<d", data[:8])
                if timestemp > self.udp_timestemp:
                    self.udp_timestemp = timestemp
                    request = msgpack.unpackb(data[8:])
                    self.handle_request(request)
                else:
                    logger.error("UDP Timestemp error. Current %f buf got %f",
                                 self.udp_timestemp, timestemp)
            else:
                logger.error("Unknown udp payload prefix: %s", buf[0])
        except Exception:
            logger.exception("UDP payload error.")

    def handle_request(self, request):
        pass

    def on_timer(self, watcher, revent):
        try:
            if self.session and self.session.is_expired is False:
                self.push_update()
            else:
                self.begin_session()
        except RuntimeError as e:
            logger.error("%s", e)
        except Exception:
            logger.exception("Unhandle error")

    def on_shutdown(self):
        pass
