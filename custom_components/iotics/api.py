"""The account API recovered from the supplied Android app."""
import asyncio
import aiohttp


class AuthError(Exception):
    """The account needs authentication."""


class ApiError(Exception):
    """Network or server protocol failure."""


class IoticsApi:
    def __init__(self, session, profile, email, password, device_id):
        self.session, self.profile = session, profile
        self.email, self.password, self.device_id = email.strip(), password, device_id
        self.token = None
        self.user_id = None
        self._lock = asyncio.Lock()

    def _body(self, action):
        return {"appid": self.profile.appid, "action": action, "emailid": self.email,
                "device_token": self.device_id, "source": "mobile", "os": "android"}

    async def _post(self, path, body, bearer):
        try:
            async with self.session.post(
                self.profile.base_url + path, json=body,
                headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise AuthError("Authentication rejected")
                if response.status != 200:
                    raise ApiError("Iotics service unavailable")
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise ApiError("Unable to read Iotics response") from None
        if not isinstance(data, dict):
            raise ApiError("Unexpected Iotics response")
        if data.get("status") != "success":
            # Do not log or expose raw server responses (may include credentials).
            message = str(data.get("response", "")).lower()
            if path == "/user/login" or any(x in message for x in ("jwt", "token expired", "unauthorized")):
                raise AuthError("Account authentication failed")
            raise ApiError("Iotics rejected the request")
        return data.get("response")

    async def login(self):
        body = {**self._body("login"), "password": self.password}
        data = await self._post("/user/login", body, self.profile.login_bearer)
        try:
            token, user_id = data["access_token"], data["user"]["user_id"]
            if not isinstance(token, str) or not token or user_id is None:
                raise ValueError
            self.token, self.user_id = token, str(user_id)
        except (KeyError, TypeError, ValueError):
            raise ApiError("Unexpected login response") from None
        return self.user_id

    async def devices(self):
        async with self._lock:
            if self.token is None:
                await self.login()
            for attempt in range(2):
                try:
                    data = await self._post("/device/list", {
                        **self._body("getdevices"), "user_id": self.user_id,
                    }, self.token)
                    if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
                        raise ApiError("Unexpected device response")
                    return data["devices"]
                except AuthError:
                    if attempt:
                        raise
                    await self.login()
