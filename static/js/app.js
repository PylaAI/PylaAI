const NAV_ITEMS = {
    dashboard: { label: "Dashboard", icon: "dashboard" },
    queue: { label: "Brawlers", icon: "queue" },
    playstyles: { label: "Playstyles", icon: "playstyles" },
    history: { label: "History", icon: "history" },
    settings: { label: "Settings", icon: "settings" },
};

const GAMEMODE_LABELS = {
    all: "All Gamemodes",
    brawlball: "Brawl Ball",
    basketbrawl: "Basket Brawl",
    brawlball_5v5: "Brawl Ball 5v5",
    showdown: "Showdown",
    other: "Other",
};

const AUTH_ERROR_COPY = {
    MISSING_API_KEY: {
        title: "API key required",
        detail: "Generate one in Discord with /generate_key using PylaBot.",
    },
    MISSING_HWID: {
        title: "Device ID missing",
        detail: "The app could not send this device ID. Restart PylaAI and check the Python logs if it repeats.",
    },
    MISSING_BUILD_TIMESTAMP: {
        title: "Build timestamp missing",
        detail: "The app could not build a complete auth request. Restart PylaAI and check the Python logs if it repeats.",
    },
    INVALID_BUILD_TIMESTAMP: {
        title: "Build timestamp invalid",
        detail: "Check that your system clock is correct, then try again.",
    },
    MISSING_BUILD_SIGNATURE: {
        title: "Build signature missing",
        detail: "The app could not sign the auth request. Restart PylaAI and check the Python logs if it repeats.",
    },
    INVALID_API_KEY: {
        title: "API key not found",
        detail: "Generate a fresh key with /generate_key using PylaBot, then paste the full key here.",
    },
    IP_MISMATCH: {
        title: "IP address changed",
        detail: "Refresh your API key in Discord so it can bind to your current IP.",
    },
    HWID_MISMATCH: {
        title: "Device mismatch",
        detail: "Refresh your API key in Discord from this device.",
    },
    VERSION_TOO_NEW: {
        title: "Version is too new for this key",
        detail: "Refresh your API key in Discord or use a version allowed by this key.",
    },
    INVALID_BUILD_SIGNATURE: {
        title: "App build could not be verified",
        detail: "This usually means the local build and auth server secrets do not match.",
    },
    SIGNATURE_EXPIRED: {
        title: "Auth request expired",
        detail: "Check that your system clock is correct, then try again.",
    },
    AUTH_SERVER_UNREACHABLE: {
        title: "Auth server unreachable",
        detail: "Check your internet connection and try again.",
    },
    INVALID_AUTH_RESPONSE: {
        title: "Auth server returned an invalid response",
        detail: "Try again. If it keeps happening, check the Python logs for the auth status code.",
    },
    LOGIN_CHECK_FAILED: {
        title: "Saved key check failed",
        detail: "The saved key could not be checked. Try again or generate a fresh key with /generate_key using PylaBot.",
    },
    LOGIN_FAILED: {
        title: "Login failed locally",
        detail: "The local web UI hit an error while validating the key. Check the Python logs for the traceback.",
    },
    LOGIN_REQUEST_FAILED: {
        title: "Login request failed",
        detail: "The browser could not reach the local PylaAI web UI login endpoint.",
    },
};

const INVALID_PLAYER_TAG_MESSAGE = "Player tag is incorrect. Use your Brawl Stars player tag, not your Supercell ID.";

const state = {
    bootstrap: null,
    currentView: "dashboard",
    selectedBrawler: "",
    queueTargetType: "trophies",
    brawlerSearch: "",
    playerInfo: { ok: true, player_tag: "", player_name: "", stats: {} },
    historySearch: "",
    historySort: "matches",
    historyChartRange: "recent",
    playstyleSearch: "",
    playstyleFilter: "all",
    pendingSaves: {},
    playerTagTimer: null,
    playerTagLoading: false,
    runtimePollTimer: null,
    authSubmitting: false,
};

const SETTINGS_META = {
    general: [
        { key: "player_tag", label: "Player Tag", type: "text", placeholder: "#PLAYER", help: "Used to autofill live trophies and win streaks inside the brawler editor. Use your Brawl Stars player tag, not your Supercell ID." },
        { key: "default_trophy_target", label: "Default Trophy Target", type: "number", help: "Default trophy target used when adding a new brawler to the queue." },
        { key: "run_for_minutes", label: "Run Time", type: "number", suffix: "min", help: "How long Pyla runs before cooldown logic takes over." },
        { key: "max_ips", label: "Max IPS", type: "text", help: "Processing cap. Use auto if you want Pyla to manage it." },
        { key: "used_threads", label: "Threads", type: "text", help: "Worker thread count. Auto keeps the current behavior." },
        { key: "ocr_scale_down_factor", label: "OCR Scale", type: "number", step: "0.1", help: "Scale factor used before OCR work." },
        { key: "trophies_multiplier", label: "Trophies Multiplier", type: "number", help: "Useful for custom arenas or multiplier-based modes." },
        { key: "emulator_port", label: "Emulator Port", type: "number", help: "ADB port used for the emulator instance." },
        { key: "brawl_stars_package", label: "Package Name", type: "text", help: "Android package used when restarting Brawl Stars." },
        { key: "auto_load_queue_on_startup", label: "Load Queue On Startup", type: "checkbox", help: "Load the latest saved queue when the web UI starts." },
    ],
    debug: [
        { key: "verbose_debug", label: "Verbose Debug", type: "checkbox", help: "Enable extra runtime debugging output." },
        { key: "state_finder_debug", label: "State Finder Debug", type: "checkbox", help: "Enable state finder logging output." },
        { key: "re_apply_movement", label: "Re-apply Movement", type: "checkbox", help: "Keep sending joystick movement even when the target position has not changed." },
        { key: "debug_view", label: "Debug View", type: "checkbox", help: "Show the latest bot frame in a separate low-latency window." },
        { key: "debug_view_fps", label: "Debug View FPS", type: "number", help: "Maximum FPS for the debug window. Lower this if it costs too much performance." },
        { key: "advanced_debug_visuals", label: "Advanced Debug Visuals", type: "checkbox", visibleIf: { key: "debug_view", value: true }, help: "Show hit circles, line-of-sight links, and joystick path sectors in the debug window." },
        { key: "record_debug_preview_clips", label: "Record Debug Preview As Clips", type: "checkbox", visibleIf: { key: "debug_view", value: true }, help: "Save MP4 clips of the debug preview when the player is tracked and then lost." },
    ],
    bot: [
        { key: "play_again_on_win", label: "Play Again On Win", type: "checkbox", help: "Chain another match immediately after a win." },
        { key: "minimum_movement_delay", label: "Minimum Movement Delay", type: "number", step: "0.1", help: "Lower bound between movement actions." },
        { key: "unstuck_movement_delay", label: "Unstuck Delay", type: "number", step: "0.1", help: "Delay before the unstuck routine fires." },
        { key: "unstuck_movement_hold_time", label: "Unstuck Hold Time", type: "number", step: "0.1", help: "How long the unstuck move is held." },
        { key: "perceived_tile_size", label: "Perceived Tile Size", type: "number", help: "Map tile size in pixels used by playstyle movement and wall-aware targeting." },
        { key: "centered_wall_detection", label: "Centered Wall Detection", type: "checkbox", help: "Use the close wall model on a 640x640 crop centered near the player." },
        { key: "wall_detection_confidence", label: "Wall Confidence", type: "number", step: "0.05", help: "Confidence threshold for wall detection." },
        { key: "entity_detection_confidence", label: "Entity Confidence", type: "number", step: "0.05", help: "Confidence threshold for player and enemy detections." },
        { key: "seconds_to_hold_attack_after_reaching_max", label: "Post-Max Hold Attack", type: "number", step: "0.1", help: "Extra hold time after maxing hold-attack brawlers." },
        { key: "idle_pixels_minimum", label: "Idle Pixel Threshold", type: "number", help: "Amount of gray needed to consider the game idle." },
        { key: "super_pixels_minimum", label: "Super Pixels", type: "number", help: "Yellow pixel threshold for super readiness." },
        { key: "gadget_pixels_minimum", label: "Gadget Pixels", type: "number", help: "Green pixel threshold for gadget readiness." },
        { key: "hypercharge_pixels_minimum", label: "Hypercharge Pixels", type: "number", help: "Purple pixel threshold for hypercharge readiness." },
    ],
    timers: [
        { key: "super", label: "Super Delay", min: 0.1, max: 10, step: 0.1, help: "How often Pyla checks if super is available." },
        { key: "hypercharge", label: "Hypercharge Delay", min: 0.1, max: 10, step: 0.1, help: "How often Pyla checks if hypercharge is available." },
        { key: "gadget", label: "Gadget Delay", min: 0.1, max: 10, step: 0.1, help: "How often Pyla checks gadgets." },
        { key: "wall_detection", label: "Wall Detection", min: 0.1, max: 10, step: 0.1, help: "Wall scan cadence." },
        { key: "no_detection_proceed", label: "Proceed Delay", min: 0.1, max: 10, step: 0.1, help: "Delay before pressing proceed when no detections are found." },
        { key: "state_check", label: "State Check", min: 0.1, max: 10, step: 0.1, help: "How often Pyla checks the game state." },
        { key: "idle", label: "Idle Check", min: 0.1, max: 10, step: 0.1, help: "How often idle detection runs." },
        { key: "check_if_brawl_stars_crashed", label: "Crash Check", min: 0.1, max: 10, step: 0.1, help: "How often crash recovery checks run." },
    ],
    webhook: [
        { key: "discord_id", label: "Discord ID", type: "text", help: "Your discord user ID. Required to use a discord bot or be pinged in webhooks." },
        { key: "webhook_url", label: "Webhook URL", type: "url", help: "Discord webhook endpoint used for notifications." },
        { key: "discord_bot_token", label: "Discord Bot Token", type: "password", help: "Discord bot token used for remote control commands. Requires full restart to apply." },
        { key: "ping_when_stuck", label: "Ping When Stuck", type: "checkbox", help: "Send a ping when Pyla gets stuck." },
        { key: "ping_when_target_is_reached", label: "Ping On Target", type: "checkbox", help: "Send a ping when a target finishes." },
        { key: "ping_every_x_match", label: "Ping Every X Matches", type: "number", help: "0 disables periodic match pings." },
        { key: "ping_every_x_minutes", label: "Ping Every X Minutes", type: "number", help: "0 disables periodic minute pings." },
        { key: "discord_guild_id", label: "Discord Guild ID", type: "text", help: "Discord server ID where slash commands should be synced." },
        { key: "telegram_token", label: "Telegram Bot Token", type: "password", help: "Telegram bot token used for notifications." },
        { key: "telegram_chat_id", label: "Telegram Chat ID", type: "text", help: "Telegram chat ID that should receive notifications." },
    ],
};

document.addEventListener("DOMContentLoaded", async () => {
    renderNav();
    bindShellEvents();

    try {
        await bootstrap();
    } catch (error) {
        showToast(error.message || "Unable to load the PylaAI UI.", "error");
    }
});

function renderNav() {
    const nav = document.querySelector(".nav-menu");
    if (!nav) return;

    nav.innerHTML = Object.entries(NAV_ITEMS).map(([view, item]) => `
        <button class="nav-item ${view === state.currentView ? "active" : ""}" data-view="${view}">
            <span class="nav-icon">${iconMarkup(item.icon)}</span>
            <span>${escapeHtml(item.label)}</span>
        </button>
    `).join("");
}

function bindShellEvents() {
    document.addEventListener("click", (event) => {
        const navButton = event.target.closest("[data-view]");
        if (navButton) {
            setView(navButton.dataset.view);
        }

        const lockedAction = event.target.closest(".ea-locked-action");
        if (lockedAction) {
            event.preventDefault();
            event.stopPropagation();
            showEarlyAccessModal();
        }
    });

    document.getElementById("authForm")?.addEventListener("submit", handleLogin);
    bindTooltipEvents();
}

function bindTooltipEvents() {
    const tooltip = document.getElementById("tooltip");
    if (!tooltip) return;

    document.body.addEventListener("mouseover", (event) => {
        const target = event.target.closest("[data-tooltip]");
        if (!target) {
            tooltip.classList.add("hidden");
            return;
        }

        tooltip.innerHTML = target.dataset.tooltip;
        tooltip.classList.remove("hidden");
    });

    document.body.addEventListener("mousemove", (event) => {
        if (tooltip.classList.contains("hidden")) return;
        tooltip.style.left = `${Math.min(event.clientX + 18, window.innerWidth - 320)}px`;
        tooltip.style.top = `${Math.min(event.clientY + 18, window.innerHeight - 140)}px`;
    });

    document.body.addEventListener("mouseout", (event) => {
        if (!event.target.closest("[data-tooltip]")) {
            tooltip.classList.add("hidden");
        }
    });
}

async function bootstrap() {
    const payload = await fetchJSON("/api/bootstrap");
    state.bootstrap = payload;
    state.selectedBrawler = state.selectedBrawler || payload.queue[0]?.brawler || payload.brawlers[0]?.name || "";
    syncQueueFormState();

    const playerTag = payload.settings.general.player_tag || "";
    if (playerTag) {
        const playerInfo = await fetchJSON(`/api/player-info?tag=${encodeURIComponent(playerTag)}`, {}, true);
        state.playerInfo = playerInfo?.ok
            ? playerInfo
            : { ok: false, player_tag: cleanPlayerTag(playerTag), player_name: "", stats: {}, message: playerInfo?.message || INVALID_PLAYER_TAG_MESSAGE };
    }

    updateChrome();
    renderAll();
    toggleAuthModal();
    startRuntimePolling();
}

function updateChrome() {
    const { app, auth, runtime } = state.bootstrap;
    const version = `${app.name} v${app.version}`;

    document.getElementById("sidebarVersion").textContent = version;
    document.getElementById("sidebarStatus").textContent = runtimeLabel(runtime);
    document.getElementById("runtimeStatusPill").textContent = runtimeLabel(runtime);
    document.getElementById("runtimeStatusPill").className = `badge ${runtimeBadgeClass(runtime)}`;
    document.getElementById("authStatusPill").textContent = auth.required ? (auth.authenticated ? "Authenticated" : "Login required") : "Local mode";
    document.getElementById("authStatusPill").className = `badge ${auth.required && !auth.authenticated ? "danger" : "badge-outline"}`;

    const indicator = document.getElementById("sidebarIndicator");
    indicator.className = `status-indicator ${runtime.state === "error" ? "is-danger" : runtime.is_running ? "is-running" : "is-idle"}`;

    renderNav();
}

function runtimeLabel(runtime) {
    if (runtime.state === "running") return "Running";
    if (runtime.state === "pausing") return "Pausing";
    if (runtime.state === "paused") return "Paused";
    if (runtime.state === "stopping") return "Stopping";
    if (runtime.state === "error") return "Error";
    return "Idle";
}

function runtimeBadgeClass(runtime) {
    if (runtime.state === "error") return "danger";
    if (runtime.state === "running") return "active";
    if (runtime.state === "pausing" || runtime.state === "paused") return "warning";
    if (runtime.state === "stopping") return "danger";
    return "badge-outline";
}

function toggleAuthModal() {
    const modal = document.getElementById("authModal");
    if (!modal) return;

    const auth = state.bootstrap?.auth || {};
    const shouldShow = Boolean(auth.required && !auth.authenticated);
    modal.classList.toggle("hidden", !shouldShow);

    if (shouldShow) {
        const instructions = document.getElementById("authInstructions");
        if (instructions) {
            if (!auth.early_access) {
                instructions.innerHTML = "<h1> This screen isn't supposed to appear as an api key is included. Check the logs.</h1>";
            } else {
                instructions.innerHTML = "Use <code>/generate_key</code> if you bought via Patreon, or <code>/refresh_key</code> if you bought a temporary key, with PylaBot in #commands, then paste the key here. Your key is handled by Python only and is not rendered back into the UI.";
            }
        }
        renderAuthMessage(auth, auth.code ? "error" : "info");
    } else {
        renderAuthMessage(null);
    }
}

async function handleLogin(event) {
    event.preventDefault();

    const input = document.getElementById("apiKeyInput");
    const button = document.getElementById("authSubmitBtn");

    state.authSubmitting = true;
    if (button) {
        button.disabled = true;
        button.classList.add("is-disabled");
        button.textContent = "Checking...";
    }
    renderAuthMessage({ message: "Checking your API key with the auth server." }, "info");

    let result;
    try {
        result = await fetchJSON("/api/login/validate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ api_key: input.value }),
        }, true);
    } catch (error) {
        result = {
            ok: false,
            authenticated: false,
            message: error.message || "Login request failed.",
            code: "LOGIN_REQUEST_FAILED",
        };
    } finally {
        state.authSubmitting = false;
        if (button) {
            button.disabled = false;
            button.classList.remove("is-disabled");
            button.textContent = "Unlock UI";
        }
    }

    if (!result.ok) {
        state.bootstrap.auth = {
            ...(state.bootstrap.auth || {}),
            authenticated: false,
            message: result.message || "Login failed.",
            code: result.code,
            detected_version: result.detected_version,
            max_version: result.max_version,
        };
        renderAuthMessage(result, "error");
        updateChrome();
        showToast(formatAuthToast(result), "error");
        return;
    }

    input.value = "";
    renderAuthMessage(null);
    showToast("Login successful.", "success");
    await bootstrap();
}

function setView(view) {
    state.currentView = view;
    renderNav();

    document.querySelectorAll(".view").forEach((section) => {
        section.classList.toggle("active", section.id === `view-${view}`);
    });

    document.getElementById("pageTitle").textContent = NAV_ITEMS[view].label;
    renderQueueDock();
}

function renderAll() {
    renderAlerts();
    renderDashboard();
    renderQueue();
    renderPlaystyles();
    renderHistory();
    renderSettings();
    setView(state.currentView);
}

function renderAlerts() {
    const alerts = document.getElementById("alertStack");
    const warnings = state.bootstrap.app.warnings || [];
    alerts.innerHTML = warnings.map((warning) => `<div class="alert">${escapeHtml(warning)}</div>`).join("");
}

function renderDashboard() {
    const view = document.getElementById("view-dashboard");
    const { links, queue, runtime, auth } = state.bootstrap;
    const activePlaystyle = getActivePlaystyle();
    const canStart = queue.length > 0 && !["running", "pausing", "stopping"].includes(runtime.state) && !(auth.required && !auth.authenticated);
    const isPaused = runtime.state === "paused";
    const authBlockCopy = auth.required && !auth.authenticated
        ? formatAuthToast(auth) || auth.message || "Login required before starting."
        : "";
    const statusCopy = runtime.state === "error"
        ? (runtime.last_error || "Pyla stopped with an error.")
        : runtime.state === "pausing"
            ? "Pause requested. Pyla will stop in the lobby."
            : runtime.state === "stopping"
                ? "Pyla is shutting down. This should only take a few seconds."
                : isPaused
                    ? "Pyla is paused in the lobby. Press Start to resume."
                    : canStart
                        ? "Queue is ready. Start PylaAI from here."
                        : authBlockCopy
                            ? authBlockCopy
                            : queue.length
                                ? "Resolve runtime state before starting."
                            : "Add at least one brawler to the queue before starting.";

    let runtimePanel = `
        <button id="startRuntimeBtn" class="btn btn-primary btn-huge ${canStart ? "" : "is-disabled"}">
            ${iconMarkup("play")}
            <span>Start</span>
        </button>
        <p class="runtime-note ${runtime.state === "error" ? "runtime-error" : ""}">${escapeHtml(statusCopy)}</p>
        ${!queue.length ? '<button id="goToBrawlersBtn" class="btn" style="margin-top: 12px;">Go to Brawlers</button>' : ''}
    `;

    if (["running", "pausing"].includes(runtime.state)) {
        runtimePanel = `
            <div class="runtime-live-shell">
                <h3 class="runtime-live-title">${runtime.state === "pausing" ? "PylaAI is pausing" : "PylaAI is currently running"}</h3>
                <p class="runtime-note">${escapeHtml(statusCopy)}</p>
                <div class="runtime-action-grid">
                    <button id="pauseRuntimeBtn" class="btn btn-primary btn-runtime-action ${runtime.state === "pausing" ? "is-disabled" : ""}">${iconMarkup("pause")} Pause</button>
                    <button id="stopRuntimeBtn" class="btn btn-runtime-action">${iconMarkup("stop")} Stop</button>
                </div>
            </div>
        `;
    } else if (isPaused) {
        runtimePanel = `
            <div class="runtime-live-shell">
                <h3 class="runtime-live-title">PylaAI is paused</h3>
                <p class="runtime-note">${escapeHtml(statusCopy)}</p>
                <div class="runtime-action-grid">
                    <button id="resumeRuntimeBtn" class="btn btn-primary btn-runtime-action">${iconMarkup("play")} Start</button>
                    <button id="stopRuntimeBtn" class="btn btn-runtime-action">${iconMarkup("stop")} Stop</button>
                </div>
            </div>
        `;
    }

    view.innerHTML = `
        <div class="dash-grid">
            <div class="hero-row">
                <section class="panel panel-accent start-hero">
                    <p class="eyebrow">Runtime</p>
                    ${runtimePanel}
                </section>

                <section class="panel act-ps">
                    <div class="panel-header compact-header">
                        <div>
                            <p class="ps-eyebrow">Active Playstyle</p>
                            <h3>${escapeHtml(activePlaystyle?.name || "No playstyle selected")}</h3>
                            <p class="meta">${escapeHtml(metaLine(activePlaystyle))}</p>
                        </div>
                        <button id="browsePlaystylesBtn" class="btn">Browse</button>
                    </div>
                    <p class="desc">${escapeHtml(activePlaystyle?.description || "Select a playstyle to surface its brawlers and gamemodes here.")}</p>
                    ${renderPlaystyleVisual(activePlaystyle, true)}
                </section>
            </div>

            <section class="panel support-panel">
                <div class="support-copy">
                    <div>
                        <p class="eyebrow">Community</p>
                        <h3 class="panel-title support-title">Free, open-source, and actively updated</h3>
                        <p class="support-lead">Join the Discord for support and news. Patreon is where early-access builds and upcoming versions land first.</p>
                    </div>
                </div>

                <div class="link-row support-link-row">
                    ${renderSupportLink(links.discord, "Discord", "Get help, announcements, and community discussion")}
                    ${renderSupportLink(links.patreon, "Patreon", "Support PylaAI and get early access to newer versions")}
                </div>
            </section>
        </div>
    `;

    document.getElementById("browsePlaystylesBtn")?.addEventListener("click", () => setView("playstyles"));
    document.getElementById("goToBrawlersBtn")?.addEventListener("click", () => setView("queue"));
    bindRuntimeButtons();
}

function renderSupportLink(link, title, subtitle = "") {
    return `
        <a class="hero-link" href="${escapeHtml(link.url)}" target="_blank" rel="noreferrer">
            <img src="${escapeHtml(link.icon_url)}" alt="${escapeHtml(title)}">
            <div>
                <h4>${escapeHtml(title)}</h4>
                <span>${escapeHtml(subtitle || link.label)}</span>
            </div>
        </a>
    `;
}

function cleanPlayerTag(value) {
    return String(value || "").trim().replace(/^%23/i, "").replaceAll("#", "").trim();
}

function formatPlayerTagInput(value) {
    const cleanTag = cleanPlayerTag(value);
    return cleanTag ? `#${cleanTag}` : "#";
}

function ensurePlayerTagPrefix(value) {
    const text = String(value || "").trim();
    if (!text) return "#";
    return text.startsWith("#") ? text : `#${cleanPlayerTag(text)}`;
}

function formatSettingValue(field, value) {
    if (field.key === "player_tag") {
        return formatPlayerTagInput(value);
    }
    return value ?? "";
}

function getPlayerPillState() {
    if (!state.bootstrap?.auth?.early_access) {
        return {
            className: "early-access-locked",
            title: "Early Access Required",
            detail: "Get early access to sync live stats from Brawl Stars API.",
        };
    }

    if (state.playerTagLoading) {
        return {
            className: "is-loading",
            title: "Syncing player data...",
            detail: "Checking player tag with the Brawl Stars API.",
        };
    }

    const cleanTag = cleanPlayerTag(state.playerInfo.player_tag || state.bootstrap.settings.general.player_tag || "");
    if (state.playerInfo.ok === false && cleanTag) {
        return {
            className: "has-error",
            title: "Player tag is incorrect",
            detail: "Use your Brawl Stars player tag, not your Supercell ID.",
        };
    }
    if (state.playerInfo.player_name) {
        return {
            className: "has-player",
            title: state.playerInfo.player_name,
            detail: `#${cleanTag}`,
        };
    }
    return {
        className: "",
        title: "Manual mode",
        detail: "Enter a player tag to pull live trophies and streaks.",
    };
}

function renderQueue() {
    const view = document.getElementById("view-queue");
    const selectedBrawler = state.selectedBrawler || state.bootstrap.brawlers[0]?.name || "";
    const selectedCard = state.bootstrap.brawlers.find((item) => item.name === selectedBrawler);
    const hasValidPlayerInfo = Boolean(state.playerInfo.player_tag && Object.keys(state.playerInfo.stats || {}).length);
    const playerPill = getPlayerPillState();
    const defaultTarget = Number(state.bootstrap.settings.general.default_trophy_target || 1000);
    const playOrder = state.bootstrap.settings.general.play_order || "in_order";
    const pushAllButton = !state.bootstrap?.auth?.early_access
        ? `<button id="pushAllQueueLockedBtn" class="btn btn-locked ea-locked-action" type="button">${iconMarkup("queue")} Push All to ${defaultTarget} <span class="ea-lock-icon">🔒</span></button>`
        : hasValidPlayerInfo
            ? `<button id="pushAllQueueBtn" class="btn" type="button">${iconMarkup("queue")} Push All to ${defaultTarget}</button>`
            : "";

    view.innerHTML = `
        <div class="brawlers-layout">
            <section class="panel">
                <div class="panel-header">
                    <div>
                        <p class="eyebrow">Brawler Queue</p>
                        <h3 class="panel-title">Select a brawler and add it to the run order</h3>
                    </div>
                    <div class="player-pill ${playerPill.className}">
                        ${playerPill.className === "is-loading" ? '<div class="player-pill-spinner"></div>' : ''}
                        <strong>${escapeHtml(playerPill.title)}</strong>
                        <span>${escapeHtml(playerPill.detail)}</span>
                    </div>
                </div>

                <div class="queue-toolbar">
                    <div class="queue-toolbar-fields">
                        <label class="input-group grow">
                            <span>Search Brawlers</span>
                            <input id="brawlerSearch" type="search" placeholder="Search by brawler name" value="${escapeHtml(state.brawlerSearch)}">
                        </label>
                        <label class="input-group ${!state.bootstrap?.auth?.early_access ? "disabled-early-access" : ""}">
                            <span>Player Tag ${!state.bootstrap?.auth?.early_access ? `<span class="ea-badge">Early Access</span>` : ""}</span>
                            <input id="playerTagInput" type="text" placeholder="${!state.bootstrap?.auth?.early_access ? "Locked - Early Access Only" : "#PLAYER"}" value="${!state.bootstrap?.auth?.early_access ? "" : escapeHtml(formatPlayerTagInput(state.bootstrap.settings.general.player_tag || ""))}" ${!state.bootstrap?.auth?.early_access ? "disabled" : ""}>
                        </label>
                    </div>
                    <div class="queue-toolbar-bottom">
                        <div class="toolbar-actions queue-load-actions">
                            <button id="loadQueueBtn" class="btn" type="button">${iconMarkup("import")} Load Queue</button>
                            ${pushAllButton}
                            <input id="queueFileInput" type="file" accept=".json,application/json" class="hidden">
                        </div>
                        <label class="input-group play-order-control">
                            <span>Play Order</span>
                            <select id="playOrderSelect" data-setting-section="general" data-setting-key="play_order">
                                <option value="in_order" ${playOrder === "in_order" ? "selected" : ""}>In Order</option>
                                <option value="lowest_to_highest" ${playOrder === "lowest_to_highest" ? "selected" : ""}>Lowest to Highest</option>
                                <option value="highest_to_lowest" ${playOrder === "highest_to_lowest" ? "selected" : ""}>Highest to Lowest</option>
                            </select>
                        </label>
                    </div>
                </div>

                <div id="brawlerGrid" class="grid-select">
                    ${renderBrawlerCards()}
                </div>
            </section>

            <section class="panel">
                ${selectedCard ? renderSelectedBrawlerEditor(selectedCard) : `<div class="empty-state">Choose a brawler to configure it.</div>`}
            </section>
        </div>
    `;

    bindQueueEvents();
}

function renderBrawlerCards() {
    const query = state.brawlerSearch.trim().toLowerCase();
    const filtered = state.bootstrap.brawlers.filter((item) => item.name.toLowerCase().includes(query));

    if (!filtered.length) {
        return `<div class="empty-state wide-empty">No brawlers match the current search.</div>`;
    }

    return filtered.map((item) => `
        <button class="b-cell ${item.name === state.selectedBrawler ? "active" : ""}" data-brawler="${escapeHtml(item.name)}">
            <img src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.name)}">
            <span>${escapeHtml(item.name)}</span>
        </button>
    `).join("");
}

function renderSelectedBrawlerEditor(brawler) {
    const liveStats = getLiveBrawlerStats(brawler.name);
    const existing = findExistingQueueItem(brawler.name);
    const currentType = state.queueTargetType;
    const currentTrophies = liveStats.trophies ?? existing?.trophies ?? 0;
    const currentWinStreak = liveStats.win_streak ?? existing?.win_streak ?? 0;
    const currentWins = existing?.wins ?? 0;
    const configuredDefaultTarget = Number(state.bootstrap.settings.general.default_trophy_target || 1000);
    const defaultTarget = currentType === "wins" ? Math.max(currentWins + 10, 25) : configuredDefaultTarget;
    const autoPickDefault = existing ? Boolean(existing.automatically_pick) : state.bootstrap.queue.length > 0;

    return `
        <div class="queue-editor">
            <div class="selected-brawler-top">
                <img class="brawler-detail-art" src="${escapeHtml(brawler.icon_url)}" alt="${escapeHtml(brawler.name)}">
                <div>
                    <p class="eyebrow">Selected Brawler</p>
                    <h3 class="panel-title">${escapeHtml(brawler.name)}</h3>
                    <p class="meta-line">${state.playerInfo.player_name ? `Live values synced from ${escapeHtml(state.playerInfo.player_name)}` : "Manual values are available if you do not use a player tag."}</p>
                </div>
            </div>

            <div class="seg-control">
                <button class="seg-btn ${currentType === "trophies" ? "active" : ""}" data-target-type="trophies">Target Trophies</button>
                <button class="seg-btn ${currentType === "wins" ? "active" : ""}" data-target-type="wins">Target Wins</button>
            </div>

            <div class="editor-fields">
                <label class="input-group">
                    <span>Target Amount</span>
                    <input id="queuePushUntil" type="number" min="0" value="${existing?.push_until ?? defaultTarget}">
                </label>

                ${currentType === "trophies" ? `
                    <label class="input-group">
                        <span>Current Trophies</span>
                        <input id="queueTrophies" type="number" min="0" value="${currentTrophies}">
                    </label>
                    <label class="input-group">
                        <span>Current Win Streak</span>
                        <input id="queueWinStreak" type="number" min="0" value="${currentWinStreak}">
                    </label>
                ` : `
                    <label class="input-group">
                        <span>Current Wins</span>
                        <input id="queueWins" type="number" min="0" value="${currentWins}">
                    </label>
                `}
            </div>

            <label class="check-card">
                <input id="queueAutoPick" type="checkbox" ${autoPickDefault ? "checked" : ""}>
                <span class="check-box"></span>
                <span class="check-info">
                    <strong>Automatically pick this brawler</strong>
                    <span>Enabled by default once you already have another brawler queued ahead of it.</span>
                </span>
            </label>

            <button id="saveQueueItemBtn" class="btn btn-primary w-full">${existing ? "Update Queue Entry" : "Add To Queue"}</button>
        </div>
    `;
}

function renderPlaystyles() {
    const view = document.getElementById("view-playstyles");
    const active = getActivePlaystyle();

    view.innerHTML = `
        <div class="ps-page">
            <section class="panel panel-accent playstyle-selected-shell">
                <div class="playstyle-selected-head">
                    <p class="eyebrow">Selected</p>
                </div>
                <div class="playstyle-selected-card-wrap">
                    ${renderPlaystyleShowcaseCard(active, true)}
                </div>
            </section>

            <section class="toolbar-strip">
                <div class="tb-search grow">
                    <input id="playstyleSearch" type="search" placeholder="Search by playstyle, brawler, or gamemode" value="${escapeHtml(state.playstyleSearch)}">
                </div>
                <div class="toolbar-actions">
                    <button id="importPlaystyleBtn" class="btn">${iconMarkup("import")} Import</button>
                    <input id="playstyleFileInput" type="file" accept=".pyla" class="hidden">
                </div>
            </section>

            <section class="ps-lib-wrap">
                <p class="ps-lib-title">Library</p>
                <div class="ps-library">
                    ${renderPlaystyleLibrary(active)}
                </div>
            </section>
        </div>
    `;

    bindPlaystyleEvents();
}

function renderPlaystyleLibrary(active = getActivePlaystyle()) {
    const filtered = (state.bootstrap.playstyles.items || []).filter((item) => {
        if (active && item.filename === active.filename) return false;
        return matchesPlaystyleFilters(item);
    });

    return filtered.length
        ? filtered.map((item) => renderPlaystyleCard(item)).join("")
        : `<div class="empty-state wide-empty">No playstyles match the current search or filter.</div>`;
}

function renderPlaystyleCard(item) {
    return `
        <article class="ps-card" data-activate-playstyle="${escapeHtml(item.filename)}">
            <button class="ps-delete-btn" data-delete-playstyle="${escapeHtml(item.filename)}" aria-label="Delete ${escapeHtml(item.name)}">&times;</button>
            ${renderPlaystyleShowcaseCard(item, false)}
        </article>
    `;
}

function renderPlaystyleShowcaseCard(playstyle, large = false) {
    if (!playstyle) {
        return `
            <div class="playstyle-showcase ${large ? "selected" : ""}">
                <div class="playstyle-showcase-head">
                    <h4>No playstyle selected</h4>
                    <span>No metadata</span>
                </div>
                <div class="ps-vis ${large ? "large" : ""}">
                    <div class="ps-univ">No playstyle selected</div>
                </div>
            </div>
        `;
    }

    return `
        <div class="playstyle-showcase ${large ? "selected" : ""}">
            <div class="playstyle-showcase-head">
                <h4>${escapeHtml(playstyle.name)}</h4>
                <span>${escapeHtml(metaLine(playstyle))}</span>
                <p class="playstyle-card-description">${escapeHtml(playstyle.description || "No description provided.")}</p>
            </div>
            ${renderPlaystyleVisual(playstyle, large)}
        </div>
    `;
}

function renderPlaystyleVisual(playstyle, large = false) {
    if (!playstyle) {
        return `<div class="ps-vis ${large ? "large" : ""}"><div class="ps-univ">No playstyle selected</div></div>`;
    }

    const brawlers = playstyle.brawlers || [];
    const gamemodes = playstyle.gamemodes || [];
    const showBrawlers = brawlers.length > 0 && !brawlers.includes("all");
    const showGamemodes = gamemodes.length > 0 && !gamemodes.includes("all");

    if (!showBrawlers && !showGamemodes) {
        return `<div class="ps-vis ${large ? "large" : ""}"><div class="ps-univ">Universal</div></div>`;
    }

    return `
        <div class="ps-vis ${large ? "large" : ""}">
            ${showBrawlers ? `<div class="ps-part">${renderPlaystyleBrawlerThumbs(brawlers, large)}</div>` : ""}
            ${showBrawlers && showGamemodes ? `<div class="ps-div"></div>` : ""}
            ${showGamemodes ? `<div class="ps-part">${renderPlaystyleGamemodePills(gamemodes)}</div>` : ""}
        </div>
    `;
}

function renderPlaystyleBrawlerThumbs(brawlers, large) {
    return brawlers.slice(0, 6).map((name) => {
        const entry = state.bootstrap.brawlers.find((item) => item.name.toLowerCase() === String(name).toLowerCase());
        if (!entry) {
            return `<div class="ps-m-pill">${escapeHtml(String(name))}</div>`;
        }

        return `<img class="ps-b-img ${large ? "large" : ""}" src="${escapeHtml(entry.icon_url)}" alt="${escapeHtml(entry.name)}">`;
    }).join("");
}

function renderPlaystyleGamemodePills(gamemodes) {
    return gamemodes.slice(0, 4).map((mode) => `<span class="ps-m-pill">${escapeHtml(GAMEMODE_LABELS[mode] || String(mode))}</span>`).join("");
}

function renderHistory() {
    const view = document.getElementById("view-history");
    const summary = getHistorySummary();

    view.innerHTML = `
        <section class="panel">
            <div class="panel-header history-head">
                    <div>
                        <p class="eyebrow">Match History</p>
                        <h3 class="panel-title history-total">${summary.total_matches} total matches</h3>
                        <p class="meta-line history-summary-meta">${summary.wins} wins | ${summary.losses} losses | ${formatPercent(summary.win_rate)} win rate | ${formatPercent(summary.loss_rate)} loss rate</p>
                    </div>
                <div class="toolbar-actions history-actions">
                    <div class="tb-search compact-search">
                        <input id="historySearch" type="search" placeholder="Filter by brawler" value="${escapeHtml(state.historySearch)}">
                    </div>
                    <select id="historySort" aria-label="Sort match history">
                        <option value="matches" ${state.historySort === "matches" ? "selected" : ""}>Matches</option>
                        <option value="recent" ${state.historySort === "recent" ? "selected" : ""}>Recently played</option>
                        <option value="winrate" ${state.historySort === "winrate" ? "selected" : ""}>Win Rate</option>
                        <option value="name" ${state.historySort === "name" ? "selected" : ""}>Name</option>
                    </select>
                </div>
            </div>

            <div class="hist-grid">
                ${renderHistoryGrid()}
            </div>
        </section>
    `;

    document.getElementById("historySearch")?.addEventListener("input", (event) => {
        state.historySearch = event.target.value;
        const grid = document.querySelector("#view-history .hist-grid");
        if (grid) {
            grid.innerHTML = renderHistoryGrid();
        }
    });

    document.getElementById("historySort")?.addEventListener("change", (event) => {
        state.historySort = event.target.value;
        const grid = document.querySelector("#view-history .hist-grid");
        if (grid) {
            grid.innerHTML = renderHistoryGrid();
        }
    });

    view.removeEventListener("click", handleHistoryCardClick);
    view.addEventListener("click", handleHistoryCardClick);
    view.removeEventListener("keydown", handleHistoryCardKeydown);
    view.addEventListener("keydown", handleHistoryCardKeydown);
}

function getHistorySummary() {
    const items = state.bootstrap.history.items || [];
    const wins = items.reduce((total, item) => total + Number(item.wins || 0), 0);
    const losses = items.reduce((total, item) => total + Number(item.losses || 0), 0);
    const totalMatches = wins + losses;

    return {
        total_matches: totalMatches,
        wins,
        losses,
        win_rate: totalMatches ? (wins / totalMatches) * 100 : 0,
        loss_rate: totalMatches ? (losses / totalMatches) * 100 : 0,
    };
}

function getFilteredHistoryItems() {
    return [...(state.bootstrap.history.items || [])]
        .filter((item) => item.brawler.toLowerCase().includes(state.historySearch.toLowerCase()))
        .sort(sortHistoryItems);
}

function renderHistoryGrid() {
    const items = getFilteredHistoryItems();
    return items.length
        ? items.map(renderHistoryCard).join("")
        : `<div class="empty-state wide-empty">No match history has been recorded yet.</div>`;
}

function renderHistoryCard(item) {
    const trophyDelta = Number(item.trophy_delta || 0);
    return `
        <article class="hist-card" role="button" tabindex="0" data-history-brawler="${escapeHtml(item.brawler)}">
            <div class="hist-top">
                <div class="hist-identity">
                    <img src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.brawler)}">
                    <div>
                        <h4>${escapeHtml(item.brawler)}</h4>
                        <p class="meta-line history-tracked">${item.total_matches} tracked matches</p>
                    </div>
                </div>
                <div class="hist-trophy-delta ${trophyDelta < 0 ? "negative" : "positive"}">
                    <span>${formatSignedNumber(trophyDelta)}</span>
                    <img src="/api/assets/support/trophies_icon.png" alt="Trophies">
                </div>
            </div>
            <div class="hist-stats">
                <div class="hist-stat win-stat">
                    <label>Wins</label>
                    <strong>${item.wins}</strong>
                </div>
                <div class="hist-stat loss-stat">
                    <label>Losses</label>
                    <strong>${item.losses}</strong>
                </div>
                <div class="hist-stat rate-stat win-rate-stat">
                    <label>Win%</label>
                    <strong>${formatPercent(item.win_rate)}</strong>
                </div>
                <div class="hist-stat rate-stat loss-rate-stat">
                    <label>Loss%</label>
                    <strong>${formatPercent(item.loss_rate)}</strong>
                </div>
            </div>
            <div class="hist-more">Click to see more info</div>
        </article>
    `;
}

function handleHistoryCardClick(event) {
    const card = event.target.closest("[data-history-brawler]");
    if (card) {
        openHistoryDetails(card.dataset.historyBrawler);
    }
}

function handleHistoryCardKeydown(event) {
    if (!["Enter", " "].includes(event.key)) return;
    const card = event.target.closest("[data-history-brawler]");
    if (!card) return;
    event.preventDefault();
    openHistoryDetails(card.dataset.historyBrawler);
}

function openHistoryDetails(brawlerName) {
    const item = (state.bootstrap.history.items || []).find((historyItem) => historyItem.brawler === brawlerName);
    if (!item) return;

    closeHistoryDetails();
    document.body.insertAdjacentHTML("beforeend", renderHistoryDetailOverlay(item));
    document.getElementById("historyDetailOverlay")?.addEventListener("click", (event) => {
        if (event.target === event.currentTarget) {
            closeHistoryDetails();
        }
    });
    bindHistoryChartRangeControls(item);
    scrollRecentChartToLatest();
    document.addEventListener("keydown", handleHistoryDetailKeydown);
}

function bindHistoryChartRangeControls(item) {
    document.querySelectorAll("[data-history-chart-range]").forEach((button) => {
        button.addEventListener("click", () => {
            state.historyChartRange = button.dataset.historyChartRange;
            const chartPanel = document.querySelector("#historyDetailOverlay .history-chart-panel");
            if (chartPanel) {
                chartPanel.outerHTML = renderHistoryChartPanel(item);
                bindHistoryChartRangeControls(item);
                scrollRecentChartToLatest();
            }
        });
    });
}

function scrollRecentChartToLatest() {
    if (state.historyChartRange !== "recent") return;
    requestAnimationFrame(() => {
        const scroller = document.querySelector("#historyDetailOverlay .history-chart-scroll-window");
        if (scroller) {
            scroller.scrollLeft = scroller.scrollWidth;
        }
    });
}

function closeHistoryDetails() {
    document.getElementById("historyDetailOverlay")?.remove();
    document.removeEventListener("keydown", handleHistoryDetailKeydown);
}

function handleHistoryDetailKeydown(event) {
    if (event.key === "Escape") {
        closeHistoryDetails();
    }
}

function renderHistoryDetailOverlay(item) {
    const trophyDelta = Number(item.trophy_delta || 0);
    const currentTrophies = item.current_trophies ?? "N/A";
    const peakTrophies = item.peak_trophies ?? "N/A";

    return `
        <div id="historyDetailOverlay" class="history-detail-overlay" role="dialog" aria-modal="true" aria-label="${escapeHtml(item.brawler)} match history details">
            <section class="history-detail-shell">
                <header class="history-detail-head">
                    <div class="history-detail-title">
                        <img src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.brawler)}">
                        <div>
                            <h3>${escapeHtml(item.brawler)}</h3>
                            <p class="meta-line">Last played ${escapeHtml(item.last_played || "Unknown")}</p>
                        </div>
                    </div>
                    <div class="history-detail-actions">
                        <div class="history-trophy-hero ${trophyDelta < 0 ? "negative" : "positive"}">
                            <span>${formatSignedNumber(trophyDelta)}</span>
                            <img src="/api/assets/support/trophies_icon.png" alt="Trophies">
                        </div>
                    </div>
                </header>

                <div class="history-detail-grid">
                    ${renderHistoryChartPanel(item)}

                    <aside class="history-insights-panel">
                        <div class="history-kpi-grid">
                            ${renderHistoryKpi("Current", currentTrophies)}
                            ${renderHistoryKpi("Peak", peakTrophies)}
                            ${renderHistoryKpi("Win Rate", formatPercent(item.win_rate))}
                            ${renderHistoryKpi("Best Streak", item.best_win_streak || 0)}
                        </div>
                    </aside>
                </div>

                <div class="history-detail-bottom">
                    <section class="history-recent-panel">
                        <div class="history-section-head">
                            <h4>Recent results</h4>
                        </div>
                        ${renderHistoryResultGrid(item.trophy_points || [])}
                    </section>

                    <section class="history-playstyle-panel">
                        <div class="history-section-head">
                            <h4>Most used playstyles</h4>
                        </div>
                        <div class="history-playstyle-list">
                            ${(item.playstyles || []).length ? item.playstyles.map((playstyle) => `
                                <div class="history-playstyle-row">
                                    <span>${escapeHtml(playstyle.name)}</span>
                                    <strong>${playstyle.matches}</strong>
                                </div>
                            `).join("") : `<div class="empty-state">No playstyle data available.</div>`}
                        </div>
                    </section>
                </div>
            </section>
        </div>
    `;
}

function renderHistoryChartPanel(item) {
    return `
        <section class="history-chart-panel">
            <div class="history-section-head">
                <h4>Trophy Curve</h4>
                <div class="history-chart-controls">
                    <button class="${state.historyChartRange === "recent" ? "active" : ""}" type="button" data-history-chart-range="recent">Recent</button>
                    <button class="${state.historyChartRange === "all" ? "active" : ""}" type="button" data-history-chart-range="all">All</button>
                    <strong class="history-match-count">${escapeHtml(String(item.total_matches || item.trophy_points?.length || 0))} matches</strong>
                </div>
            </div>
            ${renderTrophyChart(item.trophy_points || [])}
        </section>
    `;
}

function renderTrophyChart(points) {
    const showAll = state.historyChartRange === "all";
    const chartPoints = points;
    if (chartPoints.length < 2) {
        return `<div class="history-chart-empty">Not enough trophy data to draw a curve yet.</div>`;
    }

    const width = showAll ? 640 : Math.max(640, (chartPoints.length - 1) * 64);
    const height = 210;
    const padLeft = 34;
    const padRight = 40;
    const padY = 26;
    const values = chartPoints.map((point) => Number(point.value || 0));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(1, max - min);
    const xStep = (width - padLeft - padRight) / Math.max(1, chartPoints.length - 1);
    const coords = chartPoints.map((point, index) => {
        const value = Number(point.value || 0);
        const x = padLeft + index * xStep;
        const y = height - padY - ((value - min) / range) * (height - padY * 2);
        return { x, y, value, result: point.result, delta: point.delta, label: point.label };
    });
    const line = coords.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const area = `${padLeft},${height - padY} ${line} ${width - padRight},${height - padY}`;
    const last = coords[coords.length - 1];
    const latestLabelX = last.x;

    return `
        <div class="history-chart-wrap ${showAll ? "all" : "recent"}">
            <div class="history-chart-scroll-window">
            <svg class="history-chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Trophy evolution chart">
                <defs>
                    <linearGradient id="historyChartFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="rgba(255,42,68,0.32)" />
                        <stop offset="100%" stop-color="rgba(255,42,68,0.02)" />
                    </linearGradient>
                </defs>
                <line x1="${padLeft}" y1="${padY}" x2="${padLeft}" y2="${height - padY}" class="chart-axis" />
                <line x1="${padLeft}" y1="${height - padY}" x2="${width - padRight}" y2="${height - padY}" class="chart-axis" />
                <text x="${padLeft}" y="18" class="chart-label">${max}</text>
                <text x="${padLeft}" y="${height - 7}" class="chart-label">${min}</text>
                <text x="${latestLabelX.toFixed(1)}" y="${Math.max(18, last.y - 14).toFixed(1)}" text-anchor="middle" class="chart-label chart-latest-label">${last.value}</text>
                <polygon points="${area}" class="chart-area"></polygon>
                <polyline points="${line}" class="chart-line"></polyline>
                ${coords.map((point, index) => {
                    if (showAll && index !== 0 && index !== coords.length - 1) return "";
                    return `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="${point === last ? 5 : 3}" class="chart-dot ${point.result === "victory" ? "victory" : point.result === "defeat" ? "defeat" : "draw"}" data-tooltip="${escapeHtml(historyPointTooltip(point))}"></circle>`;
                }).join("")}
            </svg>
            </div>
            <div class="history-chart-meta">
                <span>${escapeHtml(chartPoints[0].label || "First match")}</span>
                <strong>${last.value} trophies</strong>
                <span>${escapeHtml(chartPoints[chartPoints.length - 1].label || "Latest match")}</span>
            </div>
        </div>
    `;
}

function renderHistoryKpi(label, value) {
    return `
        <div class="history-kpi">
            <label>${escapeHtml(label)}</label>
            <strong>${escapeHtml(value)}</strong>
        </div>
    `;
}

function renderHistoryResultGrid(points) {
    const tiles = points.slice(-72).reverse();
    return tiles.length
        ? `<div class="history-result-grid">${tiles.map(renderHistoryResultTile).join("")}</div>`
        : `<div class="empty-state">No recent match rows available.</div>`;
}

function renderHistoryResultTile(point) {
    const result = String(point.result || "unknown");

    return `
        <div class="history-result-tile ${escapeHtml(result)}" data-tooltip="${escapeHtml(point.label || "Unknown time")}">
            <strong>${formatSignedNumber(point.delta || 0)}</strong>
            <span>${escapeHtml(point.value ?? "N/A")}</span>
        </div>
    `;
}

function historyPointTooltip(point) {
    const delta = Number(point.delta || 0);
    const deltaClass = delta < 0 ? "negative" : "positive";
    return [
        point.label || "Unknown time",
        `<span class="tooltip-trophy-line ${deltaClass}">${formatSignedNumber(delta)} <img src="/api/assets/support/trophies_icon.png" alt=""></span>`,
        `<span class="tooltip-trophy-line total">${point.value ?? "N/A"} <img src="/api/assets/support/trophies_icon.png" alt=""></span>`,
    ].join("<br>");
}

function formatResultLabel(value) {
    return String(value || "unknown").replaceAll("_", " ");
}

function renderSettings() {
    const view = document.getElementById("view-settings");

    view.innerHTML = `
        <div class="set-grid">
            <section class="panel settings-section">
                <div class="panel-header compact-header">
                    <div>
                        <p class="eyebrow">General</p>
                        <h3 class="panel-title">Runtime and environment</h3>
                    </div>
                    <button class="btn-reset-settings" data-reset-section="general">Reset Settings</button>
                </div>
                <div class="settings-list">
                    ${SETTINGS_META.general.map((field) => renderSettingField("general", field, state.bootstrap.settings.general[field.key])).join("")}
                </div>
            </section>
 
            <section class="panel settings-section">
                <div class="panel-header compact-header">
                    <div>
                        <p class="eyebrow">Behavior</p>
                        <h3 class="panel-title">Combat and recovery</h3>
                    </div>
                    <button class="btn-reset-settings" data-reset-section="bot">Reset Settings</button>
                </div>
                <div class="settings-list">
                    ${SETTINGS_META.bot.map((field) => renderSettingField("bot", field, state.bootstrap.settings.bot[field.key])).join("")}
                </div>
            </section>
 
            <section class="panel settings-section">
                <div class="panel-header compact-header">
                    <div>
                        <p class="eyebrow">Timers</p>
                        <h3 class="panel-title">Timing controls</h3>
                    </div>
                    <button class="btn-reset-settings" data-reset-section="timers">Reset Settings</button>
                </div>
                <div class="settings-list">
                    ${SETTINGS_META.timers.map((field) => renderTimerField(field, state.bootstrap.settings.timers[field.key])).join("")}
                </div>
            </section>
 
            <section class="panel settings-section">
                <div class="panel-header compact-header">
                    <div>
                        <p class="eyebrow">Integrations</p>
                        <h3 class="panel-title">Webhook</h3>
                    </div>
                    <button class="btn-reset-settings" data-reset-section="webhook">Reset Settings</button>
                </div>
                <div class="settings-list">
                    ${SETTINGS_META.webhook.map((field) => renderSettingField("webhook", field, state.bootstrap.settings.webhook[field.key])).join("")}
                </div>
            </section>
 
            <section class="panel settings-section">
                <div class="panel-header compact-header">
                    <div>
                        <p class="eyebrow">Debug</p>
                        <h3 class="panel-title">Diagnostics</h3>
                    </div>
                    <button class="btn-reset-settings" data-reset-section="debug">Reset Settings</button>
                </div>
                <div class="settings-list">
                    ${SETTINGS_META.debug.map((field) => renderSettingField("debug", field, state.bootstrap.settings.debug[field.key])).join("")}
                </div>
            </section>
        </div>
    `;

    bindSettingsEvents();
}

function renderSettingField(section, field, value) {
    if (!shouldRenderSettingField(section, field)) {
        return "";
    }

    if (field.type === "checkbox") {
        const isEarlyAccessLocked = !state.bootstrap?.auth?.early_access && field.key === "advanced_debug_visuals";
        return `
            <label class="setting-row check-card check-card-right ${isEarlyAccessLocked ? "setting-locked ea-locked-action" : ""}">
                <span class="check-info">
                    <strong>${escapeHtml(field.label)} ${isEarlyAccessLocked ? `<span class="ea-badge-inline">Early Access</span>` : ""}</strong>
                    <span>${escapeHtml(field.help)}</span>
                </span>
                <span class="check-control">
                    <input type="checkbox" data-setting-section="${section}" data-setting-key="${field.key}" ${value && !isEarlyAccessLocked ? "checked" : ""} ${isEarlyAccessLocked ? "disabled" : ""}>
                    <span class="check-box ${isEarlyAccessLocked ? "check-box-locked" : ""}"></span>
                </span>
            </label>
        `;
    }

    if (field.type === "select") {
        return `
            <div class="setting-row">
                <div class="setting-copy">
                    <div class="setting-label">
                        <strong>${escapeHtml(field.label)}</strong>
                        <span class="tooltip-anchor" data-tooltip="${escapeHtml(field.help)}">?</span>
                    </div>
                    <p class="help-text">${escapeHtml(field.help)}</p>
                </div>
                <div class="setting-input-wrap">
                    <select data-setting-section="${section}" data-setting-key="${field.key}">
                        ${(field.options || []).map((option) => `
                            <option value="${escapeHtml(option.value)}" ${option.value === value ? "selected" : ""}>${escapeHtml(option.label)}</option>
                        `).join("")}
                    </select>
                </div>
            </div>
        `;
    }

    const isEarlyAccessLocked = !state.bootstrap?.auth?.early_access && field.key === "player_tag";
    return `
        <div class="setting-row ${isEarlyAccessLocked ? "setting-locked ea-locked-action" : ""}">
            <div class="setting-copy">
                <div class="setting-label">
                    <strong>${escapeHtml(field.label)} ${isEarlyAccessLocked ? `<span class="ea-badge-inline">Early Access</span>` : ""}</strong>
                    <span class="tooltip-anchor" data-tooltip="${escapeHtml(field.help)}">?</span>
                </div>
                <p class="help-text">${escapeHtml(field.help)}</p>
            </div>
            <div class="setting-input-wrap ${field.suffix ? "has-suffix" : ""}">
                <input data-setting-section="${section}" data-setting-key="${field.key}" type="${field.type}" step="${field.step || "1"}" placeholder="${isEarlyAccessLocked ? "Locked - Early Access Only" : escapeHtml(field.placeholder || "")}" value="${isEarlyAccessLocked ? "" : escapeHtml(formatSettingValue(field, value))}" ${isEarlyAccessLocked ? "readonly" : ""}>
                ${field.suffix ? `<span class="input-suffix">${escapeHtml(field.suffix)}</span>` : ""}
            </div>
        </div>
    `;
}

function shouldRenderSettingField(section, field) {
    if (!field.visibleIf) {
        return true;
    }

    const sectionSettings = state.bootstrap?.settings?.[section] || {};
    return sectionSettings[field.visibleIf.key] === field.visibleIf.value;
}

function renderTimerField(field, value) {
    return `
        <div class="timer-box">
            <div class="timer-header">
                <div>
                    <h5>${escapeHtml(field.label)}</h5>
                    <span>${escapeHtml(field.help)}</span>
                </div>
                <input data-setting-section="timers" data-setting-key="${field.key}" data-timer-input="${field.key}" type="number" step="${field.step}" value="${value}">
            </div>
            <div class="slider-shell">
                <span class="slider-edge">${field.min}s</span>
                <input class="slider" data-setting-section="timers" data-setting-key="${field.key}" data-timer-key="${field.key}" type="range" min="${field.min}" max="${field.max}" step="${field.step}" value="${value}">
                <span class="slider-edge">${field.max}s</span>
            </div>
        </div>
    `;
}

function renderQueueDock() {
    const dock = document.getElementById("queueDock");
    if (!dock) return;

    const visible = ["dashboard", "queue"].includes(state.currentView);
    dock.classList.toggle("hidden", !visible);
    if (!visible) return;

    const isQueueView = state.currentView === "queue";
    const hasQueueItems = state.bootstrap.queue.length > 0;
    const manageLabel = isQueueView ? "Clear Queue" : "Open Brawlers";
    const manageDisabled = isQueueView && !hasQueueItems ? "disabled" : "";

    dock.innerHTML = `
        <div class="queue-dock-head">
            <div>
                <p class="queue-title">Queue</p>
                <p class="meta-line">${state.bootstrap.queue.length ? `${state.bootstrap.queue.length} brawler${state.bootstrap.queue.length === 1 ? "" : "s"} ready` : "No brawlers queued yet."}</p>
            </div>
            <div class="dock-actions">
                <button id="queueDockManageBtn" class="btn btn-sm" ${manageDisabled}>${manageLabel}</button>
            </div>
        </div>
        ${renderQueueStrip(state.bootstrap.queue)}
    `;
    document.getElementById("queueDockManageBtn")?.addEventListener("click", () => {
        if (isQueueView) {
            clearQueue();
            return;
        }
        setView("queue");
    });
    bindQueueStripEvents();
}

function renderQueueStrip(queue) {
    if (!queue.length) {
        return `<div class="queue-empty">Build a queue from the Brawlers tab to see it here.</div>`;
    }

    return `
        <div id="queueStrip" class="queue-strip">
            ${queue.map((item, index) => `
                <article class="queue-item" draggable="true" data-queue-brawler="${escapeHtml(item.brawler)}" data-tooltip="${escapeHtml(queueTooltip(item))}">
                    <span class="queue-index">${index + 1}</span>
                    <img class="qi-img" src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.brawler)}">
                    <div class="qi-text">
                        <strong>${escapeHtml(item.brawler)}</strong>
                        <span>${escapeHtml(item.current_label)}: ${item.current_value}</span>
                        <span>${escapeHtml(item.target_label)}: ${item.push_until}</span>
                    </div>
                    <button class="qi-del" data-delete-queue="${escapeHtml(item.brawler)}" aria-label="Delete ${escapeHtml(item.brawler)}">&times;</button>
                </article>
            `).join("")}
        </div>
    `;
}

function bindRuntimeButtons() {
    document.getElementById("startRuntimeBtn")?.addEventListener("click", async () => {
        const button = document.getElementById("startRuntimeBtn");
        if (button.classList.contains("is-disabled")) return;

        const result = await fetchJSON("/api/runtime/start", { method: "POST" }, true);
        if (!result.ok) {
            if (result.auth) {
                state.bootstrap.auth = result.auth;
                toggleAuthModal();
            }
            showToast(result.code ? formatAuthToast(result) : (result.message || "Unable to start Pyla."), "error");
            return;
        }

        state.bootstrap.runtime = result.runtime;
        updateChrome();
        renderDashboard();
        renderQueueDock();
        showToast("Pyla runtime started.", "success");
    });

    document.getElementById("resumeRuntimeBtn")?.addEventListener("click", async () => {
        const result = await fetchJSON("/api/runtime/start", { method: "POST" }, true);
        if (!result.ok) {
            if (result.auth) {
                state.bootstrap.auth = result.auth;
                toggleAuthModal();
            }
            showToast(result.code ? formatAuthToast(result) : (result.message || "Unable to resume Pyla."), "error");
            return;
        }

        state.bootstrap.runtime = result.runtime;
        updateChrome();
        renderDashboard();
        renderQueueDock();
        showToast("Pyla runtime resumed.", "success");
    });

    document.getElementById("pauseRuntimeBtn")?.addEventListener("click", async () => {
        const button = document.getElementById("pauseRuntimeBtn");
        if (button?.classList.contains("is-disabled")) return;
        const result = await fetchJSON("/api/runtime/pause", { method: "POST" }, true);
        if (!result.ok) {
            showToast(result.message || "Unable to pause Pyla.", "error");
            return;
        }

        state.bootstrap.runtime = result.runtime;
        updateChrome();
        renderDashboard();
        renderQueueDock();
        showToast(result.message || "Pause requested.", "success");
    });

    document.getElementById("stopRuntimeBtn")?.addEventListener("click", async () => {
        const result = await fetchJSON("/api/runtime/stop", { method: "POST" }, true);
        if (!result.ok) {
            showToast(result.message || "Unable to stop Pyla.", "error");
            return;
        }

        state.bootstrap.runtime = result.runtime;
        updateChrome();
        renderDashboard();
        renderQueueDock();
        showToast(result.message || "Stop requested.", "success");
    });
}

function startRuntimePolling() {
    if (state.runtimePollTimer) return;
    state.runtimePollTimer = setInterval(refreshRuntimeState, 1200);
}

async function refreshRuntimeState() {
    if (!state.bootstrap) return;

    try {
        const result = await fetchJSON("/api/runtime/status", {}, true);
        if (!result.ok || !result.runtime) return;

        const prevState = state.bootstrap.runtime?.state;
        state.bootstrap.runtime = result.runtime;

        if (result.runtime.is_running) {
            await refreshRunningQueue();
            await refreshMatchHistory();
        }

        if (prevState !== result.runtime.state) {
            updateChrome();
            if (state.currentView === "dashboard") {
                renderDashboard();
                renderQueueDock();
            }
            if (result.runtime.state === "error") {
                showToast(result.runtime.last_error || "Pyla stopped with an error.", "error");
            }

            if (prevState === "running" && !result.runtime.is_running) {
                await refreshMatchHistory();
            }
        }
    } catch {
        return;
    }
}

async function refreshMatchHistory() {
    try {
        const result = await fetchJSON("/api/history", {}, true);
        if (!result || !result.items) return;

        const prevItems = state.bootstrap.history?.items || [];
        if (JSON.stringify(result.items) === JSON.stringify(prevItems)) return;

        state.bootstrap.history = result;

        if (state.currentView === "history") {
            const summary = getHistorySummary();
            const totalEl = document.querySelector("#view-history .history-total");
            const metaEl = document.querySelector("#view-history .history-summary-meta");
            if (totalEl) totalEl.textContent = `${summary.total_matches} total matches`;
            if (metaEl) metaEl.textContent = `${summary.wins} wins | ${summary.losses} losses | ${formatPercent(summary.win_rate)} win rate | ${formatPercent(summary.loss_rate)} loss rate`;

            const grid = document.querySelector("#view-history .hist-grid");
            if (grid) grid.innerHTML = renderHistoryGrid();
        }
    } catch {
        return;
    }
}

async function refreshRunningQueue() {
    const result = await fetchJSON("/api/queue", {}, true);
    if (!result.items) return;

    const nextQueue = result.items || [];
    if (JSON.stringify(nextQueue) === JSON.stringify(state.bootstrap.queue)) return;

    state.bootstrap.queue = nextQueue;
    syncQueueFormState();
    if (state.currentView === "dashboard") {
        renderDashboard();
    }
    if (state.currentView === "queue") {
        renderQueue();
    }
    renderQueueDock();
}

function bindQueueEvents() {
    document.getElementById("brawlerSearch")?.addEventListener("input", (event) => {
        state.brawlerSearch = event.target.value;
        document.getElementById("brawlerGrid").innerHTML = renderBrawlerCards();
        bindBrawlerCardEvents();
    });

    document.getElementById("playerTagInput")?.addEventListener("input", (event) => {
        event.target.value = ensurePlayerTagPrefix(event.target.value);
    });

    document.getElementById("playerTagInput")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            event.target.blur();
        }
    });

    document.getElementById("playerTagInput")?.addEventListener("blur", async (event) => {
        event.target.value = formatPlayerTagInput(event.target.value);
        await commitPlayerTagUpdate(event.target.value.trim());
    });

    document.getElementById("loadQueueBtn")?.addEventListener("click", () => {
        document.getElementById("queueFileInput")?.click();
    });

    document.getElementById("queueFileInput")?.addEventListener("change", handleQueueImport);

    document.getElementById("pushAllQueueBtn")?.addEventListener("click", pushAllToDefaultTarget);

    document.getElementById("playOrderSelect")?.addEventListener("change", async (event) => {
        await savePlayOrder(event.target.value);
    });

    bindBrawlerCardEvents();

    document.querySelectorAll("[data-target-type]").forEach((button) => {
        button.addEventListener("click", () => {
            state.queueTargetType = button.dataset.targetType;
            renderQueue();
        });
    });

    document.getElementById("saveQueueItemBtn")?.addEventListener("click", saveQueueItem);
}

function bindBrawlerCardEvents() {
    document.querySelectorAll("[data-brawler]").forEach((button) => {
        button.addEventListener("click", () => {
            state.selectedBrawler = button.dataset.brawler;
            syncQueueFormState();
            renderQueue();
        });
    });
}

function bindQueueStripEvents() {
    document.querySelectorAll("[data-delete-queue]").forEach((button) => {
        button.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();

            const brawler = button.dataset.deleteQueue;
            try {
                const result = await fetchJSON(`/api/queue/${encodeURIComponent(brawler)}`, { method: "DELETE" });
                state.bootstrap.queue = result.items;

                if (state.selectedBrawler === brawler) {
                    syncQueueFormState();
                }

                renderDashboard();
                renderQueue();
                renderQueueDock();
                showToast(`${brawler} removed from queue.`, "success");
            } catch (error) {
                showToast(error.message || `Unable to remove ${brawler} from queue.`, "error");
            }
        });
    });

    const strip = document.getElementById("queueStrip");
    if (!strip) return;

    let originalOrder = [];
    let suppressQueueItemClick = false;

    strip.querySelectorAll("[data-queue-brawler]").forEach((item) => {
        item.addEventListener("click", (event) => {
            if (event.target.closest("[data-delete-queue]")) return;
            if (suppressQueueItemClick) {
                suppressQueueItemClick = false;
                return;
            }
            selectBrawlerFromQueue(item.dataset.queueBrawler);
        });

        item.addEventListener("dragstart", () => {
            originalOrder = [...strip.querySelectorAll("[data-queue-brawler]")].map((node) => node.dataset.queueBrawler);
            suppressQueueItemClick = true;
            item.classList.add("dragging");
        });

        item.addEventListener("dragend", async () => {
            item.classList.remove("dragging");
            const order = [...strip.querySelectorAll("[data-queue-brawler]")].map((node) => node.dataset.queueBrawler);
            if (JSON.stringify(order) === JSON.stringify(originalOrder)) return;
            await persistQueueOrder(order);
        });
    });

    strip.addEventListener("dragover", (event) => {
        event.preventDefault();
        const dragged = strip.querySelector(".dragging");
        if (!dragged) return;

        const afterElement = getDragAfterElement(strip, event.clientX);
        if (!afterElement) {
            strip.appendChild(dragged);
        } else {
            strip.insertBefore(dragged, afterElement);
        }
    });
}

function getDragAfterElement(container, x) {
    const elements = [...container.querySelectorAll("[data-queue-brawler]:not(.dragging)")];

    return elements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = x - box.left - box.width / 2;

        if (offset < 0 && offset > closest.offset) {
            return { offset, element: child };
        }

        return closest;
    }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
}

async function clearQueue() {
    if (!state.bootstrap.queue.length) return;

    try {
        const result = await fetchJSON("/api/queue", { method: "DELETE" });
        state.bootstrap.queue = result.items || [];
        syncQueueFormState();
        renderDashboard();
        renderQueue();
        renderQueueDock();
        showToast("Queue cleared.", "success");
    } catch (error) {
        showToast(error.message || "Unable to clear queue.", "error");
    }
}

async function persistQueueOrder(order) {
    try {
        const result = await fetchJSON("/api/queue/reorder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order }),
        });

        state.bootstrap.queue = result.items;
        renderDashboard();
        renderQueue();
        renderQueueDock();
        showToast("Queue reordered.", "success");
    } catch (error) {
        showToast(error.message || "Unable to reorder queue.", "error");
        renderDashboard();
        renderQueue();
        renderQueueDock();
    }
}

function bindPlaystyleEvents() {
    document.getElementById("playstyleSearch")?.addEventListener("input", (event) => {
        state.playstyleSearch = event.target.value;
        const library = document.querySelector("#view-playstyles .ps-library");
        if (library) {
            library.innerHTML = renderPlaystyleLibrary();
            bindPlaystyleCardEvents();
        }
    });

    document.getElementById("importPlaystyleBtn")?.addEventListener("click", () => {
        if (!window.confirm("WARNING: Importing custom playstyles carries security risks.\nPlaystyle files (.pyla) contain Python code that runs directly on your system.\nOnly import playstyles from authors you completely trust.\n\nDo you want to proceed?")) {
            return;
        }
        document.getElementById("playstyleFileInput")?.click();
    });

    document.getElementById("playstyleFileInput")?.addEventListener("change", handlePlaystyleImport);

    bindPlaystyleCardEvents();
}

function bindPlaystyleCardEvents() {
    document.querySelectorAll("[data-delete-playstyle]").forEach((button) => {
        button.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();

            const filename = button.dataset.deletePlaystyle;
            const playstyle = state.bootstrap.playstyles.items?.find((item) => item.filename === filename);
            const label = playstyle?.name || filename;
            if (!window.confirm(`Delete "${label}"? This removes the playstyle file.`)) return;

            const result = await fetchJSON(`/api/playstyles/${encodeURIComponent(filename)}`, { method: "DELETE" });
            state.bootstrap.playstyles = result.playstyles;
            renderDashboard();
            renderPlaystyles();
            showToast(`${label} deleted.`, "success");
        });
    });

    document.querySelectorAll("[data-activate-playstyle]").forEach((button) => {
        button.addEventListener("click", async () => {
            const filename = button.dataset.activatePlaystyle;
            const result = await fetchJSON("/api/playstyles/active", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename }),
            });

            state.bootstrap.playstyles = result.playstyles;
            state.bootstrap.settings.bot.current_playstyle = filename;
            renderDashboard();
            renderPlaystyles();
            showToast("Playstyle activated.", "success");
        });
    });
}

function bindSettingsEvents() {
    document.querySelectorAll("[data-setting-section]").forEach((input) => {
        const eventName = input.type === "checkbox" || input.type === "range" ? "input" : "change";
        if (input.dataset.settingKey === "player_tag") {
            input.addEventListener("input", () => {
                input.value = ensurePlayerTagPrefix(input.value);
            });
            input.addEventListener("blur", () => {
                input.value = formatPlayerTagInput(input.value);
                scheduleAutosave(input);
            });
        }
        input.addEventListener(eventName, () => scheduleAutosave(input));
    });

    document.querySelectorAll("[data-timer-key]").forEach((slider) => {
        setSliderVisual(slider);
        const syncTimerInput = () => {
            const input = document.querySelector(`[data-timer-input="${slider.dataset.timerKey}"]`);
            if (input) {
                input.value = slider.value;
            }
            setSliderVisual(slider);
            return input;
        };
        slider.addEventListener("input", syncTimerInput);
        slider.addEventListener("input", () => scheduleAutosave(slider));
        slider.addEventListener("change", () => {
            syncTimerInput();
            scheduleAutosave(slider);
        });
    });

    document.querySelectorAll("[data-timer-input]").forEach((input) => {
        input.addEventListener("input", () => {
            const slider = document.querySelector(`[data-timer-key="${input.dataset.timerInput}"]`);
            if (slider) {
                slider.value = input.value;
                setSliderVisual(slider);
            }
            scheduleAutosave(input);
        });
    });

    document.querySelectorAll("[data-reset-section]").forEach((button) => {
        button.addEventListener("click", () => {
            const section = button.dataset.resetSection;
            resetSectionSettings(section);
        });
    });
}

function setSliderVisual(slider) {
    const min = Number(slider.min || 0);
    const max = Number(slider.max || 100);
    const value = Number(slider.value || min);
    const percent = max === min ? 0 : ((value - min) / (max - min)) * 100;
    slider.style.background = `linear-gradient(90deg, rgba(255,42,68,1) 0%, rgba(255,112,137,1) ${percent}%, rgba(255,255,255,0.08) ${percent}%, rgba(255,255,255,0.08) 100%)`;
}

async function commitPlayerTagUpdate(tag) {
    clearTimeout(state.playerTagTimer);
    const cleanNew = cleanPlayerTag(tag);
    const cleanSaved = cleanPlayerTag(state.bootstrap.settings.general.player_tag || "");
    const tagChanged = cleanNew !== cleanSaved;
    const previousLookupFailed = state.playerInfo.ok === false;

    if (!tagChanged && !previousLookupFailed) return;

    await updatePlayerTag(formatPlayerTagInput(tag));
}

async function updatePlayerTag(tag) {
    setPlayerTagLoading(true);
    try {
        const saved = await fetchJSON("/api/settings/general", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ player_tag: tag }),
        });

        state.bootstrap.settings.general = { ...state.bootstrap.settings.general, ...saved };
        await refreshPlayerInfo(tag, true);
        renderSettings();
    } finally {
        setPlayerTagLoading(false);
    }
}

function setPlayerTagLoading(isLoading) {
    state.playerTagLoading = isLoading;

    const pill = document.querySelector(".player-pill");
    if (pill) {
        const pillState = getPlayerPillState();
        pill.className = `player-pill ${pillState.className}`;
        const spinnerHtml = pillState.className === "is-loading" ? '<div class="player-pill-spinner"></div>' : '';
        pill.innerHTML = `${spinnerHtml}<strong>${escapeHtml(pillState.title)}</strong><span>${escapeHtml(pillState.detail)}</span>`;
    }

    const tagInput = document.getElementById("playerTagInput");
    if (tagInput) {
        tagInput.disabled = isLoading;
        tagInput.closest(".input-group")?.classList.toggle("is-loading-input", isLoading);
    }
}

async function refreshPlayerInfo(tag, notify) {
    const cleanTag = cleanPlayerTag(tag);
    if (!cleanTag) {
        state.playerInfo = { ok: true, player_tag: "", player_name: "", stats: {} };
        renderQueue();
        return;
    }

    const result = await fetchJSON(`/api/player-info?tag=${encodeURIComponent(formatPlayerTagInput(cleanTag))}`, {}, true);
    if (!result.ok) {
        state.playerInfo = { ok: false, player_tag: cleanTag, player_name: "", stats: {}, message: result.message || INVALID_PLAYER_TAG_MESSAGE };
        renderQueue();
        if (notify) {
            showToast(result.message || INVALID_PLAYER_TAG_MESSAGE, "error");
        }
        return;
    }

    state.playerInfo = result;
    renderQueue();
    if (notify) {
        showToast(`Player data synced for ${result.player_name || result.player_tag}.`, "success");
    }
}

async function saveQueueItem() {
    const existing = findExistingQueueItem(state.selectedBrawler);
    const liveStats = getLiveBrawlerStats(state.selectedBrawler);
    const payload = {
        brawler: state.selectedBrawler,
        type: state.queueTargetType,
        push_until: Number(document.getElementById("queuePushUntil")?.value || 0),
        trophies: Number(document.getElementById("queueTrophies")?.value || liveStats.trophies || existing?.trophies || 0),
        wins: Number(document.getElementById("queueWins")?.value || existing?.wins || 0),
        win_streak: Number(document.getElementById("queueWinStreak")?.value || liveStats.win_streak || existing?.win_streak || 0),
        automatically_pick: document.getElementById("queueAutoPick")?.checked || false,
    };

    try {
        const result = await fetchJSON("/api/queue", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        state.bootstrap.queue = result.items;
        syncQueueFormState();
        renderDashboard();
        renderQueue();
        renderQueueDock();
        showToast(`${payload.brawler} saved to queue.`, "success");
    } catch (error) {
        showToast(error.message || `Unable to save ${payload.brawler} to queue.`, "error");
    }
}

async function pushAllToDefaultTarget() {
    const result = await fetchJSON("/api/queue/push-all-to-target", { method: "POST" }, true);
    if (!result.ok) {
        showToast(result.message || "Unable to push brawlers to target.", "error");
        return;
    }

    state.bootstrap.queue = result.items || [];
    syncQueueFormState();
    renderDashboard();
    renderQueue();
    renderQueueDock();
    showToast(`${result.added_count || 0} brawler${result.added_count === 1 ? "" : "s"} below target queued.`, "success");
}

async function savePlayOrder(playOrder) {
    const saved = await fetchJSON("/api/settings/general", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ play_order: playOrder }),
    });

    state.bootstrap.settings.general = { ...state.bootstrap.settings.general, ...saved };
    if (playOrder !== "in_order") {
        const queueResult = await fetchJSON("/api/queue", {}, true);
        if (queueResult.items) {
            state.bootstrap.queue = queueResult.items;
            syncQueueFormState();
            renderDashboard();
            if (state.currentView === "queue") {
                renderQueue();
            }
            renderQueueDock();
        }
    }
    renderSettings();
}

function scheduleAutosave(input) {
    const section = input.dataset.settingSection;
    if (!section) return;

    clearTimeout(state.pendingSaves[section]);
    state.pendingSaves[section] = setTimeout(() => {
        autosaveSection(section).catch((error) => showToast(error.message || `${section} settings failed to save.`, "error"));
    }, 280);
}

async function autosaveSection(section) {
    const payload = collectSectionPayload(section);
    const result = await fetchJSON(`/api/settings/${section}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    }, true);

    if (!result || result.ok === false) {
        showToast(result?.message || `${section} settings failed to save.`, "error");
        return;
    }

    state.bootstrap.settings[section] = result;

    if (section === "general") {
        await refreshPlayerInfo(result.player_tag || "", false);
    }

    renderSettings();
}

async function resetSectionSettings(section) {
    try {
        const result = await fetchJSON(`/api/settings/${section}/reset`, {
            method: "POST"
        });

        state.bootstrap.settings[section] = result;

        if (section === "general") {
            await refreshPlayerInfo(result.player_tag || "", false);
        }

        renderSettings();
        showToast(`${section.charAt(0).toUpperCase() + section.slice(1)} settings reset to defaults.`, "success");
    } catch (error) {
        showToast(error.message || `Failed to reset ${section} settings.`, "error");
    }
}

function collectSectionPayload(section) {
    const payload = {};

    document.querySelectorAll(`[data-setting-section="${section}"]`).forEach((input) => {
        const key = input.dataset.settingKey;
        if (!key) return;
        payload[key] = input.type === "checkbox" ? input.checked : input.value;
        if (key === "player_tag") {
            payload[key] = formatPlayerTagInput(input.value);
        }
    });

    if (section === "debug" && payload.debug_view === false) {
        payload.advanced_debug_visuals = false;
        payload.record_debug_preview_clips = false;
    }

    return payload;
}

async function handlePlaystyleImport(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch("/api/playstyles/import", { method: "POST", body: formData });
    const result = await response.json();

    if (!response.ok || !result.ok) {
        showToast(result.message || "Playstyle import failed.", "error");
        return;
    }

    state.bootstrap.playstyles = result.playstyles;
    renderDashboard();
    renderPlaystyles();
    showToast(`${result.filename} imported.`, "success");
    event.target.value = "";
}

async function handleQueueImport(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch("/api/queue/import", { method: "POST", body: formData });
    const result = await response.json().catch(() => ({}));

    if (!response.ok || !result.ok) {
        showToast(result.message || "Queue import failed.", "error");
        event.target.value = "";
        return;
    }

    state.bootstrap.queue = result.items || [];
    if (state.bootstrap.queue[0]?.brawler) {
        state.selectedBrawler = state.bootstrap.queue[0].brawler;
    }

    syncQueueFormState();
    renderDashboard();
    renderQueue();
    renderQueueDock();
    showToast(`${state.bootstrap.queue.length} queue item${state.bootstrap.queue.length === 1 ? "" : "s"} loaded.`, "success");
    event.target.value = "";
}

function syncQueueFormState() {
    const existing = findExistingQueueItem(state.selectedBrawler);
    state.queueTargetType = existing?.type || state.queueTargetType || "trophies";
}

function findExistingQueueItem(brawlerName) {
    return state.bootstrap.queue.find((item) => item.brawler === brawlerName);
}

function selectBrawlerFromQueue(brawlerName) {
    const catalogEntry = state.bootstrap.brawlers.find((item) => item.name.toLowerCase() === String(brawlerName).toLowerCase());
    state.selectedBrawler = catalogEntry?.name || brawlerName;
    syncQueueFormState();
    setView("queue");
    renderQueue();
    requestAnimationFrame(() => {
        document.querySelector(`[data-brawler="${cssEscape(state.selectedBrawler)}"]`)?.scrollIntoView({ block: "center", inline: "nearest" });
    });
}

function getLiveBrawlerStats(brawlerName) {
    return state.playerInfo.stats[brawlerName] || {};
}

function getActivePlaystyle() {
    return state.bootstrap.playstyles.current || state.bootstrap.playstyles.items?.find((item) => item.is_active) || state.bootstrap.playstyles.items?.[0] || null;
}

function metaLine(item) {
    if (!item) return "No metadata";

    const parts = [];
    if (item.author) parts.push(item.author);
    if (item.date) parts.push(item.date);
    return parts.join(" | ") || "Unknown";
}

function matchesPlaystyleFilters(item) {
    const search = state.playstyleSearch.trim().toLowerCase();
    const searchParts = [
        item.name,
        item.author,
        item.description,
        ...(item.brawlers || []),
        ...((item.gamemodes || []).map((mode) => GAMEMODE_LABELS[mode] || mode)),
    ].join(" ").toLowerCase();

    const searchMatch = !search || searchParts.includes(search);
    return searchMatch;
}

function queueTooltip(item) {
    return `<strong>${escapeHtml(item.brawler)}</strong><br>${escapeHtml(item.current_label)}: ${item.current_value}<br>${escapeHtml(item.target_label)}: ${item.push_until}<br>Auto Pick: ${item.automatically_pick ? "On" : "Off"}`;
}

function renderAuthMessage(result, variant = "error") {
    const message = document.getElementById("authMessage");
    if (!message) return;

    if (!result?.message && !result?.code) {
        message.className = "auth-message hidden";
        message.innerHTML = "";
        return;
    }

    const copy = AUTH_ERROR_COPY[result.code] || {};
    const title = copy.title || (variant === "info" ? "Authentication check" : "Login failed");
    const detail = copy.detail || result.message || "Try again. If it keeps failing, check the Python logs for the auth code.";
    const meta = authMetaLine(result);

    message.className = `auth-message ${variant === "info" ? "info" : ""}`;
    message.innerHTML = `
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(detail)}</span>
        ${meta ? `<span class="meta-line">${escapeHtml(meta)}</span>` : ""}
    `;
}

function authMetaLine(result) {
    if (!result) return "";
    const parts = [];
    if (result.code) parts.push(`Code: ${result.code}`);
    if (result.detected_version) parts.push(`Detected: ${result.detected_version}`);
    if (result.max_version) parts.push(`Allowed: ${result.max_version}`);
    return parts.join(" | ");
}

function formatAuthToast(result) {
    const copy = AUTH_ERROR_COPY[result?.code];
    return copy?.title || result?.message || "Login failed.";
}

function sortHistoryItems(a, b) {
    if (state.historySort === "winrate") return b.win_rate - a.win_rate || b.total_matches - a.total_matches;
    if (state.historySort === "recent") return String(b.last_played_sort || "").localeCompare(String(a.last_played_sort || "")) || b.total_matches - a.total_matches;
    if (state.historySort === "name") return a.brawler.localeCompare(b.brawler);
    return b.total_matches - a.total_matches || b.win_rate - a.win_rate;
}

function formatPercent(value) {
    return `${Math.round(Number(value) || 0)}%`;
}

function formatSignedNumber(value) {
    const number = Math.round(Number(value) || 0);
    return `${number >= 0 ? "+" : ""}${number}`;
}

async function fetchJSON(url, options = {}, allowFailure = false) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));

    if (!response.ok && !allowFailure) {
        throw new Error(payload.message || `Request failed for ${url}`);
    }

    return payload;
}

function showToast(message, variant = "success") {
    const toast = document.getElementById("toast");
    if (!toast) return;

    toast.textContent = message;
    toast.className = `toast ${variant}`;
    toast.classList.remove("hidden");

    clearTimeout(showToast.timeoutId);
    showToast.timeoutId = setTimeout(() => toast.classList.add("hidden"), 2600);
}

function iconMarkup(name) {
    const S = `viewBox="0 0 24 24" aria-hidden="true"`;
    const icons = {
        dashboard:  `<svg ${S}><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>`,
        queue:      `<svg ${S}><path d="M3 5h.01"/><path d="M3 12h.01"/><path d="M3 19h.01"/><path d="M8 5h13"/><path d="M8 12h13"/><path d="M8 19h13"/></svg>`,
        playstyles: `<svg ${S}><rect width="18" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/></svg>`,
        history:    `<svg ${S}><path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>`,
        settings:   `<svg ${S}><path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/></svg>`,
        play:       `<svg ${S}><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/></svg>`,
        pause:      `<svg ${S}><rect x="14" y="3" width="5" height="18" rx="1"/><rect x="5" y="3" width="5" height="18" rx="1"/></svg>`,
        stop:       `<svg ${S}><rect width="18" height="18" x="3" y="3" rx="2"/></svg>`,
        import:     `<svg ${S}><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/></svg>`,
        close:      `<svg ${S}><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`,
        logs:       `<svg ${S}><path d="M12 19h8"/><path d="m4 17 6-6-6-6"/></svg>`,
        copy:       `<svg ${S}><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`,
    };

    return icons[name] || "";
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function cssEscape(value) {
    if (window.CSS?.escape) return CSS.escape(String(value));
    return String(value).replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

function showEarlyAccessModal() {
    let eaModal = document.getElementById("earlyAccessModal");
    if (!eaModal) {
        eaModal = document.createElement("div");
        eaModal.id = "earlyAccessModal";
        eaModal.className = "modal-overlay";
        eaModal.innerHTML = `
            <div class="modal">
                <div class="modal-header">
                    <p class="eyebrow" style="color: #ff9f1a; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase;">Early Access Feature</p>
                    <h3 style="font-size: 1.35rem; font-weight: 900; margin-bottom: 6px; color: white;">Unlock Premium Features</h3>
                    <p style="color: var(--text-secondary); font-size: 0.85rem; margin-top: 10px; line-height: 1.55;">This feature (such as Player Tag API integration, Push All, and Advanced Debug Visuals) requires the <strong>Pyla Early Access</strong> module.</p>
                    <p style="color: var(--text-secondary); font-size: 0.85rem; margin-top: 12px; line-height: 1.55;">Early access is obtainable on our Discord server in #how-to-get-early-access.</p>
                </div>
                <div style="margin-top: 24px; display: flex; flex-direction: column; gap: 10px;">
                    <a class="btn btn-primary w-full" href="https://discord.com/channels/1205263029269438574/1233146889843769417" target="_blank" rel="noreferrer" style="background: #ff9f1a; border-color: transparent; color: black; font-weight: 800; box-shadow: 0 8px 20px rgba(255, 159, 26, 0.25);">Get Early Access</a>
                    <button id="closeEAModalBtn" class="btn w-full" style="font-weight: 700;">Maybe Later</button>
                </div>
            </div>
        `;
        document.body.appendChild(eaModal);
        document.getElementById("closeEAModalBtn").addEventListener("click", () => {
            eaModal.classList.add("hidden");
        });
    }
    eaModal.classList.remove("hidden");
}
