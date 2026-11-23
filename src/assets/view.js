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
    const DEFAULT_READY_POLL_MS = 30000;
    const DEFAULT_READY_JITTER_MS = 15000;
    const TERMINATING_POLL_MS = 1500;
    const TERMINATING_MAX_ATTEMPTS = 20;

    let pollTimer = null;
    let currentPollInterval = DEFAULT_POLL_MS;
    let basePollInterval = DEFAULT_POLL_MS;
    let maxPollInterval = DEFAULT_MAX_POLL_MS;
    let backoffMultiplier = DEFAULT_BACKOFF_MULTIPLIER;
    let jitterMs = DEFAULT_JITTER_MS;
    let readyPollInterval = DEFAULT_READY_POLL_MS;
    let readyJitterMs = DEFAULT_READY_JITTER_MS;
    let pollStatuses = ["pending", "ready"];
    let lastRenderedPhase = "unknown";
    let terminatingAttempts = 0;
    let restartAfterTerminate = false;

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
        const canCreate = ["missing", "landed"].includes(status);
        const canMutate = ["pending", "ready"].includes(status);
        const canTerminate = ["pending", "ready", "failed", "unknown"].includes(status);

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
            terminate.classList.toggle("d-none", !canTerminate);
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

    function expiresCountDown(time) {
        // Generates a countdown element, which automatically updates every second until the time is reached, if the object is still in the html
        const countdown = document.createElement("span");
        time = new Date(time).getTime();
        function updateCountdown() {
            const now = new Date().getTime();
            const distance = time - now;

            if (distance < 0) {
                countdown.textContent = "Expired";
                return;
            }

            const minutes = Math.floor(distance / (1000 * 60)).toString();
            const seconds = Math.floor((distance % (1000 * 60)) / 1000).toString().padStart(2, '0');
            countdown.textContent = minutes + "m " + seconds + "s";

            // Schedule the next update
            setTimeout(updateCountdown, 1000);
        }

        updateCountdown();
        return countdown;
    }

    function renderConnections(payload) {
        const alert = document.getElementById("flight-ops-alert");
        if (!alert) {
            return;
        }

        const lines = [];
        if (payload.expires_at) {
            // Convert expires_at to a countdown timer
            alert.append(document.createElement("br"));
            alert.append(document.createTextNode("Expires:"));
            alert.append(document.createElement("br"));
            const countdown = expiresCountDown(payload.expires_at);
            alert.append(countdown);
        }

        if (payload.connection_strings && payload.connection_strings.length) {
            const heading = document.createElement("div");
            heading.classList.add("mt-2", "font-weight-bold");
            heading.textContent = "Connection details:";
            alert.append(heading);

            const list = document.createElement("div");
            payload.connection_strings.forEach((entry) => {
                appendConnectionLine(list, entry);
            });
            alert.append(list);
        }
    }

    function computeNextPollDelay(phase) {
        if (phase === "ready") {
            return readyPollInterval + Math.floor(Math.random() * readyJitterMs);
        }
        const jitter = Math.floor(Math.random() * jitterMs);
        return Math.min(maxPollInterval, currentPollInterval + jitter);
    }

    function scheduleNextPoll(phase) {
        stopPolling();
        pollTimer = setTimeout(async function () {
            await refreshStatus();
        }, computeNextPollDelay(phase));
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
        const flightName = payload && payload.flight_name ? payload.flight_name : "none";
        let phase = payload && payload.status ? payload.status : "unknown";
        let message = "Status: " + phase; //  + ", Flight: " + flightName

        let type = "alert-info";
        if (phase === "ready") {
            type = "alert-success";
        } else if (phase === "pending") {
            type = "alert-warning";
        } else if (phase === "failed") {
            type = "alert-danger";
        } else if (phase === "unknown") {
            type = "alert-warning";
        }

        // Map phase to a better message
        if (phase === "missing") {
            message = "No challenge instance found. Start challenge to get started.";
        } else if (phase === "unknown") {
            message = "Loading instance status...";
        } else if (phase === "pending") {
            message = "Challenge instance is being provisioned. Please wait...";
        } else if (phase === "ready") {
            message = "Challenge instance is ready!";
        } else if (phase === "failed") {
            message = "Challenge instance failed to start. Please try again.";
        } else if (phase === "landed") {
            message = "Challenge instance has been terminated.";
        }

        setAlert(message, type);
        setButtons(phase);
        renderConnections(payload || {});
        lastRenderedPhase = phase;

        const shouldPoll = pollStatuses.includes(phase);

        if (shouldPoll) {
            scheduleNextPoll(phase);
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
            const apiMessage = (body && body.error && body.error.message) || (body && body.message);

            if (response.status === 429) {
                const retryAfter = response.headers.get("Retry-After");
                const waitHint = retryAfter ? " Please wait " + retryAfter + " seconds." : "";
                throw new Error(
                    (apiMessage || "Slow down. This action was performed too quickly.") + waitHint
                );
            }
            
            throw new Error(apiMessage || ("Backend error (HTTP " + response.status + ")."));
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
                (err.message || "Unable to fetch challenge status."),
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

    // The backend keeps reporting the pre-land state for about a second after a terminate
    function beginTerminatingOverride(wasFailed) {
        terminatingAttempts = 0;
        restartAfterTerminate = wasFailed;
        stopPolling();
        setAlert("Challenge instance is shutting down...", "alert-warning");
        setButtons("terminating");
        scheduleTerminatingPoll();
    }

    function scheduleTerminatingPoll() {
        stopPolling();
        pollTimer = setTimeout(async function () {
            await pollDuringTermination();
        }, TERMINATING_POLL_MS);
    }

    async function pollDuringTermination() {
        terminatingAttempts += 1;

        let payload;
        try {
            payload = await requestStatus("GET");
        } catch (err) {
            if (terminatingAttempts >= TERMINATING_MAX_ATTEMPTS) {
                increasePollInterval();
                setAlert(err.message || "Unable to confirm shutdown status.", "alert-danger");
                scheduleNextPoll();
            } else {
                scheduleTerminatingPoll();
            }
            return;
        }

        const phase = payload && payload.status ? payload.status : "unknown";
        const confirmed = ["missing", "landed"].includes(phase);

        if (!confirmed && terminatingAttempts < TERMINATING_MAX_ATTEMPTS) {
            scheduleTerminatingPoll();
            return;
        }

        resetPollInterval();

        if (!confirmed) {
            renderStatus(payload);
            setAlert("Shutdown is taking longer than expected. Please try again.", "alert-warning");
            return;
        }

        if (restartAfterTerminate) {
            restartAfterTerminate = false;
            await runAction(null, "create");
            return;
        }

        renderStatus(payload);
    }

    async function runAction(button, action) {
        const wasFailed = lastRenderedPhase === "failed";
        toggleLoading(button, true);
        try {
            const payload = await requestStatus("POST", action);
            resetPollInterval();
            if (action === "terminate") {
                beginTerminatingOverride(wasFailed);
            } else {
                renderStatus(payload);
            }
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
                if (Number.isInteger(polling.readyIntervalMs)) {
                    readyPollInterval = polling.readyIntervalMs;
                }
                if (Number.isInteger(polling.readyJitterMs)) {
                    readyJitterMs = polling.readyJitterMs;
                }
                if (Array.isArray(polling.pollStatuses)) {
                    pollStatuses = polling.pollStatuses;
                }
            }
            resetPollInterval();
        } catch (err) {
            console.warn("Failed to load spec from backend. Using default polling configuration.", err);
            basePollInterval = DEFAULT_POLL_MS;
            maxPollInterval = DEFAULT_MAX_POLL_MS;
            backoffMultiplier = DEFAULT_BACKOFF_MULTIPLIER;
            jitterMs = DEFAULT_JITTER_MS;
            readyPollInterval = DEFAULT_READY_POLL_MS;
            readyJitterMs = DEFAULT_READY_JITTER_MS;
            pollStatuses = ["pending", "ready", "unknown"];
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
