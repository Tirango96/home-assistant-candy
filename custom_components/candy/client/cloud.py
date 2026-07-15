"""Simply-Fi cloud client for one-time appliance data fetch during setup."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import logging
import secrets

import aiohttp

_LOGGER = logging.getLogger(__name__)

_CIAM_BASE = "https://api-iot.he.services"
_SIMPLY_FI_BASE = "https://simply-fi.herokuapp.com"

_HON_USER_AGENT = "hOn/3 CFNetwork/1240.0.4 Darwin/20.6.0"


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) as base64url strings."""
    verifier = base64url(secrets.token_bytes(64))
    challenge = base64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclasses.dataclass
class CloudApplianceData:
    """Appliance data fetched from Simply-Fi cloud during config setup."""

    mac_address: str
    encryption_key: str
    appliance_model: str
    serial_number: str
    programs: list[dict]


class SimplyFiCloudError(Exception):
    """Raised when cloud auth or appliance fetch fails."""


async def fetch_appliance_data(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    device_ip: str,
) -> CloudApplianceData:
    """Authenticate against Simply-Fi cloud and return appliance data for the given device IP.

    Credentials are used only for this call and must not be stored by the caller.
    Raises SimplyFiCloudError on any failure.
    """
    tokens = await _authenticate(session, email, password)
    appliances = await _fetch_appliances(session, tokens)
    return _match_appliance(appliances, device_ip)


async def _authenticate(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
) -> dict:
    """Perform PKCE auth against hOn CIAM. Returns token dict."""
    verifier, challenge = _generate_pkce_pair()

    # Step 1: GET /ciam/authorize
    async with session.get(
        f"{_CIAM_BASE}/ciam/authorize",
        params={"username": email, "password": password, "code_challenge": challenge},
        headers={"User-Agent": _HON_USER_AGENT},
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise SimplyFiCloudError(
                f"CIAM authorize failed (HTTP {resp.status}): {text[:200]}"
            )
        authorize_data = await resp.json()

    session_id = authorize_data.get("session_id")
    if not session_id:
        raise SimplyFiCloudError(
            f"CIAM authorize response missing session_id: {authorize_data}"
        )

    # Step 2: POST /ciam/token
    async with session.post(
        f"{_CIAM_BASE}/ciam/token",
        json={"session_id": session_id, "code_verifier": verifier},
        headers={"User-Agent": _HON_USER_AGENT},
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise SimplyFiCloudError(
                f"CIAM token exchange failed (HTTP {resp.status}): {text[:200]}"
            )
        token_data = await resp.json()

    tokens = token_data.get("tokens")
    if not tokens or "id_token" not in tokens or "cognito_token" not in tokens:
        raise SimplyFiCloudError(
            f"CIAM token response missing expected fields: {list(token_data.keys())}"
        )

    _LOGGER.debug("Simply-Fi cloud authentication succeeded")
    return tokens


async def _fetch_appliances(
    session: aiohttp.ClientSession,
    tokens: dict,
) -> list[dict]:
    """Fetch appliance list from Simply-Fi."""
    headers = {
        "id-token": tokens["id_token"],
        "cognito-token": tokens["cognito_token"],
        "Authorization": f"Bearer {tokens['id_token']}",
        "Salesforce-Auth": "1",
        "User-Agent": _HON_USER_AGENT,
    }
    async with session.get(
        f"{_SIMPLY_FI_BASE}/api/v1/appliances.json?with_hidden_programs=1",
        headers=headers,
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise SimplyFiCloudError(
                f"Simply-Fi appliances fetch failed (HTTP {resp.status}): {text[:200]}"
            )
        data = await resp.json()

    if not isinstance(data, list):
        raise SimplyFiCloudError(
            f"Unexpected appliances response format: {type(data).__name__}"
        )

    _LOGGER.debug("Fetched %d appliance(s) from Simply-Fi", len(data))
    return data


def _match_appliance(appliances: list[dict], device_ip: str) -> CloudApplianceData:
    """Find the appliance that matches device_ip via current_status_parameters.

    Falls back to the first appliance if only one is registered and IP cannot be matched,
    since current_status_parameters may not always contain an IP field.
    """
    matched = None

    for entry in appliances:
        appliance = entry.get("appliance", {})
        status_params = appliance.get("current_status_parameters", {})
        # WiFi module may expose its local IP in status
        if status_params.get("ip_address") == device_ip:
            matched = appliance
            break

    if matched is None:
        if len(appliances) == 1:
            _LOGGER.debug(
                "Could not match appliance by IP %s; using the only registered appliance",
                device_ip,
            )
            matched = appliances[0].get("appliance", {})
        else:
            raise SimplyFiCloudError(
                f"No Simply-Fi appliance matched device IP {device_ip}. "
                f"Found {len(appliances)} appliance(s); "
                "ensure the device is registered in the Simply-Fi app."
            )

    encryption_key = matched.get("encryption_key", "")
    if not encryption_key:
        raise SimplyFiCloudError(
            "Appliance data missing encryption_key — cannot proceed with Full Control setup"
        )

    programs = matched.get("programs", [])
    if not programs:
        raise SimplyFiCloudError(
            "Appliance data missing programs — cannot proceed with Full Control setup"
        )

    return CloudApplianceData(
        mac_address=matched.get("mac_address", ""),
        encryption_key=encryption_key,
        appliance_model=matched.get("appliance_model", ""),
        serial_number=matched.get("sixteen_digits_code", ""),
        programs=programs,
    )
