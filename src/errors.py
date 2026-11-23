from dataclasses import dataclass


@dataclass(frozen=True)
class PluginError:
    type: str
    message: str
    code: int


ConfigurationError = PluginError(
    "ConfigurationError",
    "Flight Ops plugin is not configured correctly. Please contact an administrator.",
    500,
)

UnknownError = PluginError(
    "UnknownError",
    "An unexpected error occurred. Please try again shortly.",
    500,
)

InvalidRequest = PluginError("InvalidRequest", "Invalid request.", 400)
ValidationError = PluginError("ValidationError", "Invalid challenge.", 400)
NotAuthenticatedError = PluginError(
    "NotAuthenticatedError", "Please log in and join a team.", 401
)
UpstreamUnavailable = PluginError(
    "UpstreamUnavailable", "Flight Ops is currently unavailable.", 503
)

RateLimitError = PluginError(
    "RateLimitError",
    "This action was performed too quickly. Please wait and try again.",
    429,
)

MaxChallengesError = PluginError(
    "MaxChallengesError",
    "Maximum number of challenges reached. Please terminate an existing challenge before starting a new one.",
    409,
)
