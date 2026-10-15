"""Account-scoped protocol and signing; no Home Assistant dependencies."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
from urllib.parse import quote


class ProfileError(Exception):
    """Private app profile missing or invalid."""


@dataclass(repr=False, frozen=True)
class Profile:
    appid: str
    login_bearer: str
    access_key: str
    secret_key: str
    region: str
    host: str
    base_url: str = "https://apiv2.iotics.io/v2"

    @classmethod
    def load(cls, path):
        try:
            data = json.loads(Path(path).read_text())
            result = cls(*(data[k] for k in (
                "IOTICS_API_KEY", "login_bearer", "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "AWS_IOT_ENDPOINT")))
            if not all(isinstance(x, str) and x and not any(c.isspace() for c in x)
                       for x in vars(result).values()):
                raise ValueError
            if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", result.region):
                raise ValueError
            if not re.fullmatch(r"[a-zA-Z0-9-]+\.iot\." + re.escape(result.region)
                                + r"\.amazonaws\.com", result.host):
                raise ValueError
            if data.get("api_base_url", result.base_url) != result.base_url:
                raise ValueError
            return result
        except (OSError, ValueError, KeyError, TypeError):
            raise ProfileError("Missing or invalid private app profile") from None


def websocket_path(profile, now=None):
    """Sign an AWS IoT websocket upgrade, refreshed for every connection."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    scope = f"{date}/{profile.region}/iotdevicegateway/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{profile.access_key}/{scope}",
        "X-Amz-Date": stamp,
        "X-Amz-Expires": "900",
        "X-Amz-SignedHeaders": "host",
    }
    query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
                     for k, v in sorted(params.items()))
    canonical = f"GET\n/mqtt\n{query}\nhost:{profile.host}\n\nhost\n{hashlib.sha256(b'').hexdigest()}"
    to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    key = ("AWS4" + profile.secret_key).encode()
    for part in (date, profile.region, "iotdevicegateway", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"/mqtt?{query}&X-Amz-Signature={signature}"


def integer(value, minimum=0, maximum=1):
    if isinstance(value, bool):
        return int(value) if minimum <= int(value) <= maximum else None
    if isinstance(value, (int, str)) and re.fullmatch(r"\d+", str(value)):
        number = int(value)
        if minimum <= number <= maximum:
            return number
    return None


@dataclass
class Device:
    token: str
    name: str
    model: str
    channels: dict

    @property
    def controls(self):
        # Other families have unverified ranges/directions; never guess commands.
        return {k: v for k, v in self.channels.items()
                if re.fullmatch(r"b[1-9]\d*|f[12]", k)}

    def supports_speed(self, channel):
        return (channel in ("f1", "f2") and "l" + channel[1:] in self.channels
                and self.channels[channel].get("is_bldc") in (None, False, 0, "0"))


def parse_devices(records):
    if not isinstance(records, list):
        raise ValueError("Invalid device list")
    result = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid device record")
        token = record.get("hardwaretoken")
        channels = record.get("switches", {})
        if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", token):
            raise ValueError("Invalid hardware token")
        if not isinstance(channels, dict):
            raise ValueError("Invalid channels")
        safe = {k: dict(v) for k, v in channels.items()
                if isinstance(k, str) and re.fullmatch(r"[a-z]+[1-9]\d*", k)
                and isinstance(v, dict)}
        result[token] = Device(token, str(record.get("hardwarename") or "Iotics panel"),
                               str(record.get("hardwaretype") or "Panel"), safe)
    return result


def command(devices, token, channel, value):
    device = devices.get(token)
    if device is None:
        raise ValueError("Device is not in this account")
    valid = integer(value)
    if channel in device.controls:
        if valid is None:
            raise ValueError("Invalid power value")
    elif channel in ("l1", "l2") and device.supports_speed("f" + channel[1:]):
        valid = integer(value, 1, 4)
        if valid is None:
            raise ValueError("Invalid fan level")
    else:
        raise ValueError("Unsupported channel")
    return f"io/{token}/{channel}/sw", str(valid)
