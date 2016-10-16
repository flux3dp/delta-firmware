
from binascii import b2a_base64
from urlparse import urlparse
# from OpenSSL import crypto
from select import select
import msgpack
import logging
import socket
import json

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


class CloudService(ServiceBase):
    cloud_netloc = None
    metadata = None
    storage = None

    _notify_last_st = {"st_id": None}
    _notify_last_ts = 0
    _notify_aggressive = 0
    aws_client = None

    def __init__(self, options):
        super(CloudService, self).__init__(logger, options)
        self.storage = Storage("cloud")
        self.metadata = Metadata()
        self.uuidhex = security.get_uuid()

        if options.cloud.endswith("/"):
            self.cloud_netloc = options.cloud[:-1]
        else:
            self.cloud_netloc = options.cloud

    def on_start(self):
        logger.info("Cloud service started")
        self.timer = self.loop.timer(3., 3., self.on_timer)
        self.timer.start()

    def require_identify(self):
        logger.debug("Require identify")

        url = urlparse("%s/axon/require_identify" % self.cloud_netloc)
        conn = get_connection(url)

        pkey = security.get_private_key()
        publickey_base64 = b2a_base64(pkey.export_pubkey_der())
        serial = security.get_serial()
        model = get_model_id()
        identify_base64 = b2a_base64(security.get_identify())

        try:
            logger.debug("Require identify request sent")
            conn.post_request(url.path, {
                "serial": serial, "uuid": self.uuidhex, "model": model,
                "version": __version__, "publickey": publickey_base64,
                "signature": identify_base64
            })
            resp = conn.get_json_response()

            if resp.get("status") == "ok":
                return resp["token"].encode(), resp["subject"]
            elif resp.get("status") == "error":
                raise RuntimeWarning(*resp["error"])
            else:
                logger.error("require_identify response unknown response: %s",
                             resp)
                raise RuntimeWarning("RESPONSE_ERROR")
        except socket.gaierror as e:
            raise RuntimeError("REQUIRE_IDENTIFY", "DNS_ERROR", e)
        except socket.error as e:
            raise RuntimeError("REQUIRE_IDENTIFY", "CONNECTION_ERROR", e)
        except RuntimeWarning as e:
            raise RuntimeError("REQUIRE_IDENTIFY", *e.args)
        except Exception as e:
            logger.exception("Error in require identify")
            raise RuntimeError("REQUIRE_IDENTIFY", "UNKNOWN_ERROR", e)

    def get_identify(self, token, request_asn1):
        logger.debug("Get identify")

        url = urlparse("%s/axon/identify" % self.cloud_netloc)
        conn = get_connection(url)
        uuidhex = security.get_uuid()

        try:
            logger.debug("Get identify request sent")
            conn.post_request(url.path, {
                "uuid": uuidhex, "token": token, "x509_request": request_asn1,
                "metadata": {"version": __version__}
            })
            resp = conn.get_json_response()

            if resp.get("status") == "ok":
                return resp
            elif resp.get("status") == "error":
                raise RuntimeWarning(*resp["error"])
            else:
                logger.error("get identify response unknown response: %s",
                             resp)
                raise RuntimeWarning("RESPONSE_ERROR")
        except socket.gaierror as e:
            raise RuntimeError("GET_IDENTIFY", "DNS_ERROR", e)
        except socket.error as e:
            raise RuntimeError("GET_IDENTIFY", "CONNECTION_ERROR", e)
        except RuntimeWarning as e:
            raise RuntimeError("GET_IDENTIFY", *e.args)
        except Exception as e:
            logger.exception("Error in get identify")
            raise RuntimeError("GET_IDENTIFY", "UNKNOWN_ERROR", e)

    def generate_certificate_request(self, subject_list):
        from subprocess import Popen, PIPE

        fxkey = security.get_private_key()
        self.storage["key.pem"] = fxkey.export_pem()
        subject_str = "/" + "/".join(("=".join(i) for i in subject_list))

        proc = Popen(["openssl", "req", "-new", "-key",
                      self.storage.get_path("key.pem"), "-subj",
                      subject_str, "-keyform", "pem", "-nodes", "-sha256"],
                     stdin=PIPE, stderr=PIPE, stdout=PIPE)
        stdoutdata, stderrdata = proc.communicate(input="")

        while proc.poll() is None:
            pass
        if proc.returncode > 0:
            error = stdoutdata if stdoutdata else stderrdata
            if error:
                error = error.decode("utf8")
            else:
                error = "Process return %i" % proc.returncode
            raise SystemError(error)
        else:
            return stdoutdata
        # csr = crypto.X509Req()
        # subj = csr.get_subject()
        # for name, value in subject_list:
        #     if name == "CN":
        #         add_result = crypto._lib.X509_NAME_add_entry_by_NID(
        #             subj._name, 13, crypto._lib.MBSTRING_UTF8,
        #             value.encode('utf-8'), -1, -1, 0)
        #         if not add_result:
        #             crypto._raise_current_error()
        #     else:
        #         setattr(subj, name, value)

        # fxkey = security.get_private_key()
        # opensslkey = crypto.load_privatekey(crypto.FILETYPE_ASN1,
        #                                     fxkey.export_der())
        # self.storage["key.pem"] = fxkey.export_pem()
        # csr.set_pubkey(opensslkey)
        # csr.sign(opensslkey, "sha256")
        # return crypto.dump_certificate_request(crypto.FILETYPE_PEM, csr)

    def fetch_identify(self):
        logger.debug("Exec identify")

        token, subject_list = self.require_identify()
        logger.debug("require identify return token=%s, subject=%s",
                     token, subject_list)

        request_asn1 = self.generate_certificate_request(subject_list)
        doc = self.get_identify(token, request_asn1)
        logger.debug("get identify return %s", doc)

        self.storage["token"] = token
        self.storage["endpoint"] = doc["endpoint"]
        self.storage["client_id"] = doc["client_id"]
        self.storage["certificate_reqs.pem"] = doc["certificate_reqs"]
        self.storage["certificate.pem"] = doc["certificate"]

    def notify_up(self):
        c = self.aws_client.getMQTTConnection()
        payload = json.dumps({"state": {"reported": {"version": __version__}}})
        c.publish(self._notify_topic, payload, 1)

    def notify_update(self, new_st, now):
        new_st_id = new_st["st_id"]

        if self._notify_last_st["st_id"] == new_st_id:
            if self._notify_last_ts > self._notify_aggressive:
                # notify aggressive is invalid
                if now - self._notify_last_ts < 90:
                    # update every 90 seconds
                    return
            else:
                # notify aggressive is valid
                if new_st_id <= 0 and now - self._notify_last_ts < 90:
                    # update every 90 seconds if device is idle or occupy
                    return

        c = self.aws_client.getMQTTConnection()

        payload = json.dumps(
            {"state": {"reported": new_st}})
        c.publish(self._notify_topic, payload, 0)
        self._notify_last_st = new_st
        self._notify_last_ts = now

    def aws_on_request_callback(self, client, userdata, message):
        request = message.topic.split("/", 3)[-1]
        logger.debug("IoT request: %s", request)
        response_topic = "device/%s/response/%s" % (self.aws_token, request)

        try:
            payload = json.loads(message.payload)
        except ValueError:
            logger.error("IoT request payload error: %s", message.payload)
            client.publish(response_topic, message.payload)
            return

        if payload.get("uuid") != self.uuidhex:
            client.publish(response_topic, json.dumps({
                "status": "reject", "cmd_index": payload.get("cmd_index")}))
            return

        try:
            if request == "getchu":
                pass
            elif request == "camera":
                self.require_camera(payload["camera_id"], payload["endpoint"],
                                    payload["token"])
                client.publish(response_topic, json.dumps({
                    "status": "ok", "cmd_index": payload.get("cmd_index")}))
        except Exception:
            logger.exception("Handle aws request error")
            client.publish(response_topic, json.dumps({
                "status": "error", "cmd_index": payload.get("cmd_index")}))

    def begin_session(self):
        if not self.storage["certificate.pem"]:
            try:
                self.fetch_identify()
            except RuntimeError as e:
                logger.error(e)
                return
        self.setup_session()

    def setup_session(self):
        from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient
        ipaddr, port = self.storage["endpoint"].split(":")

        client = AWSIoTMQTTShadowClient(self.storage["client_id"])
        client.configureEndpoint(ipaddr, int(port))
        client.configureCredentials(
            self.storage.get_path("certificate_reqs.pem"),
            self.storage.get_path("key.pem"),
            self.storage.get_path("certificate.pem"))
        client.configureConnectDisconnectTimeout(10)
        client.configureMQTTOperationTimeout(5)
        client.connect()

        conn = client.getMQTTConnection()
        conn.subscribe("device/%s/request/camera" % self.storage["token"], 1,
                       self.aws_on_request_callback)

        self.aws_client = client
        self.aws_token = self.storage["token"]
        self._notify_topic = "$aws/things/%s/shadow/update" % (
            self.storage["client_id"])
        self.notify_up()
        self.timer.stop()
        self.timer.set(2.2, 2.2)
        self.timer.reset()
        self.timer.start()

    def teardown_session(self):
        if self.aws_client:
            try:
                self.aws_client.disconnect()
            except Exception:
                logger.exception("Error while disconnect from aws")
            self.aws_client = None
        self.timer.stop()
        self.timer.set(5.0, 5.0)
        self.timer.reset()
        self.timer.start()

    def on_timer(self, watcher, revent):
        try:
            if self.aws_client:
                self.notify_update(self.metadata.format_device_status, time())
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
        rl = select((s, ), (), (), 0.25)[0]
        if rl:
            logger.debug("Require camera return %s",
                         msgpack.unpackb(s.recv(4096)))
        s.close()

    def require_control(self, endpoint, token):
        pass