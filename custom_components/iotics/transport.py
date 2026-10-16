"""TLS MQTT transport, restricted to devices returned by the account API."""
import ssl
import threading
import uuid
import paho.mqtt.client as mqtt
from .protocol import websocket_path


class Transport:
    def __init__(self, profile, loop, on_connection, on_message):
        self.profile, self.loop = profile, loop
        self.connection_callback, self.message_callback = on_connection, on_message
        self._tokens = frozenset()
        self._lock = threading.Lock()
        self._stopped = False
        self._subscriptions = {}
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="io-ha-" + uuid.uuid4().hex[:20],
                                  protocol=mqtt.MQTTv311, transport="websockets")
        self.client.tls_set_context(ssl.create_default_context())
        self.client.reconnect_delay_set(2, 60)
        self.client.on_pre_connect = self._pre_connect
        self.client.on_connect = self._connect
        self.client.on_connect_fail = lambda *_: self._connection(False)
        self.client.on_disconnect = lambda *_: self._connection(False)
        self.client.on_message = self._message
        self.client.on_subscribe = self._subscribed

    def _connection(self, connected):
        if not self._stopped:
            self.loop.call_soon_threadsafe(self.connection_callback, connected)

    def _pre_connect(self, client, userdata):
        client.ws_set_options(path=websocket_path(self.profile))

    def _subscribe(self, token):
        # Subscribe only inside authenticated account device scopes.
        rc, mid = self.client.subscribe(f"io/{token}/#", qos=0)
        if rc == mqtt.MQTT_ERR_SUCCESS:
            self._subscriptions[mid] = token

    def _connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self._connection(False)
            return
        with self._lock:
            self._subscriptions.clear()
            for token in self._tokens:
                self._subscribe(token)
        self._connection(True)

    def _subscribed(self, client, userdata, mid, reason_codes, properties):
        with self._lock:
            token = self._subscriptions.pop(mid, None)
            if token in self._tokens and not any(code.is_failure for code in reason_codes):
                client.publish(f"io/{token}/gethwstatus", "1", qos=0, retain=False)

    def _message(self, client, userdata, message):
        parts = message.topic.split("/")
        with self._lock:
            owned = len(parts) >= 3 and parts[0] == "io" and parts[1] in self._tokens
        if owned and len(message.payload) <= 4096 and not self._stopped:
            self.loop.call_soon_threadsafe(self.message_callback, message.topic, bytes(message.payload), message.retain)

    def set_tokens(self, tokens):
        with self._lock:
            previous, self._tokens = self._tokens, frozenset(tokens)
            if self.client.is_connected():
                for token in previous - self._tokens:
                    self.client.unsubscribe(f"io/{token}/#")
                for token in self._tokens - previous:
                    self._subscribe(token)

    def start(self):
        self.client.connect_async(self.profile.host, 443, keepalive=30)
        self.client.loop_start()

    def stop(self):
        self._stopped = True
        self.client.disconnect()
        self.client.loop_stop()

    def query(self):
        with self._lock:
            if self.client.is_connected():
                for token in self._tokens:
                    self.client.publish(f"io/{token}/gethwstatus", "1", qos=0, retain=False)

    def publish(self, topic, payload):
        with self._lock:
            if topic.split("/")[1] not in self._tokens or not self.client.is_connected():
                raise ConnectionError("Iotics connection is unavailable")
            # QoS 0 prevents offline queued controls from replaying after reconnect.
            result = self.client.publish(topic, payload, qos=0, retain=False)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError("Unable to send Iotics command")
