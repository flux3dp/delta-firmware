
from AWSIoTPythonSDK.core.protocol.mqttCore import (
    publishQueueDisabledException)
from binascii import a2b_base64, b2a_base64
from urlparse import urlparse
# from OpenSSL import crypto
from select import select
from ssl import SSLError
import msgpack
import logging
import socket
import json
import os

from fluxmonitor.misc.httpclient import get_connection
from fluxmonitor.misc.systime import systime as time
from fluxmonitor.halprofile import get_model_id
from fluxmonitor.storage import Storage, metadata
from fluxmonitor.config import CAMERA_ENDPOINT, ROBOT_ENDPOINT
from fluxmonitor import security, __version__

from .base import ServiceBase

ERROR_COUNTER_MATCH = [int(2 ** i ** 0.70) - 1 for i in range(32)]
logger = logging.getLogger(__name__)


class CloudService(ServiceBase):
    config_ts = -1
    error_counter = 0
    config_enable = None
    cloud_netloc = None
    storage = None

    _notify_up_required = False
    _notify_last_st = {"st_id": None}
    _notify_last_ts = 0
    _notify_aggressive = 0
    _notify_retry_counter = 0
    aws_client = None
    postback_url = None

    def __init__(self, options):
        super(CloudService, self).__init__(logger, options)

        mqttlogger = logging.getLogger(
            "AWSIoTPythonSDK.core.protocol.mqttCore")
        if logger.getEffectiveLevel() < logging.INFO:
            mqttlogger.setLevel(logging.DEBUG)
        else:
            mqttlogger.setLevel(logging.WARNING)

        self.storage = Storage("cloud")
        self.uuidhex = security.get_uuid()

        if options.cloud.endswith("/"):
            self.cloud_netloc = options.cloud[:-1]
        else:
            self.cloud_netloc = options.cloud

    def on_start(self):
        logger.info("Cloud service started")
        if security.get_serial() == "XXXXXXXXXX":
            logger.error("Serial invalid, cloud deamon will be silenced.")
        else:
            self.timer = self.loop.timer(3., 3., self.on_timer)
            self.timer.start()

    def require_identify(self):
        logger.debug("Require identify")

        url = urlparse("%s/axon/require_identify" % self.cloud_netloc)

        pkey = security.get_private_key()
        publickey_base64 = b2a_base64(pkey.export_pubkey_der())
        serial = security.get_serial()
        model = get_model_id()
        identify_base64 = b2a_base64(security.get_identify())

        try:
            conn = get_connection(url)
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
        uuidhex = security.get_uuid()

        try:
            conn = get_connection(url)
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
        logger.info("Fetch identify")

        token, subject_list = self.require_identify()
        logger.info("Require identify return token=%s, subject=%s",
                    token, subject_list)

        request_asn1 = self.generate_certificate_request(subject_list)
        doc = self.get_identify(token, request_asn1)
        logger.info("Get identify return %s", doc["status"])

        self.storage["token"] = token
        self.storage["endpoint"] = doc["endpoint"]
        self.storage["client_id"] = doc["client_id"]
        self.storage["certificate_reqs.pem"] = doc["certificate_reqs"]
        self.storage["certificate.pem"] = doc["certificate"]

    def notify_up(self, c):
        payload = json.dumps({"state": {"reported": {
            "version": __version__, "token": self.storage["token"],
            "nickname": metadata.nickname}}})
        c.publish(self._notify_topic, payload, 1)

    def postback_status(self, st_id):
        url = Storage("general", "meta")["player_postback_url"]
        if url:
            try:
                if '"' in url or '\\' in url:
                    logger.error("Bad url: %r", url)
                else:
                    url = url % {"st_id": st_id}
                    os.system("curl -s -o /dev/null \"%s\"" % url)
            except Exception:
                logger.exception("Error while post back status, url: %s", url)

    def notify_update(self, new_st, now):
        if metadata.verify_mversion() is False:
            self._notify_up_required = True

        new_st_id = new_st["st_id"]

        if self._notify_last_st["st_id"] == new_st_id:
            if self._notify_last_ts > self._notify_aggressive:
                # notify aggressive is invalid
                if now - self._notify_last_ts < 1200:
                    # update every 1200 seconds
                    return
            else:
                # notify aggressive is valid
                if new_st_id <= 0 and now - self._notify_last_ts < 1200:
                    # update every 1200 seconds if device is idle or occupy
                    return
        elif new_st_id in (48, 64, 128):  # paused, completed, aborted
            self.postback_status(new_st_id)

        c = self.aws_client.getMQTTConnection()

        payload = json.dumps(
            {"state": {"reported": new_st}})

        if self._notify_up_required:
            self.notify_up(c)
            self._notify_up_required = False
        c.publish(self._notify_topic, payload, 0)
        self._notify_last_st = new_st
        self._notify_last_ts = now

    def aws_on_request_callback(self, client, userdata, message):
        # incommint topic format: "device/{token}/request/{action}"
        # response topic format: "device/{token}/response/{action}"

        action = message.topic.split("/", 3)[-1]
        logger.debug("IoT request: %s", action)
        response_topic = "device/%s/response/%s" % (self.aws_token, action)

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

        cmd_index = payload.get("cmd_index")

        try:
            if action == "getchu":
                try:
                    current_hash = metadata.cloud_hash
                    access_id, signature = payload.get("validate_message")
                    client_key = security.get_keyobj(access_id=access_id)
                    if client_key.verify(current_hash, a2b_base64(signature)):
                        client.publish(response_topic, json.dumps({
                            "status": "ok", "cmd_index": cmd_index}))
                    else:
                        client.publish(response_topic, json.dumps({
                            "status": "reject", "cmd_index": cmd_index}))
                finally:
                    metadata.cloud_hash = os.urandom(32)
            elif action == "monitor":
                self._notify_aggressive = time() + 180
                self._notify_last_st["st_id"] = None
                client.publish(response_topic, json.dumps({
                    "status": "ok", "cmd_index": cmd_index}))
            elif action == "camera":
                self.require_camera(payload["camera_id"], payload["endpoint"],
                                    payload["token"])
                client.publish(response_topic, json.dumps({
                    "status": "ok", "cmd_index": cmd_index}))
            elif action == "control":
                self.require_control(payload["endpoint"], payload["token"])
                client.publish(response_topic, json.dumps({
                    "status": "ok", "cmd_index": cmd_index}))
            else:
                client.publish(response_topic, json.dumps({
                    "status": "error", "cmd_index": cmd_index}))
        except Exception:
            logger.exception("Handle aws request error")
            client.publish(response_topic, json.dumps({
                "status": "error", "cmd_index": cmd_index}))

    def begin_session(self):
        logger.info("Begin Session")
        if not self.storage["certificate.pem"]:
            metadata.cloud_status = (False, ("INIT", ))
            self.fetch_identify()

        self.setup_session()
        metadata.cloud_status = (True, ())

    def setup_session(self):
        logger.info("Setup session")
        from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient
        from AWSIoTPythonSDK.core.protocol.mqttCore import (
            connectTimeoutException)

        client_id, token = self.storage["client_id"], self.storage["token"]
        if not client_id or not token:
            raise SystemError("client_id or token error")

        try:
            ipaddr, port = self.storage["endpoint"].split(":")
        except (AttributeError, ValueError):
            raise SystemError("endpoint error")

        cafile = self.storage.get_path("certificate_reqs.pem")
        cert = self.storage.get_path("certificate.pem")
        key = self.storage.get_path("key.pem")

        if False in map(lambda p: os.path.exists(p), (cafile, cert, key)):
            raise SystemError("cafile or cert or key not exist")

        client = AWSIoTMQTTShadowClient(client_id)
        client.configureEndpoint(ipaddr, int(port))
        client.configureCredentials(cafile, key, cert)
        client.configureConnectDisconnectTimeout(10)
        client.configureMQTTOperationTimeout(5)

        try:
            client.connect()
        except SSLError as e:
            raise RuntimeError("SESSION", "TLS_ERROR", "%s" % e.reason)
        except (connectTimeoutException, socket.gaierror, socket.error):
            raise RuntimeError("SESSION", "CONNECTION_ERROR")

        conn = client.getMQTTConnection()
        conn.subscribe("device/%s/request/+" % self.storage["token"], 1,
                       self.aws_on_request_callback)

        self.aws_client = client
        self.aws_token = token
        self._notify_topic = "$aws/things/%s/shadow/update" % (
            self.storage["client_id"])
        self.notify_up(conn)
        metadata.cloud_hash = os.urandom(32)
        logger.info("Session ready")

    def teardown_session(self):
        if self.aws_client:
            aws_client = self.aws_client
            self.aws_client = None

            conn = aws_client.getMQTTConnection()
            try:
                if conn._mqttCore._pahoClient._thread.isAlive():
                    aws_client.disconnect()
                else:
                    logger.error("MQTT thread closed, remove directly")

            except Exception:
                logger.exception("AWS panic while disconnect from aws, "
                                 "make a ugly bugfix")
                try:
                    conn._mqttCore._pahoClient._thread_terminate = True
                    if conn._mqttCore._pahoClient._sock:
                        conn._mqttCore._pahoClient._sock.close()
                    return
                except Exception:
                    logger.exception("AWS panic ugly bugfix failed")

    def on_timer(self, watcher, revent):
        try:
            if self.config_ts != metadata.mversion:
                self.error_counter = 0

                if metadata.enable_cloud == "R":
                    logger.warning("Refetch required")
                    if self.aws_client:
                        self.teardown_session()
                    metadata.enable_cloud = "A"
                    metadata.cloud_status = (False, ("INIT", ))
                    self.fetch_identify()

                self.config_ts = metadata.mversion
                self.config_enable = (metadata.enable_cloud == "A")
                if self.config_enable is False:
                    metadata.cloud_status = (False, ("DISABLE", ))

            if self.config_enable:
                if self.aws_client:
                    self.notify_update(metadata.format_device_status,
                                       time())
                else:
                    if self.error_counter in ERROR_COUNTER_MATCH:
                        self.begin_session()
                        self.error_counter = 0
                    elif self.error_counter > ERROR_COUNTER_MATCH[-1]:
                        self.error_counter = ERROR_COUNTER_MATCH[-2]
                    else:
                        self.error_counter += 1

            else:
                if self.aws_client:
                    self.teardown_session()

            self._notify_retry_counter = 0
        except publishQueueDisabledException:
            metadata.cloud_status = (False, ("SESSION",
                                             "CONNECTION_ERROR"))
            self._notify_retry_counter += 1
            logger.error("publishQueueDisabledException raise in notify")
            if self._notify_retry_counter > 10:
                self.teardown_session()
            self.error_counter += 1
        except RuntimeError as e:
            logger.error(e)
            metadata.cloud_status = (False, e.args)
            self.error_counter += 1
        except Exception:
            logger.exception("Unhandle error")
            metadata.cloud_status = (False, ("UNKNOWN_ERROR", ))
            self.error_counter += 1

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
        payload = msgpack.packb((0x80, endpoint, token))
        s = socket.socket(socket.AF_UNIX)
        s.connect(ROBOT_ENDPOINT)
        s.send(payload)
        rl = select((s, ), (), (), 0.25)[0]
        if rl:
            logger.debug("Require robot return %s",
                         msgpack.unpackb(s.recv(4096)))
        s.close()
