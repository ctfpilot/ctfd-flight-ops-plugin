import os
import re
import time
from typing import Optional, Tuple

from CTFd.plugins import bypass_csrf_protection
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only, ratelimit
from CTFd.utils.logging import log
from CTFd.utils.modes import TEAMS_MODE
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import during_ctf_time_only
from flask import Blueprint, jsonify, render_template, request

from .config import (
    API_VERSION,
    CHALLENGE_REGEX,
    CONFIG_DISPATCHER_URL,
    CONFIG_JWT_AUDIENCE,
    CONFIG_JWT_EXPIRATION,
    CONFIG_JWT_ISSUER,
    CONFIG_JWT_SECRET,
    CONFIG_REQUEST_TIMEOUT,
    CONFIG_TERMINAL_ID,
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_EXPIRATION,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_TERMINAL_ID,
)
from .errors import (
    ConfigurationError,
    InvalidRequest,
    MaxChallengesError,
    NotAuthenticatedError,
    RateLimitError,
    UnknownError,
    UpstreamUnavailable,
    ValidationError,
)
from .lib import (
    DispatcherClient,
    DispatcherError,
    build_status_response,
    build_status_responses,
    format_error_response,
    select_relevant_flight,
)


POLL_BASE_INTERVAL_MS = 5000
POLL_MAX_INTERVAL_MS = 30000
POLL_BACKOFF_MULTIPLIER = 1.6
POLL_JITTER_MS = 750
POLL_READY_INTERVAL_MS = 30000
POLL_READY_JITTER_MS = 15000


blueprint = Blueprint(
    "flight_ops",
    __name__,
    template_folder="templates",
    static_folder="assets",
)


def register_app(app):
    app.register_blueprint(blueprint)


def _normalize_k8s_name(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]", "-", (value or "").lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized[:63] or fallback


def _get_owner_and_terminal() -> Optional[Tuple[str, str]]:
    session = get_current_user()
    if not session or not session.id:
        return None

    owner_id = str(session.id)
    if get_config("user_mode") == TEAMS_MODE:
        if not session.team_id:
            return None
        owner_id = str(session.team_id)

    terminal_id = str(get_config_terminal())
    return _normalize_k8s_name(owner_id, "owner"), _normalize_k8s_name(terminal_id, "ctfd")


def get_config_dispatcher_url(default=None):
    value = os.getenv("FLIGHT_OPS_DISPATCHER_URL") or get_config(CONFIG_DISPATCHER_URL)
    return value or default


def get_config_jwt_secret(default=None):
    value = os.getenv("FLIGHT_OPS_JWT_SECRET") or get_config(CONFIG_JWT_SECRET)
    return value or default


def get_config_jwt_issuer(default=None):
    value = os.getenv("FLIGHT_OPS_JWT_ISSUER") or get_config(CONFIG_JWT_ISSUER)
    return value or default


def get_config_jwt_audience(default=DEFAULT_JWT_AUDIENCE):
    value = os.getenv("FLIGHT_OPS_JWT_AUDIENCE") or get_config(CONFIG_JWT_AUDIENCE)
    return value or default


def get_config_jwt_expiration(default=DEFAULT_JWT_EXPIRATION):
    raw = os.getenv("FLIGHT_OPS_JWT_EXPIRATION") or get_config(CONFIG_JWT_EXPIRATION)
    try:
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


def get_config_terminal(default=DEFAULT_TERMINAL_ID):
    value = os.getenv("FLIGHT_OPS_TERMINAL_ID") or get_config(CONFIG_TERMINAL_ID)
    return value or default


def get_config_timeout(default=DEFAULT_REQUEST_TIMEOUT):
    raw = os.getenv("FLIGHT_OPS_REQUEST_TIMEOUT") or get_config(CONFIG_REQUEST_TIMEOUT)
    try:
        timeout = int(raw) if raw else default
    except (TypeError, ValueError):
        timeout = default
    return max(1, min(timeout, 60))


def _create_client(owner: str, terminal: str) -> Optional[DispatcherClient]:
    dispatcher_url = get_config_dispatcher_url()
    jwt_secret = get_config_jwt_secret()
    jwt_issuer = get_config_jwt_issuer()
    jwt_audience = get_config_jwt_audience()
    jwt_expiration = get_config_jwt_expiration()
    timeout = get_config_timeout()

    if not dispatcher_url or not jwt_secret or not jwt_issuer:
        return None

    return DispatcherClient(
        base_url=dispatcher_url,
        jwt_secret=jwt_secret,
        jwt_issuer=jwt_issuer,
        jwt_audience=jwt_audience,
        jwt_expiration=jwt_expiration,
        owner=owner,
        terminal=terminal,
        timeout=timeout,
    )


def _load_current_flight(client: DispatcherClient, challenge: str):
    payload = client.list_flights_for_plan(challenge)
    items = payload.get("items") or []
    return select_relevant_flight(items)

def _load_all_flights(client: DispatcherClient):
    payload = client.list_flights()
    return payload.get("items") or []


def _dispatcher_error_response(exc: DispatcherError):
    status_code = exc.status_code

    if status_code in (401, 403):
        return format_error_response(NotAuthenticatedError) + ({},)

    if status_code == 409:
        return format_error_response(MaxChallengesError) + ({},)

    if status_code == 429:
        payload, status = format_error_response(RateLimitError, exc.client_message)
        headers = {}
        if exc.retryAfter:
            headers["Retry-After"] = str(exc.retryAfter)
        return payload, status, headers

    if status_code in (500, 502, 503, 504):
        return format_error_response(UpstreamUnavailable) + ({},)

    if 400 <= status_code < 500:
        return format_error_response(InvalidRequest, exc.client_message) + ({},)

    return format_error_response(UnknownError) + ({},)


def _error_response(payload, status, headers):
    response = jsonify(payload)
    response.status_code = status
    for key, value in headers.items():
        response.headers[key] = value
    return response


@blueprint.route("/api/flight_ops/spec", methods=["GET"])
@bypass_csrf_protection
@during_ctf_time_only
@ratelimit(method="GET", limit=120, interval=60, key_prefix="rl_fo_spec")
def get_spec():
    spec = {
        "apiVersion": API_VERSION,
        "kind": "flight-ops-frontend-spec",
        "polling": {
            "baseIntervalMs": POLL_BASE_INTERVAL_MS,
            "maxIntervalMs": POLL_MAX_INTERVAL_MS,
            "backoffMultiplier": POLL_BACKOFF_MULTIPLIER,
            "jitterMs": POLL_JITTER_MS,
            "readyIntervalMs": POLL_READY_INTERVAL_MS,
            "readyJitterMs": POLL_READY_JITTER_MS,
            "pollStatuses": ["pending", "ready", "unknown"],
        },
    }
    return jsonify(spec), 200


def _challenge_ids_by_template_name():
    from .flight_challenge import FlightOpsChallenge

    rows = FlightOpsChallenge.query.with_entities(
        FlightOpsChallenge.id, FlightOpsChallenge.template_name
    ).all()

    mapping = {}
    for challenge_id, template_name in rows:
        mapping.setdefault(template_name, []).append(challenge_id)
    return mapping


@blueprint.route("/api/flight_ops", methods=["GET"])
@bypass_csrf_protection
@during_ctf_time_only
@ratelimit(method="GET", limit=120, interval=60, key_prefix="rl_fo_get")
def challenges_status():
    started = time.time()

    owner_terminal = _get_owner_and_terminal()
    if not owner_terminal:
        payload, status = format_error_response(NotAuthenticatedError)
        return jsonify(payload), status

    owner, terminal = owner_terminal
    client = _create_client(owner=owner, terminal=terminal)
    if client is None:
        payload, status = format_error_response(ConfigurationError)
        return jsonify(payload), status

    try:
        current_flights = _load_all_flights(client)
        payload = build_status_responses(current_flights)
        challenge_ids_by_template_name = _challenge_ids_by_template_name()
        for entry in payload:
            entry["challenge_ids"] = challenge_ids_by_template_name.get(entry["flight_plan"], [])
        duration_ms = int((time.time() - started) * 1000)
        log(
            "flight_ops",
            "event=status_sync duration_ms={duration} method={method}",
            duration=duration_ms,
            method=request.method,
        )
        return jsonify(payload), 200
    except DispatcherError as exc:
        detail = exc.message
        payload, status, headers = _dispatcher_error_response(exc)
    except Exception as exc:
        detail = str(exc)
        payload, status = format_error_response(UnknownError)
        headers = {}

    log(
        "flight_ops",
        "event=status_sync_error status={status} error={error}",
        status=status,
        error=detail,
    )
    return _error_response(payload, status, headers)


@blueprint.route("/api/flight_ops/<challenge>", methods=["GET", "POST"])
@bypass_csrf_protection
@during_ctf_time_only
@ratelimit(method="GET", limit=120, interval=60, key_prefix="rl_fo_get")
@ratelimit(method="POST", limit=20, interval=60, key_prefix="rl_fo_post")
def challenge_status(challenge):
    started = time.time()

    owner_terminal = _get_owner_and_terminal()
    if not owner_terminal:
        payload, status = format_error_response(NotAuthenticatedError)
        return jsonify(payload), status

    if not re.match(CHALLENGE_REGEX, challenge):
        payload, status = format_error_response(ValidationError)
        return jsonify(payload), status
    challenge = challenge.lower()

    owner, terminal = owner_terminal
    client = _create_client(owner=owner, terminal=terminal)
    if client is None:
        payload, status = format_error_response(ConfigurationError)
        return jsonify(payload), status

    try:
        if request.method == "POST":
            if not request.is_json:
                payload, status = format_error_response(InvalidRequest)
                return jsonify(payload), status

            requested_action = (request.json or {}).get("action")

            if requested_action == "create":
                client.depart(challenge)
            elif requested_action == "extend":
                current = _load_current_flight(client, challenge)
                if not current or not current.get("name"):
                    payload, status = format_error_response(InvalidRequest)
                    payload["error"]["message"] = "No active flight found to refresh."
                    return jsonify(payload), 404
                client.refresh(current["name"])
            elif requested_action == "terminate":
                current = _load_current_flight(client, challenge)
                if not current or not current.get("name"):
                    payload, status = format_error_response(InvalidRequest)
                    payload["error"]["message"] = "No active flight found to terminate."
                    return jsonify(payload), 404
                client.land(current["name"])
            else:
                payload, status = format_error_response(InvalidRequest)
                return jsonify(payload), status

        try:
            current_flight = _load_current_flight(client, challenge)
        except DispatcherError as exc:
            if request.method != "POST":
                raise
            
            log(
                "flight_ops",
                "event=post_action_status_read_failed challenge={challenge} error={error}",
                challenge=challenge,
                error=exc.message,
            )
            payload = build_status_response(None)
            payload["flight_plan"] = challenge
            payload["status"] = "unknown"
            return jsonify(payload), 200

        payload = build_status_response(current_flight)
        duration_ms = int((time.time() - started) * 1000)
        log(
            "flight_ops",
            "event=status_sync challenge={challenge} status={status} duration_ms={duration} method={method}",
            challenge=challenge,
            status=payload.get("status", "unknown"),
            duration=duration_ms,
            method=request.method,
        )
        return jsonify(payload), 200
    except DispatcherError as exc:
        detail = exc.message
        payload, status, headers = _dispatcher_error_response(exc)
    except Exception as exc:
        detail = str(exc)
        payload, status = format_error_response(UnknownError)
        headers = {}

    log(
        "flight_ops",
        "event=status_sync_error challenge={challenge} status={status} error={error}",
        challenge=challenge,
        status=status,
        error=detail,
    )
    return _error_response(payload, status, headers)


@blueprint.route("/admin/flight_ops", methods=["GET", "POST"])
@admins_only
def get_config_page():
    alert = None
    if request.method == "POST":
        dispatcher_url = request.form.get("dispatcher_url", "").strip()
        jwt_secret = request.form.get("jwt_secret", "").strip()
        jwt_issuer = request.form.get("jwt_issuer", "").strip()
        jwt_audience = request.form.get("jwt_audience", DEFAULT_JWT_AUDIENCE).strip()
        jwt_expiration = request.form.get("jwt_expiration", str(DEFAULT_JWT_EXPIRATION)).strip()
        terminal_id = request.form.get("terminal_id", DEFAULT_TERMINAL_ID).strip()
        timeout = request.form.get("request_timeout", str(DEFAULT_REQUEST_TIMEOUT)).strip()

        if not dispatcher_url or not jwt_issuer:
            alert = {"type": "danger", "message": "Dispatcher URL and JWT issuer are required."}
        else:
            set_config(CONFIG_DISPATCHER_URL, dispatcher_url)
            set_config(CONFIG_JWT_ISSUER, jwt_issuer)
            if jwt_secret:
                set_config(CONFIG_JWT_SECRET, jwt_secret)
            set_config(CONFIG_JWT_AUDIENCE, jwt_audience or DEFAULT_JWT_AUDIENCE)
            set_config(CONFIG_JWT_EXPIRATION, jwt_expiration or str(DEFAULT_JWT_EXPIRATION))
            set_config(CONFIG_TERMINAL_ID, terminal_id or DEFAULT_TERMINAL_ID)
            set_config(CONFIG_REQUEST_TIMEOUT, timeout or str(DEFAULT_REQUEST_TIMEOUT))
            alert = {"type": "success", "message": "Flight Ops configuration saved."}

    return render_template(
        "admin.html",
        dispatcher_url=get_config_dispatcher_url(""),
        jwt_secret="******************" if get_config_jwt_secret() else "",
        jwt_issuer=get_config_jwt_issuer(""),
        jwt_audience=get_config_jwt_audience(DEFAULT_JWT_AUDIENCE),
        jwt_expiration=get_config_jwt_expiration(DEFAULT_JWT_EXPIRATION),
        terminal_id=get_config_terminal(DEFAULT_TERMINAL_ID),
        request_timeout=get_config_timeout(DEFAULT_REQUEST_TIMEOUT),
        alert=alert,
    )
