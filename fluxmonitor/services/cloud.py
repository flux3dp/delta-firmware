
from binascii import b2a_base64, a2b_base64, a2b_hex
from urlparse import urlparse
import msgpack
import logging
import socket

from fluxmonitor.interfaces.cloud import CloudUdpSyncHander
from fluxmonitor.misc.httpclient import get_connection
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.storage import Metadata, Storage
from fluxmonitor.config import CAMERA_ENDPOINT
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
    def __init__(self, sessionkey_hex, expire_after, publickey, privatekey):
        self.sessionkey = a2b_hex(sessionkey_hex)
        self.expire_at = time() + expire_after - 60.0
        self.publickey = publickey
        self.privatekey = privatekey

    def fileno(self):
        return self.sock.fileno()

    @property
    def is_expired(self):
        return (self.expire_at - time() < 30.0)

    def pack(self, message):
        return self.sessionkey + self.publickey.encrypt(message)

    def unpack(self, buf):
        signdoc = self.privatekey.decrypt(buf)
        if signdoc:
            size = self.publickey.size()
            signature, document = signdoc[:size], signdoc[size:]
            if self.publickey.verify(document, signature):
                return document
            else:
                logger.error("Bad session signature")
        else:
            logger.error("Bad session encrypt")


class CloudService(ServiceBase):
    cloud_netloc = None
    metadata = None
    storage = None
    udp_handler = None

    def __init__(self, options):
        super(CloudService, self).__init__(logger, options)
        self.storage = Storage("cloud")
        self.metadata = Metadata()

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

        pkey = security.get_private_key()
        publickey_base64 = b2a_base64(pkey.export_pubkey_der())
        serial = security.get_serial()
        uuidhex = security.get_uuid()
        model = get_model_id()
        identify_base64 = b2a_base64(security.get_identify())

        try:
            # === Require identify ===
            logger.debug("Require identify request sent")
            conn.post_request(url.path, {
                "serial": serial, "uuid": uuidhex, "model": model,
                "version": __version__, "publickey": publickey_base64,
                "signature": identify_base64
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
            session = Session(doc["session"], doc["expire_after"],
                              security.RSAObject(doc["key"]),
                              security.get_private_key)
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
        ipaddr = endpoint[0] \
            if isinstance(endpoint[0], str) else endpoint[0].encode()

        self.udp_handler = CloudUdpSyncHander(self, (ipaddr, endpoint[1]),
                                              timestemp, session)

    def teardown_session(self):
        if self.udp_handler:
            self.udp_handler.close()
            self.udp_handler = None

    def push_update(self):
        flag = 0  # push device status flag
        payload = msgpack.packb((flag, self.metadata.device_status))

        try:
            self.udp_handler.send(payload)
            logger.warning("PUSH..")
        except socket.gaierror:
            raise
        except OSError:
            logger.exception("Push message failed, teardown session")
            self.teardown_session()

    def on_timer(self, watcher, revent):
        try:
            if self.udp_handler and not self.udp_handler.session.is_expired:
                self.push_update()
            else:
                self.begin_session()
        except RuntimeError as e:
            logger.error("%s", e)
        except Exception:
            logger.exception("Unhandle error")

    def on_shutdown(self):
        pass

    def require_camera(self, camera_id, endpoint, token):
        payload = msgpack.packb((0x80, camera_id, endpoint, token))
        s = socket.socket(socket.AF_UNIX)
        s.connect(CAMERA_ENDPOINT)
        s.send(payload)
        s.close()

    def require_control(self, endpoint, token):
        pass
