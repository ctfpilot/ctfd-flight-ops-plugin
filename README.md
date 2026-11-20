# CTFd Flight Ops Plugin

> [!IMPORTANT]
> CTF Pilot Flight Ops replaces [Kube-CTF](https://github.com/ctfpilot/kube-ctf), and is the actively maintained instancing system for CTF Pilot.

CTFd plugin for integrating challenge instance lifecycle with the [CTF Pilot Flight Ops dispatcher](https://github.com/ctfpilot/flight-ops).

It acts as the main connection system between CTFd and [Flight Ops](https://github.com/ctfpilot/flight-ops), allowing to integrate challenge start and stop directly into the CTFd interface, allowing teams to start and stop their instances.

*This plugin follows the same principles as the [kube-ctf](https://github.com/ctfpilot/ctfd-kubectf-plugin) CTFd plugin, but have been rebuildt to fit with the CTF Pilot Flight Ops system.*

## Features

- Custom CTFd challenge type: `flightops`
- Admin configuration panel for dispatcher and JWT settings
- Backend-owned API contract for the CTFd frontend (not raw dispatcher passthrough)
- JWT auth to dispatcher with Flight Ops claim shape
- Production-focused error mapping and rate limiting
- Frontend status polling

## Install

1. Copy `src/` into `CTFd/plugins/`.
2. Install dependencies from `src/requirements.txt`.
3. Restart or start CTFd.
4. Open `/admin/flight_ops` and configure dispatcher + JWT settings.

## Theme Requirement

Add this block in your active CTFd theme `challenge.html`:

```html
{% block kubectf_info %}
{% endblock %}
```

Recommended placement: below the connection info area.

## API exposed through CTFd

The plugin exposes a frontend-facing status API:

- `GET /api/flight_ops/spec`
- `GET /api/flight_ops/{flight_plan}`
- `POST /api/flight_ops/{flight_plan}` with JSON body `{ "action": "create" | "extend" | "terminate" }`

### Status Response Schema (normalized)

```json
{
  "apiVersion": "v1",
  "kind": "flight-ops-status",
  "flight_name": "demo-flight",
  "connection_strings": [
    "https://challenge.example.com",
    "ncat --ssl challenge.example.com 443"
  ],
  "expires_at": "2026-01-01T01:00:00Z",
  "started_at": "2026-01-01T00:00:00Z",
  "status": "pending|ready|landed|failed|missing|unknown"
}
```

The response intentionally avoids Kubernetes resource-like structure and only includes essential values used by the challenge UI.

### Polling Strategy Endpoint

`GET /api/flight_ops/spec` returns polling metadata (base interval, max interval, backoff multiplier, jitter, and statuses that should be polled).

## Flight Ops Dispatcher Integration Notes

- `create` maps to: `POST /api/flightplans/{name}/depart`
- `extend` maps to: `POST /api/flights/{name}/refresh`
- `terminate` maps to: `POST /api/flights/{name}/land`
- Status lookup chooses the most relevant flight for the caller and plan.

The plugin creates JWTs with required dispatcher claims, including `iss`, `aud`, `exp`, `iat`, `nbf`, `jti`, and `flight` context.

## Configuration

CTFd path: `/admin/flight_ops`

Required:

- Dispatcher URL
- JWT Secret
- JWT Issuer

Optional:

- JWT Audience (default: `ground-control-dispatcher`)
- JWT Expiration seconds (default: `120`)
- Terminal ID (default: `ctfd`)
- Request timeout seconds (default: `10`)

Environment variable overrides are supported:

- `FLIGHT_OPS_DISPATCHER_URL`
- `FLIGHT_OPS_JWT_SECRET`
- `FLIGHT_OPS_JWT_ISSUER`
- `FLIGHT_OPS_JWT_AUDIENCE`
- `FLIGHT_OPS_JWT_EXPIRATION`
- `FLIGHT_OPS_TERMINAL_ID`
- `FLIGHT_OPS_REQUEST_TIMEOUT`

## Frontend Polling

The challenge view polls status while flights are `pending` or `ready`.

Polling behavior:

- Base interval: `5000` ms
- Exponential backoff multiplier: `1.6`
- Max interval: `30000` ms
- Per-request jitter: up to `750` ms

Polling stops automatically on terminal status (`missing`, `landed`, `failed`, `unknown`).

## Logging

The backend emits structured status-sync logs with challenge, status, method, and request latency.

## Tests

Run tests with:

```sh
python -m unittest discover -s tests -p "test_*.py"
```

## Contributing

We welcome contributions of all kinds, from **code** and **documentation** to **bug reports** and **feedback**!

Please check the [Contribution Guidelines (`CONTRIBUTING.md`)](/CONTRIBUTING.md) for detailed guidelines on how to contribute.

To maintain the ability to distribute contributions across all our licensing models, **all code contributions require signing a Contributor License Agreement (CLA)**.
You can review **[the CLA here](https://github.com/ctfpilot/cla)**. CLA signing happens automatically when you create your first pull request.  
To administrate the CLA signing process, we are using **[CLA assistant lite](https://github.com/marketplace/actions/cla-assistant-lite)**.

*A copy of the CLA document is also included in this repository as [`CLA.md`](CLA.md).*  
*Signatures are stored in the [`cla` repository](https://github.com/ctfpilot/cla).*

## License

This repository is licensed under the **EUPL-1.2 License**.  
You can find the full license in the **[LICENSE](LICENSE)** file.

We encourage all modifications and contributions to be shared back with the community, for example through pull requests to this repository.  
We also encourage all derivative works to be publicly available under the **EUPL-1.2 License**.  
At all times must the license terms be followed.

For information regarding how to contribute, see the [contributing](#contributing) section above.

CTF Pilot is owned and maintained by **[The0Mikkel](https://github.com/The0mikkel)**.  
Required Notice: Copyright Mikkel Albrechtsen (<https://themikkel.dk>)

## Code of Conduct

We expect all contributors to adhere to our [Code of Conduct](/CODE_OF_CONDUCT.md) to ensure a welcoming and inclusive environment for all.
