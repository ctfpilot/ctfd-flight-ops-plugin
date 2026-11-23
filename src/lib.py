import time
import uuid
import jwt
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from .config import API_KIND, API_VERSION
from .errors import PluginError

from CTFd.cache import cache

JWT_ALGORITHM = "HS256"


MAX_CLIENT_MESSAGE_LENGTH = 200


class DispatcherError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        retry_after: Optional[int] = None,
        client_message: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retryAfter = retry_after
        self.client_message = client_message


def extract_dispatcher_message(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    candidate = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            candidate = error.get("message") or error.get("detail") or ""
        elif isinstance(error, str):
            candidate = error
        if not candidate:
            candidate = payload.get("message") or payload.get("detail") or ""

    if not candidate:
        candidate = response.text or ""

    #Stay single-line.
    candidate = " ".join(str(candidate).split())

    #Catch HTML Errors.
    if candidate.startswith("<"):
        return ""

    if len(candidate) > MAX_CLIENT_MESSAGE_LENGTH:
        candidate = candidate[:MAX_CLIENT_MESSAGE_LENGTH].rstrip() + "..."
    return candidate


class DispatcherClient:
    def __init__(
        self,
        base_url: str,
        jwt_secret: str,
        jwt_issuer: str,
        jwt_audience: str,
        jwt_expiration: int,
        owner: str,
        terminal: str,
        timeout: int,
    ):
        self.base_url = base_url.rstrip("/")
        self.jwt_secret = jwt_secret
        self.jwt_issuer = jwt_issuer
        self.jwt_audience = jwt_audience
        self.jwt_expiration = jwt_expiration
        self.owner = owner
        self.terminal = terminal
        self.timeout = timeout

    def _create_token(
        self,
        action: str,
        flight_plan: str = "",
        flight: str = "",
        admin: bool = False,
        ttl: Optional[int] = None,
    ) -> str:
        now = int(time.time())
        claims: Dict[str, Any] = {
            "iss": self.jwt_issuer,
            "aud": [self.jwt_audience],
            "exp": now + self.jwt_expiration,
            "iat": now,
            "nbf": now,
            "jti": str(uuid.uuid4()),
            "flight": {
                "action": action,
                "owner": self.owner,
                "terminal": self.terminal,
                "admin": admin,
            },
        }
        if flight_plan:
            claims["flight"]["flight_plan"] = flight_plan
        if flight:
            claims["flight"]["flight"] = flight
        if ttl is not None:
            claims["flight"]["ttl"] = ttl

        return jwt.encode(claims, self.jwt_secret, algorithm=JWT_ALGORITHM)

    def _request(
        self,
        method: str,
        path: str,
        action: str,
        flight_plan: str = "",
        flight: str = "",
        admin: bool = False,
        ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        token = self._create_token(
            action=action,
            flight_plan=flight_plan,
            flight=flight,
            admin=admin,
            ttl=ttl,
        )
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DispatcherError(503, f"dispatcher request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = extract_dispatcher_message(response)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            parsed_retry_after = None
            if retry_after:
                try:
                    parsed_retry_after = int(retry_after)
                except ValueError:
                    pass
            raise DispatcherError(
                429,
                detail or "dispatcher rate limit exceeded",
                retry_after=parsed_retry_after,
                client_message=detail or None,
            )
        if response.status_code >= 400:
            raise DispatcherError(
                response.status_code,
                detail or "dispatcher returned an error",
                client_message=detail or None,
            )

        if not response.text:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise DispatcherError(502, "dispatcher returned invalid JSON") from exc

    @cache.memoize(timeout=1)
    def list_flights(self) -> Dict[str, Any]:
        return self._request("GET", "/api/flights", action="list")

    @cache.memoize(timeout=1)
    def list_flights_for_plan(self, flight_plan: str) -> Dict[str, Any]:
        encoded = quote(flight_plan, safe="")
        return self._request(
            "GET",
            f"/api/flightplans/{encoded}/flights",
            action="list",
            flight_plan=flight_plan,
        )

    def depart(self, flight_plan: str, ttl: Optional[int] = None) -> Dict[str, Any]:
        encoded = quote(flight_plan, safe="")
        payload = self._request(
            "POST",
            f"/api/flightplans/{encoded}/depart",
            action="depart",
            flight_plan=flight_plan,
            ttl=ttl,
        )
        return payload

    def refresh(self, flight_name: str) -> Dict[str, Any]:
        encoded = quote(flight_name, safe="")
        payload = self._request(
            "POST",
            f"/api/flights/{encoded}/refresh",
            action="refresh",
            flight=flight_name,
        )
        return payload

    def land(self, flight_name: str) -> Dict[str, Any]:
        encoded = quote(flight_name, safe="")
        payload = self._request(
            "POST",
            f"/api/flights/{encoded}/land",
            action="land",
            flight=flight_name,
        )
        return payload


PHASE_MAP = {
    "Pending": "pending",
    "InFlight": "ready",
    "Landed": "landed",
    "Failed": "failed",
}


def phase_to_state(phase: Optional[str]) -> str:
    if not phase:
        return "unknown"
    return PHASE_MAP.get(phase, "unknown")


def parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def select_relevant_flight(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not items:
        return None

    if len(items) == 1:
        return items[0]

    phase_priority = {
        "InFlight": 4,
        "Pending": 3,
        "Failed": 2,
        "Landed": 1,
        "": 0,
    }

    def score(item: Dict[str, Any]) -> Tuple[int, int]:
        status = item.get("status") or {}
        phase = status.get("phase") or ""
        launched = parse_iso_timestamp(status.get("launchedAt"))
        expires = parse_iso_timestamp(status.get("expiresAt"))
        latest_ts = launched or expires
        epoch = int(latest_ts.timestamp()) if latest_ts else 0
        return (phase_priority.get(phase, 0), epoch)

    return sorted(items, key=score, reverse=True)[0]


def format_error_response(
    error: PluginError, message: Optional[str] = None
) -> Tuple[Dict[str, Any], int]:
    return {
        "apiVersion": API_VERSION,
        "kind": API_KIND,
        "error": {
            "type": error.type,
            "message": message or error.message,
        },
    }, error.code


def build_status_response(flight: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not flight:
        return {
            "apiVersion": API_VERSION,
            "kind": API_KIND,
            "flight_name": None,
            "flight_plan": None,
            "connection_strings": [],
            "expires_at": None,
            "started_at": None,
            "status": "missing",
        }

    spec = flight.get("spec") or {}
    status = flight.get("status") or {}
    phase = status.get("phase")
    state = phase_to_state(phase)

    return {
        "apiVersion": API_VERSION,
        "kind": API_KIND,
        "flight_name": flight.get("name"),
        "flight_plan": spec.get("flightPlanRef"),
        "connection_strings": status.get("connectionStrings") or [],
        "expires_at": status.get("expiresAt"),
        "started_at": status.get("launchedAt"),
        "status": state,
    }

def build_status_responses(flights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [build_status_response(flight) for flight in flights]
