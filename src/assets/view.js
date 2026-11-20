CTFd._internal.challenge.data = undefined;
CTFd._internal.challenge.preRender = function () { };
CTFd._internal.challenge.postRender = function () { };

(function () {
    const API_SPEC_ENDPOINT = "api/flight_ops/spec";
    const API_BASE = "api/flight_ops/";
    const DEFAULT_POLL_MS = 5000;
    const DEFAULT_MAX_POLL_MS = 30000;
    const DEFAULT_BACKOFF_MULTIPLIER = 1.6;
    const DEFAULT_JITTER_MS = 750;

    let pollTimer = null;
    let currentPollInterval = DEFAULT_POLL_MS;
    let basePollInterval = DEFAULT_POLL_MS;
    let maxPollInterval = DEFAULT_MAX_POLL_MS;
    let backoffMultiplier = DEFAULT_BACKOFF_MULTIPLIER;
    let jitterMs = DEFAULT_JITTER_MS;
    let pollStatuses = ["pending", "ready"];

    function challengeName() {
        const element = document.getElementById("flight-plan-name");
        return (element && element.value ? element.value : "").trim().toLowerCase();
    }

    function setAlert(message, type) {
        const alert = document.getElementById("flight-ops-alert");
        if (!alert) {
            return;
        }

        alert.classList.remove("alert-info", "alert-success", "alert-warning", "alert-danger");
        alert.classList.add(type || "alert-info");
        alert.innerHTML = "";
        alert.append(message || "Status updated.");
    }

    function toggleLoading(button, isLoading) {
        if (!button) {
            return;
        }
        button.disabled = isLoading;
        const icon = button.querySelector("i");
        if (!icon) {
            return;
        }
        if (isLoading) {
            icon.classList.add("fa-spinner", "fa-spin");
        } else {
            icon.classList.remove("fa-spinner", "fa-spin");
        }
    }

    function setButtons(status) {
        const canCreate = ["missing", "landed", "failed", "unknown"].includes(status);
        const canMutate = ["pending", "ready"].includes(status);

        const create = document.querySelector(".create-chal");
        const extend = document.querySelector(".extend-chal");
        const terminate = document.querySelector(".terminate-chal");

        if (create) {
            create.classList.toggle("d-none", !canCreate);
        }
        if (extend) {
            extend.classList.toggle("d-none", !canMutate);
        }
        if (terminate) {
            terminate.classList.toggle("d-none", !canMutate);
        }
    }

    function toClickableUrl(text) {
        const value = (text || "").trim();
        if (!value) {
            return null;
        }

        if (/^https?:\/\//i.test(value)) {
            return value;
        }

        // Convert bare hostnames to HTTPS links so plain URL responses become clickable.
        if (/^[a-z0-9.-]+(?::\d+)?(\/.*)?$/i.test(value) && !value.includes(" ")) {
            return "https://" + value;
        }

        return null;
    }

    function appendConnectionLine(container, entry) {
        const row = document.createElement("div");
        row.classList.add("mb-1");

        const url = toClickableUrl(entry);
        if (url) {
            const link = document.createElement("a");
            link.href = url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = entry;
            row.append(link);
        } else {
            const code = document.createElement("code");
            code.textContent = entry;
            row.append(code);
        }

        container.append(row);
    }

    function renderConnections(payload) {
        const alert = document.getElementById("flight-ops-alert");
        if (!alert) {
            return;
        }

        const lines = [];
        if (payload.expires_at) {
            lines.push("Expires at " + payload.expires_at);
        }

        if (lines.length > 0) {
            alert.append(document.createElement("br"));
            lines.forEach((line) => {
                alert.append(document.createTextNode(line));
                alert.append(document.createElement("br"));
            });
        }

        if (payload.connection_strings && payload.connection_strings.length) {
            const heading = document.createElement("div");
            heading.classList.add("mt-2", "font-weight-bold");
            heading.textContent = "Connection details";
            alert.append(heading);

            const list = document.createElement("div");
            payload.connection_strings.forEach((entry) => {
                appendConnectionLine(list, entry);
            });
            alert.append(list);
        }
    }

    function computeNextPollDelay() {
        const jitter = Math.floor(Math.random() * jitterMs);
        return Math.min(maxPollInterval, currentPollInterval + jitter);
    }

    function scheduleNextPoll() {
        stopPolling();
        pollTimer = setTimeout(async function () {
            await refreshStatus();
        }, computeNextPollDelay());
    }

    function resetPollInterval() {
        currentPollInterval = basePollInterval;
    }

    function increasePollInterval() {
        currentPollInterval = Math.min(
            maxPollInterval,
            Math.floor(currentPollInterval * backoffMultiplier)
        );
    }

    function renderStatus(payload) {
        const phase = payload && payload.status ? payload.status : "unknown";
        const flightName = payload && payload.flight_name ? payload.flight_name : "none";
        const message = "Status: " + phase; //  + ", Flight: " + flightName

        let type = "alert-info";
        if (phase === "ready") {
            type = "alert-success";
        } else if (phase === "pending") {
            type = "alert-warning";
        } else if (phase === "failed") {
            type = "alert-danger";
        }

        setAlert(message, type);
        setButtons(phase);
        renderConnections(payload || {});

        const shouldPoll = pollStatuses.includes(phase);

        if (shouldPoll) {
            scheduleNextPoll();
        } else {
            stopPolling();
        }
    }

    async function parseResponse(response) {
        let body = {};
        try {
            body = await response.json();
        } catch (err) {
            body = {};
        }

        if (!response.ok) {
            if (response.status === 429) {
                const retryAfter = response.headers.get("Retry-After");
                const waitHint = retryAfter ? " Please wait " + retryAfter + " seconds." : "";
                const apiMessage = (body && body.error && body.error.message) || body.message;
                throw new Error(apiMessage || ("Slow down. This action was performed too quickly." + waitHint));
            }

            const message =
                (body && body.error && body.error.message) ||
                body.message ||
                "Failed to reach the backend.";
            throw new Error(message);
        }

        return body;
    }

    async function requestStatus(method, action) {
        const challenge = challengeName();
        if (!challenge) {
            throw new Error("Challenge has no configured instance.");
        }

        const options = {
            method: method,
            headers: {
                "Content-Type": "application/json",
            },
        };

        if (method === "POST") {
            options.body = JSON.stringify({ action: action });
        }

        const response = await fetch(API_BASE + challenge, options);
        return parseResponse(response);
    }

    async function refreshStatus() {
        try {
            const payload = await requestStatus("GET");
            resetPollInterval();
            renderStatus(payload);
        } catch (err) {
            increasePollInterval();
            setAlert(
                (err.message || "Unable to fetch challenge status.") +
                ". Retrying with backoff.",
                "alert-danger"
            );
            scheduleNextPoll();
        }
    }

    function stopPolling() {
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    async function runAction(button, action) {
        toggleLoading(button, true);
        try {
            const payload = await requestStatus("POST", action);
            resetPollInterval();
            renderStatus(payload);
        } catch (err) {
            setAlert(err.message || "Action failed.", "alert-danger");
        } finally {
            toggleLoading(button, false);
        }
    }

    async function loadSpec() {
        try {
            const response = await fetch(API_SPEC_ENDPOINT, { method: "GET" });
            const payload = await parseResponse(response);
            if (payload && payload.polling) {
                const polling = payload.polling;
                if (Number.isInteger(polling.baseIntervalMs)) {
                    basePollInterval = polling.baseIntervalMs;
                }
                if (Number.isInteger(polling.maxIntervalMs)) {
                    maxPollInterval = polling.maxIntervalMs;
                }
                if (typeof polling.backoffMultiplier === "number") {
                    backoffMultiplier = polling.backoffMultiplier;
                }
                if (Number.isInteger(polling.jitterMs)) {
                    jitterMs = polling.jitterMs;
                }
                if (Array.isArray(polling.pollStatuses)) {
                    pollStatuses = polling.pollStatuses;
                }
            }
            resetPollInterval();
        } catch (err) {
            basePollInterval = DEFAULT_POLL_MS;
            maxPollInterval = DEFAULT_MAX_POLL_MS;
            backoffMultiplier = DEFAULT_BACKOFF_MULTIPLIER;
            jitterMs = DEFAULT_JITTER_MS;
            pollStatuses = ["pending", "ready"];
            resetPollInterval();
        }
    }

    window.flightOpsController = {
        create: function (button) {
            runAction(button, "create");
        },
        extend: function (button) {
            runAction(button, "extend");
        },
        terminate: function (button) {
            runAction(button, "terminate");
        },
    };

    setTimeout(async function () {
        await loadSpec();
        await refreshStatus();
    }, 250);
})();
