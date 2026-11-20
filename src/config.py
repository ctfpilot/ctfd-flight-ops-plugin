CONFIG_DISPATCHER_URL = "flight_ops_dispatcher_url"
CONFIG_JWT_SECRET = "flight_ops_jwt_secret"
CONFIG_JWT_ISSUER = "flight_ops_jwt_issuer"
CONFIG_JWT_AUDIENCE = "flight_ops_jwt_audience"
CONFIG_JWT_EXPIRATION = "flight_ops_jwt_expiration"
CONFIG_TERMINAL_ID = "flight_ops_terminal_id"
CONFIG_REQUEST_TIMEOUT = "flight_ops_request_timeout"

CHALLENGE_REGEX = r"^[a-zA-Z0-9-]+$"

DEFAULT_JWT_AUDIENCE = "ground-control-dispatcher"
DEFAULT_JWT_EXPIRATION = 120
DEFAULT_TERMINAL_ID = "ctfd"
DEFAULT_REQUEST_TIMEOUT = 10

API_VERSION = "v1"
API_KIND = "flight-ops-status"
