"""
Improved AIOSomeComfort client with automatic retry and re-authentication.

This is a modified version of mkmer/AIOSomecomfort that adds:
- Automatic re-authentication on 401/403 errors
- Exponential backoff retry on transient errors (500/502/503)
- Session health checking
- Better logging for debugging

Original: https://github.com/mkmer/AIOSomecomfort
License: GPL-3.0
"""

from __future__ import annotations
import asyncio
import datetime
import logging
import urllib.parse as urllib
import aiohttp
from yarl import URL

_LOG = logging.getLogger("somecomfort")

AUTH_COOKIE = ".ASPXAUTH_TRUEHOME"
DOMAIN = "mytotalconnectcomfort.com"
MIN_LOGIN_TIME = datetime.timedelta(minutes=10)
MAX_LOGIN_ATTEMPTS = 3
DEFAULT_RETRY_COUNT = 3
RETRY_BACKOFF_BASE = 2  # seconds


# ============== Exceptions ==============

class SomeComfortError(Exception):
    """SomeComfort general error class."""

class ConnectionTimeout(SomeComfortError):
    """SomeComfort Connection Timeout Error."""

class ConnectionError(SomeComfortError):
    """SomeComfort Connection Error."""

class AuthError(SomeComfortError):
    """SomeComfort Authentication Error."""

class APIError(SomeComfortError):
    """SomeComfort General API error."""

class APIRateLimited(SomeComfortError):
    """SomeComfort API Rate limited."""

class SessionTimedOut(SomeComfortError):
    """SomeComfort Session Timeout."""

class ServiceUnavailable(SomeComfortError):
    """SomeComfort Service Unavailable."""

class UnexpectedResponse(SomeComfortError):
    """SomeComfort responded with incorrect type."""

class UnauthorizedError(SomeComfortError):
    """Unauthorized response from SomeComfort."""


# ============== Client ==============

def _convert_errors(fn):
    """Decorator to convert aiohttp errors to our exceptions."""
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except aiohttp.ClientError as ex:
            _LOG.error("Connection Timeout: %s", ex)
            raise ConnectionError("Connection Timeout") from ex
    return wrapper


class AIOSomeComfort:
    """Improved AIOSomeComfort API Client with auto-retry."""

    def __init__(
        self,
        username: str | None,
        password: str | None,
        timeout: int = 30,
        session: aiohttp.ClientSession = None,
        retry_count: int = DEFAULT_RETRY_COUNT,
    ) -> None:
        self._username = username
        self._password = password
        self._session = session
        self._timeout = timeout
        self._retry_count = retry_count
        self._headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate",
        }
        self._locations = {}
        self._baseurl = f"https://{DOMAIN}"
        self._null_cookie_count = 0
        self._next_login = datetime.datetime.now(datetime.timezone.utc)
        self._counter = 1700000000000
        self._is_authenticated = False

    @property
    def next_login(self) -> datetime.datetime:
        """Return next allowed login time for rate limit."""
        return self._next_login

    @property
    def is_authenticated(self) -> bool:
        """Return whether we believe we're authenticated."""
        return self._is_authenticated

    def _set_null_count(self) -> None:
        """Set null cookie count and retry timeout."""
        self._null_cookie_count += 1
        self._is_authenticated = False
        if self._null_cookie_count >= MAX_LOGIN_ATTEMPTS:
            self._next_login = datetime.datetime.now(datetime.timezone.utc) + MIN_LOGIN_TIME
            _LOG.warning("Rate limited after %d failed attempts, waiting until %s",
                        MAX_LOGIN_ATTEMPTS, self._next_login)

    @_convert_errors
    async def login(self) -> None:
        """Login to Honeywell API."""
        url = f"{self._baseurl}/portal"
        params = {
            "timeOffset": "480",
            "UserName": self._username,
            "Password": self._password,
            "RememberMe": "false",
        }
        self._headers["Content-Type"] = "application/x-www-form-urlencoded"
        url = URL(f"{url}?{urllib.urlencode(params)}", encoded=True)

        if self._next_login > datetime.datetime.now(datetime.timezone.utc):
            wait_time = self._next_login - datetime.datetime.now(datetime.timezone.utc)
            raise APIRateLimited(f"Rate limit on login: Waiting {wait_time}")

        _LOG.debug("Attempting login for %s", self._username)
        resp = await self._session.post(
            url, timeout=self._timeout, headers=self._headers
        )
        
        # Handle the malformed cookie
        cookies = resp.cookies
        if AUTH_COOKIE in cookies:
            cookies[AUTH_COOKIE]["expires"] = ''
            self._session.cookie_jar.update_cookies(
                cookies=cookies, response_url=URL(resp.host)
            )

        if resp.status == 401:
            _LOG.error("Login as %s failed (401)", self._username)
            self._set_null_count()
            raise AuthError(f"Login as {self._username} failed")

        if resp.status != 200:
            _LOG.error("Connection error during login: %s", resp.status)
            raise ConnectionError(f"Connection error {resp.status}")

        # Verify login with portal redirect
        self._headers["Content-Type"] = "application/json"
        resp2 = await self._session.get(
            f"{self._baseurl}/portal", timeout=self._timeout, headers=self._headers
        )

        if AUTH_COOKIE in resp2.cookies and resp2.cookies[AUTH_COOKIE].value == "":
            _LOG.error("Login returned null cookie - site may be down")
            self._set_null_count()
            raise AuthError(f"Null cookie error {resp2.status}")

        if resp2.status == 401:
            _LOG.error("Login verification failed (401)")
            self._set_null_count()
            raise AuthError(f"Login verification failed {resp2.status}")

        if resp2.status != 200:
            _LOG.error("Connection error during login verification: %s", resp2.status)
            raise ConnectionError(f"Connection error {resp2.status}")

        # Success!
        self._null_cookie_count = 0
        self._is_authenticated = True
        _LOG.info("Successfully logged in as %s", self._username)

    async def ensure_authenticated(self) -> None:
        """Ensure we're authenticated, re-login if needed."""
        if not self._is_authenticated:
            _LOG.info("Not authenticated, logging in")
            await self.login()

    async def _request_json(self, method: str, *args, **kwargs) -> str | None:
        """Make a JSON API request (internal, no retry)."""
        if "timeout" not in kwargs:
            kwargs["timeout"] = self._timeout
        kwargs["headers"] = self._headers
        
        resp: aiohttp.ClientResponse = await getattr(self._session, method)(
            *args, **kwargs
        )

        # Handle malformed cookie
        cookies = resp.cookies
        if AUTH_COOKIE in cookies:
            cookies[AUTH_COOKIE]["expires"] = ''
            self._session.cookie_jar.update_cookies(
                cookies=cookies, response_url=URL(resp.host)
            )

        req = args[0].replace(self._baseurl, "")
        
        if resp.status == 200 and resp.content_type in ["application/json", "application/octet-stream"]:
            self._null_cookie_count = 0
            if resp.content_type == "application/json":
                return await resp.json()
            return resp

        if resp.status == 401:
            _LOG.warning("401 Unauthorized - session likely expired")
            self._is_authenticated = False
            raise UnauthorizedError("401 Error (session expired)")

        if resp.status == 403:
            _LOG.warning("403 Forbidden - may be rate limited or session expired")
            self._is_authenticated = False
            raise UnauthorizedError("403 Error (forbidden)")

        if resp.status in [500, 502, 503] or len(resp.history) > 0:
            _LOG.warning("Service unavailable (%s)", resp.status)
            raise ServiceUnavailable(f"Service Unavailable {resp.status}")

        _LOG.info("Unexpected API response %s from %s", resp.status, req)
        raise UnexpectedResponse(f"API returned {resp.status}, {req}")

    async def _request_json_with_retry(
        self, 
        method: str, 
        *args, 
        retry_count: int | None = None,
        **kwargs
    ) -> str | None:
        """
        Make a JSON API request with automatic retry and re-authentication.
        
        This is the KEY IMPROVEMENT over the original library.
        """
        retries = retry_count if retry_count is not None else self._retry_count
        last_error = None

        for attempt in range(retries):
            try:
                await self.ensure_authenticated()
                return await self._request_json(method, *args, **kwargs)
                
            except UnauthorizedError as e:
                _LOG.warning("Auth error on attempt %d/%d, re-authenticating: %s", 
                           attempt + 1, retries, e)
                self._is_authenticated = False
                try:
                    await self.login()
                except (AuthError, APIRateLimited) as auth_err:
                    last_error = auth_err
                    if attempt < retries - 1:
                        backoff = RETRY_BACKOFF_BASE ** attempt
                        _LOG.info("Auth failed, waiting %ds before retry", backoff)
                        await asyncio.sleep(backoff)
                    continue
                    
            except ServiceUnavailable as e:
                _LOG.warning("Service unavailable on attempt %d/%d: %s",
                           attempt + 1, retries, e)
                last_error = e
                if attempt < retries - 1:
                    backoff = RETRY_BACKOFF_BASE ** attempt
                    _LOG.info("Waiting %ds before retry", backoff)
                    await asyncio.sleep(backoff)
                continue
                
            except ConnectionError as e:
                _LOG.warning("Connection error on attempt %d/%d: %s",
                           attempt + 1, retries, e)
                last_error = e
                if attempt < retries - 1:
                    backoff = RETRY_BACKOFF_BASE ** attempt
                    _LOG.info("Waiting %ds before retry", backoff)
                    await asyncio.sleep(backoff)
                continue

        # All retries exhausted
        _LOG.error("All %d retry attempts failed", retries)
        if last_error:
            raise last_error
        raise SomeComfortError("Request failed after all retries")

    async def _get_json(self, *args, **kwargs) -> str | None:
        """GET request with retry."""
        return await self._request_json_with_retry("get", *args, **kwargs)

    async def _post_json(self, *args, **kwargs) -> str | None:
        """POST request with retry."""
        return await self._request_json_with_retry("post", *args, **kwargs)

    async def _get_locations(self) -> list:
        """Get all locations for the account."""
        json_responses: list = []
        url = f"{self._baseurl}/portal/Location/GetLocationListData/"
        
        for page in range(1, 5):
            params = {"page": page, "filter": ""}
            # Use internal method without retry for pagination
            try:
                await self.ensure_authenticated()
                resp = await self._session.post(
                    url, params=params, headers=self._headers, timeout=self._timeout
                )
                if resp.content_type == "application/json":
                    json_responses.extend(await resp.json())
                    
                cookies = resp.cookies
                if AUTH_COOKIE in cookies:
                    cookies[AUTH_COOKIE]["expires"] = ''
                    self._session.cookie_jar.update_cookies(
                        cookies=cookies, response_url=URL(resp.host)
                    )
            except Exception as e:
                _LOG.warning("Error fetching location page %d: %s", page, e)
                break
                
        return json_responses if json_responses else None

    async def get_thermostat_data(self, thermostat_id: str) -> str:
        """Get thermostat data from API with retry."""
        url = f"{self._baseurl}/portal/Device/CheckDataSession/{thermostat_id}?_={self._counter}"
        self._counter += 1
        return await self._get_json(url)

    async def get_data(self, thermostat_id: str) -> str:
        """Get device total data structure with retry."""
        url = f"{self._baseurl}/portal/Device/Menu/GetData?deviceID={thermostat_id}"
        return await self._post_json(url)

    async def set_thermostat_settings(
        self, thermostat_id: str, settings: dict[str, str]
    ) -> None:
        """Set thermostat settings with retry."""
        data = {
            "DeviceID": thermostat_id,
            "SystemSwitch": None,
            "HeatSetpoint": None,
            "CoolSetpoint": None,
            "HeatNextPeriod": None,
            "CoolNextPeriod": None,
            "StatusHeat": None,
            "StatusCool": None,
            "FanMode": None,
        }
        data.update(settings)
        
        url = f"{self._baseurl}/portal/Device/SubmitControlScreenChanges"
        result = await self._post_json(url, json=data)
        
        if result is None or result.get("success") != 1:
            raise APIError("API rejected thermostat settings")

    @_convert_errors
    async def discover(self) -> None:
        """Discover devices on the account with retry on failure."""
        from .location import Location  # Avoid circular import
        
        await self.ensure_authenticated()
        raw_locations = await self._get_locations()
        
        if raw_locations is not None:
            for raw_location in raw_locations:
                try:
                    location = await Location.from_api_response(self, raw_location)
                    self._locations[location.locationid] = location
                except KeyError as ex:
                    _LOG.exception(
                        "Failed to process location `%s`: missing %s element",
                        raw_location.get("LocationID", "unknown"), ex.args[0]
                    )

    @property
    def locations_by_id(self) -> dict:
        """A dict of all locations indexed by id."""
        return self._locations

    @property
    def default_device(self):
        """Return the first device found."""
        for location in self.locations_by_id.values():
            for device in location.devices_by_id.values():
                return device
        return None

    def get_device(self, device_id: str):
        """Find a device by id."""
        for location in self.locations_by_id.values():
            for ident, device in location.devices_by_id.items():
                if ident == device_id:
                    return device
        return None
