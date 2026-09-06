const NAV_ITEMS = {
    dashboard: { label: "Dashboard", icon: "dashboard" },
    queue: { label: "Brawlers", icon: "queue" },
    playstyles: { label: "Playstyles", icon: "playstyles" },
    history: { label: "History", icon: "history" },
    logs: { label: "Logs", icon: "logs" },
    settings: { label: "Settings", icon: "settings" },
};

const GAMEMODE_LABELS = {
    all: "All Gamemodes",
    brawlball: "Brawl Ball",
    brawl_ball: "Brawl Ball",
    bounty: "Bounty",
    duo_showdown: "Duo Showdown",
    gem_grab: "Gem Grab",
    heist: "Heist",
    hot_zone: "Hot Zone",
    knockout: "Knockout",
    basketbrawl: "Basket Brawl",
    brawlball_5v5: "Brawl Ball 5v5",
    solo_showdown: "Solo Showdown",
    trio_showdown: "Trio Showdown",
    showdown: "Showdown",
    wipeout: "Wipeout",
    other: "Other",
};

const UI_API_TOKEN = document.querySelector('meta[name="pyla-ui-token"]')?.content || "";

const GAMEMODE_LOGOS = new Set([
    "brawlball", "bounty", "duo_showdown", "gem_grab", "heist", "hot_zone",
    "knockout", "solo_showdown", "trio_showdown", "wipeout",
]);

const INVALID_PLAYER_TAG_MESSAGE = "Player tag is incorrect. Use your Brawl Stars player tag, not your Supercell ID.";
const BRAWLER_RARITIES = {
    "Common": { order: 1, color: "#b8bec9" },
    "Rare": { order: 2, color: "#58d65c" },
    "Super Rare": { order: 3, color: "#5b8cff" },
    "Epic": { order: 4, color: "#d967ff" },
    "Mythic": { order: 5, color: "#ff6b7d" },
    "Legendary": { order: 6, color: "#ffd83d" },
    "Ultra Legendary": { order: 7, color: "#dffb45" },
    "Unknown": { order: 999, color: "#f3f4f6" },
};

function getStorageItem(key, defaultValue) {
    try {
        return localStorage.getItem(key) || defaultValue;
    } catch (e) {
        return defaultValue;
    }
}

function setStorageItem(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (e) {}
}

function getStoredISODate(key) {
    const value = getStorageItem(key, "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : "";
}

const state = {
    bootstrap: null,
    currentView: "dashboard",
    selectedBrawler: "",
    queueTargetType: "trophies",
    brawlerSearch: "",
    brawlerSort: getStorageItem("brawlerSort", "alphabetical"),
    brawlerSortDirection: getStorageItem("brawlerSortDirection", "asc"),
    showAllBrawlers: getStorageItem("showAllBrawlers", "false") === "true",
    playerInfo: { ok: true, player_tag: "", player_name: "", stats: {} },
    playerInfoCache: {},
    historySearch: "",
    historySort: ["matches", "recent", "winrate", "name"].includes(getStorageItem("historySort", "matches"))
        ? getStorageItem("historySort", "matches")
        : "matches",
    historyStartDate: getStoredISODate("historyStartDate"),
    historyEndDate: getStoredISODate("historyEndDate"),
    historyChartRange: "recent",
    activeHistoryBrawler: null,
    settingsSearch: "",
    playstyleSearch: "",
    playstyleFilter: "all",
    expandedPlaystyleDescriptions: new Set(),
    pendingSaves: {},
    playerTagTimer: null,
    playerTagLoading: false,
    brawlerScrollbarCleanup: null,
    queueScrollbarCleanup: null,
    playstyleScrollbarCleanup: null,
    profileScrollbarCleanup: null,
    mainViewScrollbarCleanup: null,
    runtimePollTimer: null,
    historyPollTimer: null,
    historyRefreshInFlight: null,
    authSubmitting: false,
    autoScrollLogs: true,
    forceScrollLogs: false,
    adbDevices: null,
    scanningAdb: false,
};

function renderSyncButton() { return ""; }

const SETTINGS_META = {
    general: [
        { key: "player_tag", label: "Player Tag", type: "text", placeholder: "#PLAYER", help: "Used to autofill live trophies and win streaks inside the brawler editor. Use your Brawl Stars player tag, not your Supercell ID." },
        { key: "default_trophy_target", label: "Default Trophy Target", type: "number", help: "Default trophy target used when adding a new brawler to the queue." },
        { key: "run_for_minutes", label: "Run Time", type: "number", suffix: "min", help: "How long Pyla runs before cooldown logic takes over." },
        { key: "interface_mode", label: "Interface Mode", type: "select", options: [{ value: "desktop", label: "Integrated window" }, { value: "browser", label: "System browser" }, { value: "headless", label: "Headless" }], help: "Choose what Pyla opens at startup. Headless opens no window or browser, but the local web UI remains available. Requires a full restart." },
        { key: "max_fps", label: "Max FPS", type: "text", help: "Processing cap. Use auto if you want Pyla to manage it." },
        { key: "used_threads", label: "Threads", type: "text", help: "Worker thread count. Auto keeps the current behavior." },
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
        { key: "state_detection_confidence", label: "State Confidence", type: "number", step: "0.05", help: "Confidence threshold used when matching UI templates and game states." },
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
        { key: "webhook_url", label: "Webhook URL", type: "url", secret: true, help: "Discord webhook endpoint used for notifications." },
        { key: "discord_bot_token", label: "Discord Bot Token", type: "password", secret: true, help: "Discord bot token used for remote control commands. Requires full restart to apply." },
        { key: "ping_when_stuck", label: "Ping When Stuck", type: "checkbox", help: "Send a ping when Pyla gets stuck." },
        { key: "ping_when_target_is_reached", label: "Ping On Target", type: "checkbox", help: "Send a ping when a target finishes." },
        { key: "ping_every_x_match", label: "Ping Every X Matches", type: "number", help: "0 disables periodic match pings." },
        { key: "ping_every_x_minutes", label: "Ping Every X Minutes", type: "number", help: "0 disables periodic minute pings." },
        { key: "discord_guild_id", label: "Discord Guild ID", type: "text", help: "Discord server ID where slash commands should be synced." },
        { key: "telegram_token", label: "Telegram Bot Token", type: "password", secret: true, help: "Telegram bot token used for notifications." },
        { key: "telegram_chat_id", label: "Telegram Chat ID", type: "text", help: "Telegram chat ID that should receive notifications." },
    ],
};

document.addEventListener("DOMContentLoaded", async () => {
    if (getStorageItem("sidebarCollapsed", "false") === "true") {
        setSidebarCollapsed(true);
    }
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
            <span class="nav-label">${escapeHtml(item.label)}</span>
        </button>
    `).join("");
    updateNavTooltips(document.body.classList.contains("sidebar-collapsed"));
}


function bindShellEvents() {
    document.addEventListener("click", (event) => {
        const navButton = event.target.closest("[data-view]");
        if (navButton) {
            setView(navButton.dataset.view);
            setSidebarOpen(false);
        }

        const lockedAction = event.target.closest(".premium-locked-action");
        if (lockedAction) {
            event.preventDefault();
            event.stopPropagation();
            showPremiumModal();
        }
    });
    document.getElementById("menuToggle")?.addEventListener("click", () => {
        if (window.innerWidth > 980) {
            setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
            return;
        }
        setSidebarOpen(!document.body.classList.contains("sidebar-open"));
    });
    document.getElementById("sidebarClose")?.addEventListener("click", () => setSidebarOpen(false));
    document.getElementById("sidebarBackdrop")?.addEventListener("click", () => setSidebarOpen(false));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) {
            setSidebarOpen(false);
            document.getElementById("menuToggle")?.focus();
        }
    });
    window.addEventListener("resize", () => {
        if (window.innerWidth > 980) setSidebarOpen(false);
    });
    window.addEventListener("focus", refreshVisibleHistory);
    document.addEventListener("visibilitychange", refreshVisibleHistory);
    bindTooltipEvents();
}

function setSidebarOpen(isOpen) {
    const open = Boolean(isOpen && window.innerWidth <= 980);
    document.body.classList.toggle("sidebar-open", open);
    const toggle = document.getElementById("menuToggle");
    toggle?.setAttribute("aria-expanded", String(open));
    toggle?.setAttribute("aria-label", open ? "Close navigation menu" : "Open navigation menu");
}

function setSidebarCollapsed(isCollapsed) {
    const collapsed = Boolean(isCollapsed);
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    setStorageItem("sidebarCollapsed", String(collapsed));
    updateNavTooltips(collapsed);
    const toggle = document.getElementById("menuToggle");
    toggle?.setAttribute("aria-expanded", String(!collapsed));
    toggle?.setAttribute("aria-label", collapsed ? "Expand navigation menu" : "Collapse navigation menu");
}

function updateNavTooltips(collapsed) {
    document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
        const item = NAV_ITEMS[button.dataset.view];
        if (!item) return;
        if (collapsed) button.setAttribute("data-tooltip", item.label);
        else button.removeAttribute("data-tooltip");
    });
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

        const lines = String(target.dataset.tooltip || "").split("\n");
        tooltip.replaceChildren();
        lines.forEach((line, index) => {
            if (index > 0) tooltip.appendChild(document.createElement("br"));
            tooltip.appendChild(document.createTextNode(line));
        });
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


async function bootstrap(cachedPayload = null) {
    const payload = cachedPayload || await fetchJSON("/api/bootstrap");
    state.bootstrap = payload;
    if (payload.settings?.general?.history_sort) {
        state.historySort = payload.settings.general.history_sort;
        setStorageItem("historySort", state.historySort);
    }
    state.selectedBrawler = state.selectedBrawler || payload.queue[0]?.brawler || payload.brawlers[0]?.name || "";
    state.playerInfo = { ok: false, player_tag: "", player_name: "", stats: {}, message: "Premium player data is unavailable in the public edition." };
    syncQueueFormState();
    updateChrome();
    renderAll();
    showPendingAnnouncements();
    startRuntimePolling();
    startHistoryPolling();
}


function updateChrome() {
    const { app } = state.bootstrap;
    document.getElementById("sidebarVersion").textContent = `${app.name} v${app.version}`;
    const discordUrl = state.bootstrap.links?.discord?.url || "#";
    document.getElementById("sidebarDiscordLink")?.setAttribute("href", discordUrl);
    document.getElementById("officialDiscordLink")?.setAttribute("href", discordUrl);
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





function setView(view) {
    state.currentView = view;
    renderNav();

    document.querySelectorAll(".view").forEach((section) => {
        section.classList.toggle("active", section.id === `view-${view}`);
    });

    document.getElementById("pageTitle").textContent = NAV_ITEMS[view].label;
    renderQueueDock();

    if (view === "logs") {
        refreshLogs();
    } else if (view === "history") {
        refreshMatchHistory();
    }

    bindMainViewScrollbar();
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
    const downloadUrl = safeExternalUrl(state.bootstrap.app.download_url);
    alerts.innerHTML = warnings.map((warning) => {
        const downloadLink = downloadUrl && String(warning).startsWith("New version available:")
            ? ` <a href="${escapeHtml(downloadUrl)}" target="_blank" rel="noopener noreferrer">Download</a>`
            : "";
        return `<div class="alert">${escapeHtml(warning)}${downloadLink}</div>`;
    }).join("");
}

function safeExternalUrl(value) {
    try {
        const parsed = new URL(String(value || ""));
        return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
    } catch (error) {
        return "";
    }
}

function getSeenAnnouncementIds() {
    try {
        const parsed = JSON.parse(getStorageItem("pylaSeenAnnouncements", "[]"));
        return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
    } catch (error) {
        return new Set();
    }
}

function showPendingAnnouncements() {
    if (document.getElementById("announcementModal")) return;
    const seen = getSeenAnnouncementIds();
    const announcement = (state.bootstrap?.announcements || []).find((item) => {
        return item && item.id != null && !seen.has(String(item.id));
    });
    if (!announcement) return;

    const linkUrl = safeExternalUrl(announcement.link_url);
    const linkLabel = String(announcement.link_label || "Learn more");
    const linkMarkup = linkUrl
        ? `<a class="btn btn-primary" href="${escapeHtml(linkUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(linkLabel)}</a>`
        : "";

    document.body.insertAdjacentHTML("beforeend", `
        <div id="announcementModal" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="announcementTitle" style="z-index: 350;">
            <section class="modal" style="max-width: 520px;">
                <header class="modal-header">
                    <p class="eyebrow">Announcement</p>
                    <h3 id="announcementTitle">${escapeHtml(announcement.title || "PylaAI announcement")}</h3>
                    <p style="margin-top: 14px; white-space: pre-wrap; line-height: 1.6;">${escapeHtml(announcement.message || "")}</p>
                </header>
                <div style="display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 10px; margin-top: 24px;">
                    ${linkMarkup}
                    <button id="dismissAnnouncementBtn" class="btn" type="button">Got it</button>
                </div>
            </section>
        </div>
    `);

    const dismiss = () => {
        seen.add(String(announcement.id));
        setStorageItem("pylaSeenAnnouncements", JSON.stringify([...seen].slice(-200)));
        document.getElementById("announcementModal")?.remove();
        showPendingAnnouncements();
    };
    document.getElementById("dismissAnnouncementBtn")?.addEventListener("click", dismiss);
}

function renderDashboard() {
    const view = document.getElementById("view-dashboard");
    const { queue, runtime } = state.bootstrap;
    const activePlaystyle = getActivePlaystyle();
    const canStart = queue.length > 0 && !["running", "pausing", "stopping"].includes(runtime.state);
    const isPaused = runtime.state === "paused";
    const statusCopy = runtime.state === "error"
        ? (runtime.last_error || "Pyla stopped with an error.")
        : runtime.state === "pausing"
            ? "Pause requested. Pyla will stop in the lobby."
            : runtime.state === "stopping"
                ? "Pyla is shutting down. This should only take a few seconds."
                : isPaused
                    ? "Pyla is paused. Press Start to resume."
                    : canStart
                        ? "Queue is ready. Start PylaAI from here."
                        : queue.length
                            ? "Resolve the current runtime state before starting."
                            : "Add at least one brawler to the queue before starting.";

    let runtimePanel = `
        <button id="startRuntimeBtn" class="btn btn-primary btn-huge ${canStart ? "" : "is-disabled"}">
            ${iconMarkup("play")}<span>Start</span>
        </button>
        <p class="runtime-note ${runtime.state === "error" ? "runtime-error" : ""}">${escapeHtml(statusCopy)}</p>
        ${!queue.length ? '<button id="goToBrawlersBtn" class="btn" style="margin-top: 12px;">Go to Brawlers</button>' : ''}
    `;

    if (runtime.state === "stopping") {
        runtimePanel = `
            <button class="btn btn-huge runtime-transition-button is-stopping" type="button" disabled aria-live="polite">
                <span class="runtime-transition-icon">${iconMarkup("stop")}</span><span>Stopping…</span>
            </button>
            <p class="runtime-note">${escapeHtml(statusCopy)}</p>`;
    } else if (["running", "pausing"].includes(runtime.state)) {
        runtimePanel = `
            <div class="runtime-live-shell">
                <h3 class="runtime-live-title">${runtime.state === "pausing" ? "PylaAI is pausing" : "PylaAI is currently running"}</h3>
                <p class="runtime-note">${escapeHtml(statusCopy)}</p>
                <div class="runtime-action-grid">
                    <button id="pauseRuntimeBtn" class="btn btn-primary btn-runtime-action ${runtime.state === "pausing" ? "runtime-transition-button is-pausing is-disabled" : ""}">${iconMarkup("pause")} Pause</button>
                    <button id="stopRuntimeBtn" class="btn btn-runtime-action">${iconMarkup("stop")} Stop</button>
                </div>
            </div>`;
    } else if (isPaused) {
        runtimePanel = `
            <div class="runtime-live-shell">
                <h3 class="runtime-live-title">PylaAI is paused</h3>
                <p class="runtime-note">${escapeHtml(statusCopy)}</p>
                <div class="runtime-action-grid">
                    <button id="resumeRuntimeBtn" class="btn btn-primary btn-runtime-action">${iconMarkup("play")} Start</button>
                    <button id="stopRuntimeBtn" class="btn btn-runtime-action">${iconMarkup("stop")} Stop</button>
                </div>
            </div>`;
    }

    const runtimeState = escapeHtml(String(runtime.state || "idle").replace(/[^a-z-]/gi, ""));
    const emulatorPort = Number(state.bootstrap.settings?.general?.emulator_port || 5037);
    view.innerHTML = `
        <div class="dash-grid">
            <div class="hero-row">
                <section class="panel panel-accent start-hero">
                    ${runtimePanel}
                    ${renderDashboardStats(runtime)}
                </section>
                <section class="panel act-ps">
                    <div class="panel-header compact-header">
                        <div>
                            <p class="ps-eyebrow">Active Playstyle</p>
                            <h3 data-i18n-skip>${escapeHtml(activePlaystyle?.name || "No playstyle selected")}</h3>
                            <p class="meta">${escapeHtml(metaLine(activePlaystyle))}</p>
                        </div>
                        <button id="browsePlaystylesBtn" class="btn">Browse</button>
                    </div>
                    <p class="desc" data-i18n-skip>${escapeHtml(activePlaystyle?.description || "Select a playstyle to preview its brawlers and gamemodes here.")}</p>
                    ${renderPlaystyleVisual(activePlaystyle, "dashboard")}
                </section>
            </div>

            <section class="panel profile-switcher-card premium-profile-preview">
                <div class="profile-switcher-heading">
                    <div class="profile-heading-copy">
                        <p class="eyebrow">Profiles</p>
                        <div class="profile-title-row"><h3 class="panel-title">One setup today, more with Premium</h3><span class="premium-badge-inline">Premium</span></div>
                    </div>
                    <a class="btn btn-sm profile-add-btn premium-cta" href="https://pyla-ai.angelfirela.dev/premium" target="_blank" rel="noreferrer">Explore Premium</a>
                </div>
                <div class="profile-list premium-profile-list">
                    <div class="profile-entry is-active">
                        <div class="profile-entry-main">
                            <span class="profile-entry-name">Public profile</span>
                            <span class="profile-entry-details"><span class="profile-runtime-status status-${runtimeState}"><span class="profile-status-dot"></span>${escapeHtml(runtimeLabel(runtime))}</span><span class="profile-port-summary">ADB ${emulatorPort}</span></span>
                        </div>
                        <span class="profile-active-label">Active</span>
                    </div>
                    <button class="profile-entry premium-profile-locked premium-locked-action" type="button">
                        <div class="profile-entry-main"><span class="profile-entry-name">Second emulator profile</span><span class="profile-entry-details">Separate queue, settings, history and runtime</span></div><span class="premium-profile-lock">Premium</span>
                    </button>
                    <button class="profile-entry premium-profile-locked premium-locked-action" type="button">
                        <div class="profile-entry-main"><span class="profile-entry-name">Additional profile</span><span class="profile-entry-details">Run independent account configurations</span></div><span class="premium-profile-lock">Premium</span>
                    </button>
                </div>
            </section>
        </div>`;

    document.getElementById("browsePlaystylesBtn")?.addEventListener("click", () => setView("playstyles"));
    document.getElementById("goToBrawlersBtn")?.addEventListener("click", () => setView("queue"));
    bindRuntimeButtons();
    updateSessionTimer();
}

function renderDashboardStats(runtime) {
    const showSessionTime = Boolean(runtime?.is_running && runtime?.session_started_at);
    if (!showSessionTime) return "";

    const currentSession = state.bootstrap.history?.session_summary;
    const summaryMatchesRuntime = currentSession?.active
        && Number(currentSession.started_at) === Number(runtime.session_started_at);
    const summary = summaryMatchesRuntime
        ? currentSession
        : { win_rate: 0, trophy_delta: 0 };
    const trophyDelta = Number(summary.trophy_delta || 0);

    return `
        <div class="dashboard-runtime-stats has-session">
            <div class="dashboard-runtime-stat session-stat">
                <span>Session Time</span>
                <strong id="dashboardSessionTime">${formatSessionDuration(runtime.session_started_at)}</strong>
            </div>
            <div class="dashboard-runtime-stat">
                <span>Session Win Rate</span>
                <strong>${formatPercent(summary.win_rate)}</strong>
            </div>
            <div class="dashboard-runtime-stat trophy-stat ${trophyDelta < 0 ? "negative" : "positive"}">
                <span>Trophies Gained</span>
                <strong>${formatSignedNumber(trophyDelta)} ${trophyIconMarkup()}</strong>
            </div>
        </div>
    `;
}

function formatSessionDuration(startedAt) {
    const elapsedSeconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(startedAt || 0)));
    const hours = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;
    return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function updateSessionTimer() {
    const timer = document.getElementById("dashboardSessionTime");
    const runtime = state.bootstrap?.runtime;
    if (!timer || !runtime?.is_running || !runtime?.session_started_at) return;
    timer.textContent = formatSessionDuration(runtime.session_started_at);
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
    if (!state.bootstrap?.auth?.premium) {
        return {
            className: "premium-locked",
            title: "Premium Required",
            detail: "Get premium to sync live stats from Brawl Stars API.",
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
    const hasValidPlayerInfo = hasLivePlayerStats();
    if (["trophies", "win_streak", "power_level"].includes(state.brawlerSort)
        && (!state.bootstrap?.auth?.premium || !hasValidPlayerInfo)) {
        state.brawlerSort = "alphabetical";
        setStorageItem("brawlerSort", state.brawlerSort);
    }
    const visibleBrawlers = getVisibleBrawlers();

    let selectedBrawler = state.selectedBrawler;
    if (selectedBrawler && !visibleBrawlers.some((item) => item.name === selectedBrawler)) {
        selectedBrawler = "";
    }
    if (!selectedBrawler && visibleBrawlers.length > 0) {
        selectedBrawler = visibleBrawlers[0].name;
    }
    state.selectedBrawler = selectedBrawler;

    const selectedCard = state.bootstrap.brawlers.find((item) => item.name === selectedBrawler);
    const playerPill = getPlayerPillState();
    const defaultTarget = Number(state.bootstrap.settings.general.default_trophy_target || 1000);
    const playOrder = state.bootstrap.settings.general.play_order || "in_order";
    const dynamicSortsLocked = !state.bootstrap?.auth?.premium;
    const targetHelp = `<span class="tooltip-anchor push-all-help" data-tooltip="Change this amount by editing Default Trophy Target in Settings." aria-label="How to change the Push All target">?</span>`;
    const pushAllButton = !state.bootstrap?.auth?.premium
        ? `<div class="push-all-control"><button id="pushAllQueueLockedBtn" class="btn btn-locked premium-locked-action" type="button">${iconMarkup("queue")} Push All to ${defaultTarget} <span class="premium-lock-icon">🔒</span></button>${targetHelp}</div>`
        : hasValidPlayerInfo
            ? `<div class="push-all-control"><button id="pushAllQueueBtn" class="btn" type="button">${iconMarkup("queue")} Push All to ${defaultTarget}</button>${targetHelp}</div>`
            : "";
    state.brawlerScrollbarCleanup?.();
    state.brawlerScrollbarCleanup = null;

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
                        ${pushAllButton}
                        <label class="input-group ${!state.bootstrap?.auth?.premium ? "disabled-premium" : ""}">
                            <span>Player Tag ${!state.bootstrap?.auth?.premium ? `<span class="premium-badge">Premium</span>` : ""}</span>
                            <input id="playerTagInput" type="text" placeholder="${!state.bootstrap?.auth?.premium ? "Locked - Premium Only" : "#PLAYER"}" value="${!state.bootstrap?.auth?.premium ? "" : escapeHtml(formatPlayerTagInput(state.bootstrap.settings.general.player_tag || ""))}" ${!state.bootstrap?.auth?.premium ? "disabled" : ""}>
                        </label>
                    </div>
                    <div class="queue-toolbar-bottom">
                        <div class="toolbar-actions brawler-sort-actions">
                            <div class="input-group brawler-sort-control">
                                <span>Sorting</span>
                                <div class="brawler-sort-row">
                                    <select id="brawlerSortSelect">
                                        <option value="alphabetical" ${state.brawlerSort === "alphabetical" ? "selected" : ""}>By name</option>
                                        <option value="rarity" ${state.brawlerSort === "rarity" ? "selected" : ""}>By rarity</option>
                                        <option value="trophies" ${state.brawlerSort === "trophies" ? "selected" : ""}>${dynamicSortsLocked ? "🔒 " : ""}By trophies</option>
                                        <option value="win_streak" ${state.brawlerSort === "win_streak" ? "selected" : ""}>${dynamicSortsLocked ? "🔒 " : ""}By win streak</option>
                                        <option value="power_level" ${state.brawlerSort === "power_level" ? "selected" : ""}>${dynamicSortsLocked ? "🔒 " : ""}By power level</option>
                                    </select>
                                    <button id="brawlerSortDirectionBtn" class="sort-direction-btn" type="button" title="${state.brawlerSortDirection === "asc" ? "Ascending — click for descending" : "Descending — click for ascending"}" aria-label="${state.brawlerSortDirection === "asc" ? "Sort descending" : "Sort ascending"}">
                                        ${state.brawlerSortDirection === "asc" ? "↑" : "↓"}
                                    </button>
                                </div>
                            </div>
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

                <div class="brawler-grid-shell">
                    <div id="brawlerGrid" class="grid-select">
                        ${renderBrawlerCards()}
                    </div>
                    <div id="brawlerGridScrollbar" class="app-scrollbar brawler-grid-scrollbar" role="scrollbar" aria-controls="brawlerGrid" aria-orientation="vertical" aria-label="Scroll brawlers" tabindex="0">
                        <div id="brawlerGridScrollbarThumb" class="app-scrollbar-thumb"></div>
                    </div>
                </div>
            </section>

            <section class="panel">
                ${selectedCard ? renderSelectedBrawlerEditor(selectedCard) : `<div class="empty-state">Choose a brawler to configure it.</div>`}
            </section>
        </div>
    `;

    bindQueueEvents();
    renderQueueDock();
}

function renderBrawlerCards() {
    const query = state.brawlerSearch.trim().toLowerCase();
    let filtered = getVisibleBrawlers();
    filtered = filtered.filter((item) => item.name.toLowerCase().includes(query));

    const direction = state.brawlerSortDirection === "desc" ? -1 : 1;
    const statSort = ["trophies", "win_streak", "power_level"].includes(state.brawlerSort);
    filtered = [...filtered].sort((left, right) => {
        let comparison = 0;
        if (state.brawlerSort === "rarity") {
            comparison = (BRAWLER_RARITIES[left.rarity]?.order ?? 999) - (BRAWLER_RARITIES[right.rarity]?.order ?? 999);
        } else if (statSort) {
            comparison = Number(getLiveBrawlerStats(left.name)?.[state.brawlerSort] ?? -1)
                - Number(getLiveBrawlerStats(right.name)?.[state.brawlerSort] ?? -1);
        } else {
            comparison = left.name.localeCompare(right.name);
        }
        return comparison === 0 ? left.name.localeCompare(right.name) : comparison * direction;
    });

    if (!filtered.length) {
        return `<div class="empty-state wide-empty">No brawlers match the current search.</div>`;
    }

    return filtered.map((item) => {
        const liveValue = statSort ? getLiveBrawlerStats(item.name)?.[state.brawlerSort] : null;
        const rarityStyle = state.brawlerSort === "rarity" ? ` style="color: ${BRAWLER_RARITIES[item.rarity]?.color || BRAWLER_RARITIES.Unknown.color}"` : "";
        const value = Number(liveValue ?? 0);
        const valueMarkup = state.brawlerSort === "trophies"
            ? `<small class="brawler-sort-value">${value}${trophyIconMarkup()}</small>`
            : state.brawlerSort === "win_streak"
                ? `<small class="brawler-sort-value">${value} WS</small>`
                : state.brawlerSort === "power_level"
                    ? `<small class="brawler-sort-value">Lvl ${value}</small>`
                    : "";
        return `
        <button class="b-cell ${item.name === state.selectedBrawler ? "active" : ""}" data-brawler="${escapeHtml(item.name)}">
            <img src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.name)}">
            <span data-i18n-skip${rarityStyle}>${escapeHtml(item.name)}</span>
            ${valueMarkup}
        </button>
    `}).join("");
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
                    <h3 class="panel-title" data-i18n-skip>${escapeHtml(brawler.name)}</h3>
                    <p class="meta-line">${state.playerInfo.player_name ? `Live values synced from ${escapeHtml(state.playerInfo.player_name)}` : "Manual values are available if you do not use a player tag."}</p>
                </div>
            </div>

            <div class="seg-control">
                <button class="seg-btn ${currentType === "trophies" ? "active" : ""}" data-target-type="trophies">Target Trophies</button>
                <button class="seg-btn ${currentType === "wins" ? "active" : ""}" data-target-type="wins">Target Wins</button>
            </div>

            <div class="editor-fields">
                ${currentType === "trophies" ? `
                    <label class="input-group">
                        <span>Current Trophies</span>
                        <input id="queueTrophies" type="number" min="0" value="${currentTrophies}">
                    </label>
                    <label class="input-group target-total-field">
                        <span>Target Total</span>
                        <input id="queuePushUntil" type="number" min="0" value="${existing?.push_until ?? defaultTarget}">
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
                    <label class="input-group target-total-field">
                        <span>Target Total</span>
                        <input id="queuePushUntil" type="number" min="0" value="${existing?.push_until ?? defaultTarget}">
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

    state.playstyleScrollbarCleanup?.();
    state.playstyleScrollbarCleanup = null;

    view.innerHTML = `
        <div class="ps-page">
            <div class="ps-workspace">
                <section class="panel panel-accent playstyle-selected-shell">
                    <div class="playstyle-selected-head">
                        <p class="eyebrow">Selected playstyle</p>
                    </div>
                    <div class="playstyle-selected-card-wrap">
                        ${renderPlaystyleShowcaseCard(active, true)}
                    </div>
                </section>

                <section class="ps-library-column">
                    <div class="toolbar-strip ps-toolbar">
                        <div>
                            <p class="eyebrow">Library</p>
                            <div class="tb-search grow">
                                <input id="playstyleSearch" type="search" placeholder="Search playstyles, brawlers, or modes" value="${escapeHtml(state.playstyleSearch)}">
                            </div>
                        </div>
                        <div class="toolbar-actions">
                            <button id="importPlaystyleBtn" class="btn">${iconMarkup("import")} Import</button>
                            <input id="playstyleFileInput" type="file" accept=".pyla" class="hidden">
                        </div>
                    </div>

                    <div class="ps-lib-wrap">
                        <div class="ps-library-shell">
                            <div id="playstyleLibrary" class="ps-library">
                                ${renderPlaystyleLibrary(active)}
                            </div>
                            <div id="playstyleLibraryScrollbar" class="app-scrollbar playstyle-library-scrollbar" role="scrollbar" aria-controls="playstyleLibrary" aria-orientation="vertical" aria-label="Scroll playstyle library" tabindex="0">
                                <div id="playstyleLibraryScrollbarThumb" class="app-scrollbar-thumb"></div>
                            </div>
                        </div>
                    </div>
                </section>
            </div>
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
    const isExpanded = state.expandedPlaystyleDescriptions.has(item.filename);
    return `
        <article class="ps-card ${isExpanded ? "description-expanded" : ""}" data-activate-playstyle="${escapeHtml(item.filename)}">
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

    const description = playstyle.description || "No description provided.";
    const canExpandDescription = !large && description.length > 110;
    const descriptionExpanded = state.expandedPlaystyleDescriptions.has(playstyle.filename);

    return `
        <div class="playstyle-showcase ${large ? "selected" : ""} ${descriptionExpanded ? "description-expanded" : ""}">
            <div class="playstyle-showcase-head">
                <h4 data-i18n-skip>${escapeHtml(playstyle.name)}</h4>
                <span>${escapeHtml(metaLine(playstyle))}</span>
                <div class="playstyle-description-wrap">
                    <p class="playstyle-card-description ${canExpandDescription ? "is-clamped" : ""} ${descriptionExpanded ? "is-expanded" : ""}" data-i18n-skip>${escapeHtml(description)}</p>
                    ${canExpandDescription ? `<p class="playstyle-description-hover" aria-hidden="true" data-i18n-skip>${escapeHtml(description)}</p>` : ""}
                </div>
                ${canExpandDescription ? `
                    <button class="playstyle-read-more" type="button" data-toggle-playstyle-description="${escapeHtml(playstyle.filename)}" aria-expanded="${descriptionExpanded}">
                        ${descriptionExpanded ? "Read less" : "Read more"}
                    </button>
                ` : ""}
            </div>
            ${renderPlaystyleVisual(playstyle, large ? "selected" : "library")}
        </div>
    `;
}

function renderPlaystyleVisual(playstyle, variant = "library") {
    const large = variant !== "library";
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
        <div class="ps-vis ${large ? "large" : ""} ${variant === "dashboard" ? "dashboard-visual" : ""}">
            ${showBrawlers ? `<div class="ps-part">${renderPlaystyleBrawlerThumbs(brawlers, large)}</div>` : ""}
            ${showBrawlers && showGamemodes ? `<div class="ps-div"></div>` : ""}
            ${showGamemodes ? `<div class="ps-part ps-mode-part">${renderPlaystyleGamemodeLogos(gamemodes, large)}</div>` : ""}
        </div>
    `;
}

function renderPlaystyleBrawlerThumbs(brawlers, large) {
    const limit = large ? 8 : 3;
    const visible = brawlers.slice(0, limit);
    const overflow = brawlers.length - visible.length;
    const items = visible.map((name) => {
        const entry = state.bootstrap.brawlers.find((item) => item.name.toLowerCase() === String(name).toLowerCase());
        if (!entry) {
            return `<div class="ps-m-pill">${escapeHtml(String(name))}</div>`;
        }

        return `<img class="ps-b-img ${large ? "large" : ""}" src="${escapeHtml(entry.icon_url)}" alt="${escapeHtml(entry.name)}">`;
    });
    if (overflow > 0) {
        items.push(renderPlaystyleOverflow(overflow, brawlers.slice(limit)));
    }
    return items.join("");
}

function renderPlaystyleGamemodeLogos(gamemodes, large) {
    const limit = large ? 6 : 2;
    const visible = gamemodes.slice(0, limit);
    const overflow = gamemodes.length - visible.length;
    const items = visible.map((rawMode) => {
        const mode = normalizeGamemodeKey(rawMode);
        const label = GAMEMODE_LABELS[mode] || String(rawMode).replaceAll("_", " ");
        if (!GAMEMODE_LOGOS.has(mode)) {
            return `<span class="ps-m-pill" data-tooltip="${escapeHtml(label)}">${escapeHtml(label)}</span>`;
        }
        return `<span class="ps-mode-logo ${large ? "large" : ""}" data-tooltip="${escapeHtml(label)}"><img src="/api/assets/support/gamemodes_logos/${escapeHtml(mode)}.webp" alt="${escapeHtml(label)}"></span>`;
    });
    if (overflow > 0) {
        items.push(renderPlaystyleOverflow(overflow, gamemodes.slice(limit).map((mode) => GAMEMODE_LABELS[normalizeGamemodeKey(mode)] || mode)));
    }
    return items.join("");
}

function normalizeGamemodeKey(value) {
    const normalized = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
    return normalized === "brawl_ball" ? "brawlball" : normalized;
}

function renderPlaystyleOverflow(count, hiddenItems) {
    const tooltip = hiddenItems.map((item) => String(item).replaceAll("_", " ")).join(", ");
    return `<span class="ps-overflow" data-tooltip="${escapeHtml(tooltip)}" aria-label="${count} more: ${escapeHtml(tooltip)}">+${count}</span>`;
}

function renderHistory() {
    const view = document.getElementById("view-history");
    const summary = getHistorySummary();

    view.innerHTML = `
        <section class="panel">
            <div class="panel-header history-head">
                <div class="history-summary-hero">
                    <div class="history-total"><strong id="historyTotalMatches">${summary.total_matches}</strong><span>matches tracked</span></div>
                    <div class="history-summary-stats">
                        <span><strong id="historyTotalWins">${summary.wins}</strong> wins</span>
                        <span><strong id="historyTotalLosses">${summary.losses}</strong> losses</span>
                        <span><strong id="historyTotalWinRate">${formatPercent(summary.win_rate)}</strong> win rate</span>
                    </div>
                </div>
                <div class="toolbar-actions history-actions">
                    <div class="history-date-picker" id="historyDatePicker">
                        <button id="historyDateTrigger" class="btn history-date-trigger" type="button" aria-expanded="false" aria-controls="historyDatePopover">
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 2v4M16 2v4M3 9h18M5 4h14a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/></svg>
                            <span>${escapeHtml(historyDateRangeLabel())}</span>
                        </button>
                        <div id="historyDatePopover" class="history-date-popover hidden">
                            <strong>Date range</strong>
                            <div class="history-date-fields" role="group" aria-label="Filter match history by date">
                                <label class="history-date-field">
                                    <span>From date</span>
                                    <input id="historyStartDate" type="date" value="${escapeHtml(state.historyStartDate)}" max="${escapeHtml(state.historyEndDate)}">
                                </label>
                                <label class="history-date-field">
                                    <span>To date</span>
                                    <input id="historyEndDate" type="date" value="${escapeHtml(state.historyEndDate)}" min="${escapeHtml(state.historyStartDate)}">
                                </label>
                            </div>
                            <span class="history-date-hint">Dates are inclusive.</span>
                            <div class="history-date-buttons">
                                <button id="historyDateClear" class="btn btn-sm" type="button">Clear</button>
                                <button id="historyDateApply" class="btn btn-sm btn-primary" type="button">Apply dates</button>
                            </div>
                        </div>
                    </div>
                    <div class="tb-search compact-search">
                        <input id="historySearch" type="search" placeholder="Filter by brawler" value="${escapeHtml(state.historySearch)}">
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <select id="historySort" aria-label="Sort match history">
                            <option value="matches" ${state.historySort === "matches" ? "selected" : ""}>Matches</option>
                            <option value="recent" ${state.historySort === "recent" ? "selected" : ""}>Recently played</option>
                            <option value="winrate" ${state.historySort === "winrate" ? "selected" : ""}>Win Rate</option>
                            <option value="name" ${state.historySort === "name" ? "selected" : ""}>Name</option>
                        </select>
                        ${renderSyncButton("general", "history_sort")}
                    </div>
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
        setStorageItem("historySort", state.historySort);
        const grid = document.querySelector("#view-history .hist-grid");
        if (grid) {
            grid.innerHTML = renderHistoryGrid();
        }
        const generalSettings = { ...state.bootstrap.settings.general, history_sort: state.historySort };
        fetchJSON("/api/settings/general", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(generalSettings),
        }, true).then(result => {
            if (result && result.ok !== false) {
                state.bootstrap.settings.general = result;
            }
        }).catch(err => console.error("Failed to save history sort preference to server:", err));
    });

    document.getElementById("historyDateTrigger")?.addEventListener("click", () => {
        const trigger = document.getElementById("historyDateTrigger");
        const popover = document.getElementById("historyDatePopover");
        if (!trigger || !popover) return;
        const willOpen = popover.classList.contains("hidden");
        popover.classList.toggle("hidden", !willOpen);
        trigger.setAttribute("aria-expanded", String(willOpen));
    });

    document.getElementById("historyDateApply")?.addEventListener("click", async () => {
        const startDate = document.getElementById("historyStartDate")?.value || "";
        const endDate = document.getElementById("historyEndDate")?.value || "";
        if (startDate && endDate && startDate > endDate) {
            showToast("The start date must be on or before the end date.", "error");
            return;
        }
        await applyHistoryDateFilter(startDate, endDate);
        closeHistoryDatePicker();
        showToast("Date filter applied.", "success");
    });

    document.getElementById("historyDateClear")?.addEventListener("click", async () => {
        const startInput = document.getElementById("historyStartDate");
        const endInput = document.getElementById("historyEndDate");
        if (startInput) startInput.value = "";
        if (endInput) endInput.value = "";
        await applyHistoryDateFilter("", "");
        closeHistoryDatePicker();
        showToast("Date filter cleared.", "success");
    });

    const startDateInput = document.getElementById("historyStartDate");
    const endDateInput = document.getElementById("historyEndDate");
    startDateInput?.addEventListener("change", () => {
        if (endDateInput) endDateInput.min = startDateInput.value;
    });
    endDateInput?.addEventListener("change", () => {
        if (startDateInput) startDateInput.max = endDateInput.value;
    });

    document.removeEventListener("click", handleHistoryDatePickerOutsideClick);
    document.addEventListener("click", handleHistoryDatePickerOutsideClick);

    view.querySelectorAll(".btn-sync-toggle").forEach((button) => {
        button.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            await toggleSettingSync(button);
        });
    });

    view.removeEventListener("click", handleHistoryCardClick);
    view.addEventListener("click", handleHistoryCardClick);
    view.removeEventListener("keydown", handleHistoryCardKeydown);
    view.addEventListener("keydown", handleHistoryCardKeydown);
}

function historyDateRangeLabel() {
    if (state.historyStartDate && state.historyEndDate) {
        return `${state.historyStartDate} – ${state.historyEndDate}`;
    }
    if (state.historyStartDate) return `≥ ${state.historyStartDate}`;
    if (state.historyEndDate) return `≤ ${state.historyEndDate}`;
    return "Date range";
}

function closeHistoryDatePicker() {
    document.getElementById("historyDatePopover")?.classList.add("hidden");
    document.getElementById("historyDateTrigger")?.setAttribute("aria-expanded", "false");
}

function handleHistoryDatePickerOutsideClick(event) {
    const picker = document.getElementById("historyDatePicker");
    if (picker && !picker.contains(event.target)) closeHistoryDatePicker();
}

async function applyHistoryDateFilter(startDate, endDate) {
    state.historyStartDate = startDate;
    state.historyEndDate = endDate;
    setStorageItem("historyStartDate", startDate);
    setStorageItem("historyEndDate", endDate);
    const triggerLabel = document.querySelector("#historyDateTrigger span");
    if (triggerLabel) triggerLabel.textContent = historyDateRangeLabel();
    closeHistoryDetails();

    if (state.historyRefreshInFlight) {
        await state.historyRefreshInFlight;
    }
    await refreshMatchHistory();
}

function getHistorySummary() {
    const items = state.bootstrap.history.items || [];
    const wins = items.reduce((total, item) => total + Number(item.wins || 0), 0);
    const losses = items.reduce((total, item) => total + Number(item.losses || 0), 0);
    const totalMatches = wins + losses;
    const serverSummary = state.bootstrap.history.summary || {};
    const hasServerSummary = ["total_matches", "wins", "losses"].every((key) =>
        Number.isFinite(Number(serverSummary[key]))
    );

    const derivedSummary = {
        total_matches: totalMatches,
        wins,
        losses,
        win_rate: totalMatches ? (wins / totalMatches) * 100 : 0,
        loss_rate: totalMatches ? (losses / totalMatches) * 100 : 0,
    };

    return hasServerSummary
        ? {
            ...derivedSummary,
            ...serverSummary,
            total_matches: Number(serverSummary.total_matches),
            wins: Number(serverSummary.wins),
            losses: Number(serverSummary.losses),
            win_rate: Number(serverSummary.win_rate ?? derivedSummary.win_rate),
            loss_rate: Number(serverSummary.loss_rate ?? derivedSummary.loss_rate),
        }
        : derivedSummary;
}

function updateHistorySummary() {
    const summary = getHistorySummary();
    const values = {
        historyTotalMatches: summary.total_matches,
        historyTotalWins: summary.wins,
        historyTotalLosses: summary.losses,
        historyTotalWinRate: formatPercent(summary.win_rate),
    };
    Object.entries(values).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    });
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
        : `<div class="empty-state wide-empty">${state.historyStartDate || state.historyEndDate
            ? "No matches were recorded in the selected date range."
            : "No match history has been recorded yet."}</div>`;
}

function renderHistoryCard(item) {
    const trophyDelta = Number(item.trophy_delta || 0);
    return `
        <article class="hist-card" role="button" tabindex="0" data-history-brawler="${escapeHtml(item.brawler)}">
            <div class="hist-top">
                <div class="hist-identity">
                    <img src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.brawler)}">
                    <div>
                        <h4 data-i18n-skip>${escapeHtml(item.brawler)}</h4>
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
    state.activeHistoryBrawler = brawlerName;
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

function updateHistoryDetails(brawlerName) {
    const item = (state.bootstrap.history.items || []).find((historyItem) => historyItem.brawler === brawlerName);
    if (!item) {
        closeHistoryDetails();
        return;
    }

    const overlay = document.getElementById("historyDetailOverlay");
    if (!overlay) return;

    const shell = overlay.querySelector(".history-detail-shell");
    if (shell) {
        shell.innerHTML = `
            <header class="history-detail-head">
                <div class="history-detail-title">
                    <img src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.brawler)}">
                    <div>
                        <h3 data-i18n-skip>${escapeHtml(item.brawler)}</h3>
                        <p class="meta-line">Last played ${escapeHtml(item.last_played || "Unknown")}</p>
                    </div>
                </div>
                <div class="history-detail-actions">
                    <div class="history-trophy-hero ${Number(item.trophy_delta || 0) < 0 ? "negative" : "positive"}">
                        <span>${formatSignedNumber(Number(item.trophy_delta || 0))}</span>
                        <img src="/api/assets/support/trophies_icon.png" alt="Trophies">
                    </div>
                </div>
            </header>

            <div class="history-detail-grid">
                ${renderHistoryChartPanel(item)}

                <aside class="history-insights-panel">
                    <div class="history-kpi-grid">
                        ${renderHistoryKpi("Current", item.current_trophies ?? "N/A")}
                        ${renderHistoryKpi("Peak", item.peak_trophies ?? "N/A")}
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
                                <span data-i18n-skip>${escapeHtml(playstyle.name)}</span>
                                <strong>${playstyle.matches}</strong>
                            </div>
                        `).join("") : `<div class="empty-state">No playstyle data available.</div>`}
                    </div>
                </section>
            </div>
        `;
        bindHistoryChartRangeControls(item);
        scrollRecentChartToLatest();
    }
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
    state.activeHistoryBrawler = null;
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
                            <h3 data-i18n-skip>${escapeHtml(item.brawler)}</h3>
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
                                    <span data-i18n-skip>${escapeHtml(playstyle.name)}</span>
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
    return [
        point.label || "Unknown time",
        `${formatSignedNumber(delta)} trophies`,
        `${point.value ?? "N/A"} trophies total`,
    ].join("\n");
}

function formatResultLabel(value) {
    return String(value || "unknown").replaceAll("_", " ");
}

function renderSettings() {
    const view = document.getElementById("view-settings");

    view.innerHTML = `
        <div class="settings-search-wrap">
            ${iconMarkup("search")}
            <input id="settingsSearch" class="settings-search" type="search" placeholder="Find a setting" aria-label="Search settings" value="${escapeHtml(state.settingsSearch || "")}">
            <span id="settingsSearchStatus" class="settings-search-status" aria-live="polite"></span>
        </div>
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
                    ${SETTINGS_META.general.map((field) => `
                        ${field.key === "auto_load_queue_on_startup" ? renderShowAllBrawlersPreference() : ""}
                        ${renderSettingField("general", field, state.bootstrap.settings.general[field.key])}
                    `).join("")}
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
    applySettingsSearch(state.settingsSearch || "");
}

function renderShowAllBrawlersPreference() {
    if (!state.bootstrap?.auth?.premium) {
        return "";
    }

    return `
        <div class="setting-row check-card check-card-right client-preference-row">
            <div class="check-info">
                <strong><label for="showAllBrawlersSetting">Show all brawlers</label></strong>
                <label for="showAllBrawlersSetting"><span>Include locked brawlers in the Brawlers tab so their values can be entered manually.</span></label>
            </div>
            <label class="check-control" for="showAllBrawlersSetting">
                <input id="showAllBrawlersSetting" type="checkbox" data-client-setting="showAllBrawlers" ${state.showAllBrawlers ? "checked" : ""}>
                <span class="check-box"></span>
            </label>
        </div>
    `;
}

function renderSettingField(section, field, value) {
    if (!shouldRenderSettingField(section, field)) {
        return "";
    }

    if (field.type === "checkbox") {
        const isPremiumLocked = !state.bootstrap?.auth?.premium && (field.key === "advanced_debug_visuals" || field.key === "recover_when_wrong_brawler_used");
        return `
            <div class="setting-row check-card check-card-right ${isPremiumLocked ? "setting-locked premium-locked-action" : ""}">
                <div class="check-info">
                    <strong style="display: flex; align-items: center; gap: 6px;">
                        <label for="chk-${section}-${field.key}" style="cursor: pointer; user-select: none;">
                            ${escapeHtml(field.label)} ${isPremiumLocked ? `<span class="premium-badge-inline">Premium</span>` : ""}
                        </label>
                        ${renderSyncButton(section, field.key)}
                    </strong>
                    <label for="chk-${section}-${field.key}" style="cursor: pointer; user-select: none; display: block;">
                        <span>${escapeHtml(field.help)}</span>
                    </label>
                </div>
                <label class="check-control" for="chk-${section}-${field.key}" style="cursor: pointer;">
                    <input id="chk-${section}-${field.key}" type="checkbox" data-setting-section="${section}" data-setting-key="${field.key}" ${value && !isPremiumLocked ? "checked" : ""} ${isPremiumLocked ? "disabled" : ""}>
                    <span class="check-box ${isPremiumLocked ? "check-box-locked" : ""}"></span>
                </label>
            </div>
        `;
    }

    if (field.type === "select") {
        return `
            <div class="setting-row ${field.emphasis ? "setting-emphasis" : ""}">
                <div class="setting-copy">
                    <div class="setting-label" style="display: flex; align-items: center; gap: 6px;">
                        <strong>${escapeHtml(field.label)}</strong>
                        <span class="tooltip-anchor" data-tooltip="${escapeHtml(field.help)}">?</span>
                        ${renderSyncButton(section, field.key)}
                    </div>
                    <p class="help-text">${escapeHtml(field.help)}</p>
                </div>
                <div class="setting-input-wrap setting-width-${field.width || "standard"}">
                    <select data-setting-section="${section}" data-setting-key="${field.key}">
                        ${(field.options || []).map((option) => `
                            <option value="${escapeHtml(option.value)}" ${option.value === value ? "selected" : ""}>${escapeHtml(option.label)}</option>
                        `).join("")}
                    </select>
                </div>
            </div>
        `;
    }

    const isPremiumLocked = !state.bootstrap?.auth?.premium && field.key === "player_tag";
    const secretStatus = state.bootstrap?.settings?.[section]?._secret_status?.[field.key];
    const configuredSecretPlaceholder = field.secret && secretStatus?.configured
        ? `Configured (${secretStatus.masked || "hidden"}) - enter a replacement`
        : field.placeholder || "";
    return `
        <div class="setting-row ${field.emphasis ? "setting-emphasis" : ""} ${isPremiumLocked ? "setting-locked premium-locked-action" : ""}">
            <div class="setting-copy">
                <div class="setting-label" style="display: flex; align-items: center; gap: 6px;">
                    <strong>${escapeHtml(field.label)} ${isPremiumLocked ? `<span class="premium-badge-inline">Premium</span>` : ""}</strong>
                    <span class="tooltip-anchor" data-tooltip="${escapeHtml(field.help)}">?</span>
                    ${renderSyncButton(section, field.key)}
                </div>
                <p class="help-text">${escapeHtml(field.help)}</p>
            </div>
            <div class="setting-input-wrap setting-width-${field.width || "standard"} ${field.suffix ? "has-suffix" : ""} ${field.secret ? "has-secret-clear" : ""}">
                <input data-setting-section="${section}" data-setting-key="${field.key}" type="${field.type}" step="${field.step || "1"}" placeholder="${isPremiumLocked ? "Locked - Premium Only" : escapeHtml(configuredSecretPlaceholder)}" value="${isPremiumLocked ? "" : escapeHtml(formatSettingValue(field, value))}" ${isPremiumLocked ? "readonly" : ""}>
                ${field.suffix ? `<span class="input-suffix">${escapeHtml(field.suffix)}</span>` : ""}
                ${field.secret ? `<button class="secret-clear-button" type="button" data-clear-secret-section="${section}" data-clear-secret-key="${field.key}" data-clear-secret-label="${escapeHtml(field.label)}" aria-label="Clear ${escapeHtml(field.label)}" title="Clear ${escapeHtml(field.label)}">${iconMarkup("trash")}</button>` : ""}
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
                    <h5 style="display: flex; align-items: center; gap: 6px;">
                        ${escapeHtml(field.label)}
                        ${renderSyncButton("timers", field.key)}
                    </h5>
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

    state.queueScrollbarCleanup?.();
    state.queueScrollbarCleanup = null;

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
                <button id="queueDockLoadBtn" class="btn btn-sm" type="button">${iconMarkup("import")} Load Queue</button>
                <button id="queueDockManageBtn" class="btn btn-sm" ${manageDisabled}>${manageLabel}</button>
            </div>
        </div>
        ${renderQueueStrip(state.bootstrap.queue)}
    `;
    document.getElementById("queueDockLoadBtn")?.addEventListener("click", () => {
        document.getElementById("queueFileInput")?.click();
    });
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
        <div class="queue-strip-shell">
            <div id="queueStrip" class="queue-strip">
                ${queue.map((item, index) => {
                const liveStats = getLiveBrawlerStats(item.brawler);
                const powerLevel = liveStats?.power_level;
                const hasPower = typeof powerLevel === "number" && powerLevel > 0;

                return `
                <article class="queue-item" draggable="true" data-queue-brawler="${escapeHtml(item.brawler)}" data-tooltip="${escapeHtml(queueTooltip(item))}">
                    <span class="queue-index">${index + 1}</span>
                    <img class="qi-img" src="${escapeHtml(item.icon_url)}" alt="${escapeHtml(item.brawler)}">
                    <div class="qi-text">
                        <strong>${escapeHtml(item.brawler)}</strong>
                        <span>${escapeHtml(item.current_label)}: ${item.current_value}</span>
                        <span>${escapeHtml(item.target_label)}: ${item.push_until}</span>
                    </div>
                    ${hasPower ? `<span class="qi-power">Power ${powerLevel}</span>` : ""}
                    <button class="qi-del" data-delete-queue="${escapeHtml(item.brawler)}" aria-label="Delete ${escapeHtml(item.brawler)}">&times;</button>
                </article>
                `;
                }).join("")}
            </div>
            <div id="queueStripScrollbar" class="app-scrollbar app-scrollbar-horizontal queue-strip-scrollbar" role="scrollbar" aria-controls="queueStrip" aria-orientation="horizontal" aria-label="Scroll queued brawlers" tabindex="0">
                <div id="queueStripScrollbarThumb" class="app-scrollbar-thumb"></div>
            </div>
        </div>
    `;
}



function bindRuntimeButtons() {
    const startOrResume = async () => {
        const result = await fetchJSON("/api/runtime/start", { method: "POST" }, true);
        if (!result.ok) {
            showToast(result.message || "Unable to start Pyla.", "error");
            return;
        }
        state.bootstrap.runtime = result.runtime;
        renderDashboard();
        renderQueueDock();
        showToast(result.message || "Pyla runtime started.", "success");
    };

    document.getElementById("startRuntimeBtn")?.addEventListener("click", async (event) => {
        if (event.currentTarget.classList.contains("is-disabled")) return;
        await startOrResume();
    });
    document.getElementById("resumeRuntimeBtn")?.addEventListener("click", startOrResume);
    document.getElementById("pauseRuntimeBtn")?.addEventListener("click", async (event) => {
        if (event.currentTarget.classList.contains("is-disabled")) return;
        const previousRuntime = state.bootstrap.runtime;
        state.bootstrap.runtime = { ...previousRuntime, state: "pausing" };
        renderDashboard();
        const result = await fetchJSON("/api/runtime/pause", { method: "POST" }, true);
        if (!result.ok) {
            state.bootstrap.runtime = previousRuntime;
            renderDashboard();
            showToast(result.message || "Unable to pause Pyla.", "error");
            return;
        }
        state.bootstrap.runtime = result.runtime;
        renderDashboard();
        renderQueueDock();
        showToast(result.message || "Pause requested.", "success");
    });
    document.getElementById("stopRuntimeBtn")?.addEventListener("click", async () => {
        const previousRuntime = state.bootstrap.runtime;
        state.bootstrap.runtime = { ...previousRuntime, state: "stopping" };
        renderDashboard();
        const result = await fetchJSON("/api/runtime/stop", { method: "POST" }, true);
        if (!result.ok) {
            state.bootstrap.runtime = previousRuntime;
            renderDashboard();
            showToast(result.message || "Unable to stop Pyla.", "error");
            return;
        }
        state.bootstrap.runtime = result.runtime;
        renderDashboard();
        renderQueueDock();
        showToast(result.message || "Stop requested.", "success");
    });
}

function startRuntimePolling() {
    if (state.runtimePollTimer) return;
    state.runtimePollTimer = setInterval(refreshRuntimeState, 1200);
}

function startHistoryPolling() {
    if (state.historyPollTimer) return;
    state.historyPollTimer = setInterval(refreshVisibleHistory, 1000);
}

function refreshVisibleHistory() {
    if (document.visibilityState !== "hidden" && state.currentView === "history") {
        refreshMatchHistory();
    }
}


async function refreshRuntimeState() {
    if (!state.bootstrap) return;
    try {
        const result = await fetchJSON("/api/runtime/status", {}, true);
        if (!result.ok || !result.runtime) return;
        const previousState = state.bootstrap.runtime?.state;
        state.bootstrap.runtime = result.runtime;
        updateSessionTimer();
        // The visible History view has its own poller so it remains live even if
        // runtime status polling fails or the selected profile is idle.
        if (result.runtime.is_running && state.currentView !== "history") await refreshMatchHistory();
        if (result.runtime.is_running) await refreshRunningQueue();
        if (previousState !== result.runtime.state) {
            renderDashboard();
            renderQueueDock();
            if (result.runtime.state === "error") showToast(result.runtime.last_error || "Pyla stopped with an error.", "error");
            if (previousState === "running" && !result.runtime.is_running) await refreshMatchHistory();
        }
        if (state.currentView === "logs") await refreshLogs();
    } catch {
        return;
    }
}

async function refreshMatchHistory() {
    if (!state.bootstrap) return;
    if (state.historyRefreshInFlight) return state.historyRefreshInFlight;

    state.historyRefreshInFlight = (async () => {
        try {
            const query = new URLSearchParams();
            if (state.historyStartDate) query.set("start_date", state.historyStartDate);
            if (state.historyEndDate) query.set("end_date", state.historyEndDate);
            const queryString = query.toString();
            const historyUrl = `/api/history${queryString ? `?${queryString}` : ""}`;
            const result = await fetchJSON(historyUrl, { cache: "no-store" }, true);
            if (!result || !result.items) return;

            const previousHistory = state.bootstrap.history || {};
            if (JSON.stringify(result) === JSON.stringify(previousHistory)) return;

            state.bootstrap.history = result;

            if (state.currentView === "dashboard") {
                renderDashboard();
            }

            if (state.currentView === "history") {
                updateHistorySummary();

                const grid = document.querySelector("#view-history .hist-grid");
                if (grid) grid.innerHTML = renderHistoryGrid();
            }

            if (state.activeHistoryBrawler) {
                updateHistoryDetails(state.activeHistoryBrawler);
            }
        } catch {
            return;
        }
    })().finally(() => {
        state.historyRefreshInFlight = null;
    });

    return state.historyRefreshInFlight;
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

function bindCustomScrollbar(scrollElementId, trackId, thumbId) {
    const grid = document.getElementById(scrollElementId);
    const track = document.getElementById(trackId);
    const thumb = document.getElementById(thumbId);
    if (!grid || !track || !thumb) return null;

    let animationFrame = null;
    let dragging = false;
    let dragStartY = 0;
    let dragStartScrollTop = 0;

    const updateScrollbar = () => {
        animationFrame = null;
        const scrollRange = Math.max(0, grid.scrollHeight - grid.clientHeight);
        const trackHeight = track.clientHeight;
        const hasOverflow = scrollRange > 1 && trackHeight > 0;

        track.classList.toggle("is-hidden", !hasOverflow);
        track.setAttribute("aria-valuemin", "0");
        track.setAttribute("aria-valuemax", String(Math.round(scrollRange)));
        track.setAttribute("aria-valuenow", String(Math.round(grid.scrollTop)));
        if (!hasOverflow) return;

        const thumbHeight = Math.min(trackHeight, Math.max(48, Math.round(trackHeight * grid.clientHeight / grid.scrollHeight)));
        const thumbTravel = Math.max(0, trackHeight - thumbHeight);
        const thumbTop = scrollRange ? (grid.scrollTop / scrollRange) * thumbTravel : 0;
        thumb.style.height = `${thumbHeight}px`;
        thumb.style.transform = `translate3d(0, ${thumbTop}px, 0)`;
    };

    const scheduleUpdate = () => {
        if (animationFrame !== null) return;
        animationFrame = requestAnimationFrame(updateScrollbar);
    };

    const handleThumbPointerDown = (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        dragging = true;
        dragStartY = event.clientY;
        dragStartScrollTop = grid.scrollTop;
        thumb.classList.add("is-dragging");
        thumb.setPointerCapture(event.pointerId);
    };

    const handleThumbPointerMove = (event) => {
        if (!dragging) return;
        event.preventDefault();
        const scrollRange = Math.max(0, grid.scrollHeight - grid.clientHeight);
        const thumbTravel = Math.max(0, track.clientHeight - thumb.offsetHeight);
        if (!scrollRange || !thumbTravel) return;
        grid.scrollTop = dragStartScrollTop + (event.clientY - dragStartY) * scrollRange / thumbTravel;
    };

    const finishThumbDrag = (event) => {
        if (!dragging) return;
        dragging = false;
        thumb.classList.remove("is-dragging");
        if (thumb.hasPointerCapture(event.pointerId)) {
            thumb.releasePointerCapture(event.pointerId);
        }
    };

    const handleTrackPointerDown = (event) => {
        if (event.target === thumb || event.button !== 0) return;
        event.preventDefault();
        const scrollRange = Math.max(0, grid.scrollHeight - grid.clientHeight);
        const trackRect = track.getBoundingClientRect();
        const thumbTravel = Math.max(0, track.clientHeight - thumb.offsetHeight);
        const requestedTop = Math.min(thumbTravel, Math.max(0, event.clientY - trackRect.top - thumb.offsetHeight / 2));
        grid.scrollTop = thumbTravel ? requestedTop / thumbTravel * scrollRange : 0;
    };

    const handleTrackWheel = (event) => {
        event.preventDefault();
        grid.scrollTop += event.deltaY;
    };

    const handleTrackKeydown = (event) => {
        const pageDistance = Math.max(80, grid.clientHeight * 0.85);
        const keyActions = {
            ArrowUp: () => { grid.scrollTop -= 48; },
            ArrowDown: () => { grid.scrollTop += 48; },
            PageUp: () => { grid.scrollTop -= pageDistance; },
            PageDown: () => { grid.scrollTop += pageDistance; },
            Home: () => { grid.scrollTop = 0; },
            End: () => { grid.scrollTop = grid.scrollHeight; },
        };
        const action = keyActions[event.key];
        if (!action) return;
        event.preventDefault();
        action();
    };

    grid.addEventListener("scroll", scheduleUpdate, { passive: true });
    track.addEventListener("pointerdown", handleTrackPointerDown);
    track.addEventListener("wheel", handleTrackWheel, { passive: false });
    track.addEventListener("keydown", handleTrackKeydown);
    thumb.addEventListener("pointerdown", handleThumbPointerDown);
    thumb.addEventListener("pointermove", handleThumbPointerMove);
    thumb.addEventListener("pointerup", finishThumbDrag);
    thumb.addEventListener("pointercancel", finishThumbDrag);
    window.addEventListener("resize", scheduleUpdate);

    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(scheduleUpdate) : null;
    const observeScrollableSizes = () => {
        if (!resizeObserver) return;
        resizeObserver.disconnect();
        resizeObserver.observe(grid);
        resizeObserver.observe(track);
        Array.from(grid.children).forEach((child) => resizeObserver.observe(child));
    };
    observeScrollableSizes();
    const mutationObserver = typeof MutationObserver === "function"
        ? new MutationObserver(() => {
            observeScrollableSizes();
            scheduleUpdate();
        })
        : null;
    mutationObserver?.observe(grid, { childList: true });

    const cleanup = () => {
        if (animationFrame !== null) cancelAnimationFrame(animationFrame);
        resizeObserver?.disconnect();
        mutationObserver?.disconnect();
        grid.removeEventListener("scroll", scheduleUpdate);
        track.removeEventListener("pointerdown", handleTrackPointerDown);
        track.removeEventListener("wheel", handleTrackWheel);
        track.removeEventListener("keydown", handleTrackKeydown);
        thumb.removeEventListener("pointerdown", handleThumbPointerDown);
        thumb.removeEventListener("pointermove", handleThumbPointerMove);
        thumb.removeEventListener("pointerup", finishThumbDrag);
        thumb.removeEventListener("pointercancel", finishThumbDrag);
        window.removeEventListener("resize", scheduleUpdate);
    };

    scheduleUpdate();
    return cleanup;
}

function bindHorizontalScrollbar(scrollElementId, trackId, thumbId) {
    const scroller = document.getElementById(scrollElementId);
    const track = document.getElementById(trackId);
    const thumb = document.getElementById(thumbId);
    if (!scroller || !track || !thumb) return null;

    let animationFrame = null;
    let dragging = false;
    let dragStartX = 0;
    let dragStartScrollLeft = 0;

    const updateScrollbar = () => {
        animationFrame = null;
        const scrollRange = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
        const trackWidth = track.clientWidth;
        const hasOverflow = scrollRange > 1 && trackWidth > 0;

        track.classList.toggle("is-hidden", !hasOverflow);
        track.setAttribute("aria-valuemin", "0");
        track.setAttribute("aria-valuemax", String(Math.round(scrollRange)));
        track.setAttribute("aria-valuenow", String(Math.round(scroller.scrollLeft)));
        if (!hasOverflow) return;

        const thumbWidth = Math.min(trackWidth, Math.max(48, Math.round(trackWidth * scroller.clientWidth / scroller.scrollWidth)));
        const thumbTravel = Math.max(0, trackWidth - thumbWidth);
        const thumbLeft = scrollRange ? (scroller.scrollLeft / scrollRange) * thumbTravel : 0;
        thumb.style.width = `${thumbWidth}px`;
        thumb.style.transform = `translate3d(${thumbLeft}px, 0, 0)`;
    };

    const scheduleUpdate = () => {
        if (animationFrame !== null) return;
        animationFrame = requestAnimationFrame(updateScrollbar);
    };

    const finishDrag = (event) => {
        if (!dragging) return;
        dragging = false;
        thumb.classList.remove("is-dragging");
        if (thumb.hasPointerCapture(event.pointerId)) thumb.releasePointerCapture(event.pointerId);
    };

    const handleThumbPointerDown = (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        dragging = true;
        dragStartX = event.clientX;
        dragStartScrollLeft = scroller.scrollLeft;
        thumb.classList.add("is-dragging");
        thumb.setPointerCapture(event.pointerId);
    };

    const handleThumbPointerMove = (event) => {
        if (!dragging) return;
        event.preventDefault();
        const scrollRange = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
        const thumbTravel = Math.max(0, track.clientWidth - thumb.offsetWidth);
        if (scrollRange && thumbTravel) {
            scroller.scrollLeft = dragStartScrollLeft + (event.clientX - dragStartX) * scrollRange / thumbTravel;
        }
    };

    const handleTrackPointerDown = (event) => {
        if (event.target === thumb || event.button !== 0) return;
        event.preventDefault();
        const scrollRange = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
        const trackRect = track.getBoundingClientRect();
        const thumbTravel = Math.max(0, track.clientWidth - thumb.offsetWidth);
        const requestedLeft = Math.min(thumbTravel, Math.max(0, event.clientX - trackRect.left - thumb.offsetWidth / 2));
        scroller.scrollLeft = thumbTravel ? requestedLeft / thumbTravel * scrollRange : 0;
    };

    const handleTrackWheel = (event) => {
        event.preventDefault();
        scroller.scrollLeft += event.deltaX || event.deltaY;
    };

    const handleTrackKeydown = (event) => {
        const pageDistance = Math.max(120, scroller.clientWidth * 0.85);
        const keyActions = {
            ArrowLeft: () => { scroller.scrollLeft -= 64; },
            ArrowRight: () => { scroller.scrollLeft += 64; },
            PageUp: () => { scroller.scrollLeft -= pageDistance; },
            PageDown: () => { scroller.scrollLeft += pageDistance; },
            Home: () => { scroller.scrollLeft = 0; },
            End: () => { scroller.scrollLeft = scroller.scrollWidth; },
        };
        const action = keyActions[event.key];
        if (!action) return;
        event.preventDefault();
        action();
    };

    scroller.addEventListener("scroll", scheduleUpdate, { passive: true });
    track.addEventListener("pointerdown", handleTrackPointerDown);
    track.addEventListener("wheel", handleTrackWheel, { passive: false });
    track.addEventListener("keydown", handleTrackKeydown);
    thumb.addEventListener("pointerdown", handleThumbPointerDown);
    thumb.addEventListener("pointermove", handleThumbPointerMove);
    thumb.addEventListener("pointerup", finishDrag);
    thumb.addEventListener("pointercancel", finishDrag);
    window.addEventListener("resize", scheduleUpdate);

    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(scheduleUpdate) : null;
    resizeObserver?.observe(scroller);
    resizeObserver?.observe(track);

    const cleanup = () => {
        if (animationFrame !== null) cancelAnimationFrame(animationFrame);
        resizeObserver?.disconnect();
        scroller.removeEventListener("scroll", scheduleUpdate);
        track.removeEventListener("pointerdown", handleTrackPointerDown);
        track.removeEventListener("wheel", handleTrackWheel);
        track.removeEventListener("keydown", handleTrackKeydown);
        thumb.removeEventListener("pointerdown", handleThumbPointerDown);
        thumb.removeEventListener("pointermove", handleThumbPointerMove);
        thumb.removeEventListener("pointerup", finishDrag);
        thumb.removeEventListener("pointercancel", finishDrag);
        window.removeEventListener("resize", scheduleUpdate);
    };

    scheduleUpdate();
    return cleanup;
}

function bindBrawlerScrollbar() {
    state.brawlerScrollbarCleanup?.();
    state.brawlerScrollbarCleanup = bindCustomScrollbar(
        "brawlerGrid",
        "brawlerGridScrollbar",
        "brawlerGridScrollbarThumb",
    );
}

function bindPlaystyleScrollbar() {
    state.playstyleScrollbarCleanup?.();
    state.playstyleScrollbarCleanup = bindCustomScrollbar(
        "playstyleLibrary",
        "playstyleLibraryScrollbar",
        "playstyleLibraryScrollbarThumb",
    );
}



function bindMainViewScrollbar() {
    state.mainViewScrollbarCleanup?.();
    state.mainViewScrollbarCleanup = bindCustomScrollbar(
        "viewsWrapper",
        "mainViewScrollbar",
        "mainViewScrollbarThumb",
    );
}

function bindQueueEvents() {
    bindBrawlerScrollbar();

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

    document.getElementById("brawlerSortSelect")?.addEventListener("change", handleBrawlerSortChange);
    document.getElementById("brawlerSortDirectionBtn")?.addEventListener("click", () => {
        state.brawlerSortDirection = state.brawlerSortDirection === "asc" ? "desc" : "asc";
        setStorageItem("brawlerSortDirection", state.brawlerSortDirection);
        renderQueue();
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

function handleBrawlerSortChange(event) {
    const requestedSort = event.target.value;
    const requiresPlayerData = ["trophies", "win_streak", "power_level"].includes(requestedSort);
    if (requiresPlayerData && !state.bootstrap?.auth?.premium) {
        event.target.value = state.brawlerSort;
        showPremiumModal();
        return;
    }
    const hasValidPlayerInfo = hasLivePlayerStats();
    if (requiresPlayerData && !hasValidPlayerInfo) {
        event.target.value = state.brawlerSort;
        showToast("Enter and validate a player tag before sorting by live brawler stats.", "error");
        return;
    }
    state.brawlerSort = requestedSort;
    setStorageItem("brawlerSort", requestedSort);
    renderQueue();
}

function trophyIconMarkup() {
    return `<img class="trophy-icon" src="/api/assets/support/trophies_icon.png" alt="Trophies">`;
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

    state.queueScrollbarCleanup?.();
    state.queueScrollbarCleanup = bindHorizontalScrollbar(
        "queueStrip",
        "queueStripScrollbar",
        "queueStripScrollbarThumb",
    );

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
    bindPlaystyleScrollbar();

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
    document.querySelectorAll("[data-toggle-playstyle-description]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const filename = button.dataset.togglePlaystyleDescription;
            if (state.expandedPlaystyleDescriptions.has(filename)) state.expandedPlaystyleDescriptions.delete(filename);
            else state.expandedPlaystyleDescriptions.add(filename);
            renderPlaystyles();
        });
    });

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
            try {
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
            } catch (error) {
                showToast(error.message || "Unable to activate playstyle.", "error");
            }
        });
    });
}





function bindSettingsEvents() {
    const settingsSearch = document.getElementById("settingsSearch");
    if (settingsSearch) {
        settingsSearch.addEventListener("input", () => {
            state.settingsSearch = settingsSearch.value;
            applySettingsSearch(settingsSearch.value);
        });
    }

    document.querySelectorAll("[data-client-setting]").forEach((input) => {
        input.addEventListener("input", () => {
            if (input.dataset.clientSetting === "showAllBrawlers") {
                state.showAllBrawlers = input.checked;
                setStorageItem("showAllBrawlers", String(input.checked));
                renderQueue();
            }
        });
    });

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

    document.querySelectorAll("[data-clear-secret-key]").forEach((button) => {
        button.addEventListener("click", () => clearSecretSetting(button));
    });

    // Make the entire setting checkbox card row clickable to toggle the checkbox
    document.querySelectorAll(".setting-row.check-card").forEach((card) => {
        card.addEventListener("click", (event) => {
            // If clicking the input directly, a button, a tooltip, or a label, let the native browser behavior handle it.
            // Clicking labels natively dispatches a click event to the target checkbox, so we must not double-toggle here.
            if (
                event.target.closest("input") || 
                event.target.closest("button") || 
                event.target.closest(".tooltip-anchor") ||
                event.target.closest("label")
            ) {
                return;
            }
            const input = card.querySelector("input[type='checkbox']");
            if (input && !input.disabled) {
                input.checked = !input.checked;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
            }
        });
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

    document.querySelectorAll(".btn-sync-toggle").forEach((button) => {
        button.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            await toggleSettingSync(button);
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
    showPremiumModal();
}

async function updatePlayerTag(tag) {
    showPremiumModal();
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
    state.playerInfo = {
        ok: false,
        player_tag: "",
        player_name: "",
        stats: {},
        message: "Live player profiles are available in Premium.",
    };
    renderQueue();
    if (notify) {
        showPremiumModal();
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
    showPremiumModal();
}

async function savePlayOrder(playOrder) {
    const saved = await fetchJSON("/api/settings/general", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ play_order: playOrder }),
    });

    state.bootstrap.settings.general = { ...state.bootstrap.settings.general, ...saved };
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
    const previousMaxResolution = section === "general"
        ? state.bootstrap.settings.general.max_resolution
        : null;
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
        const switchedTo1280 = ["auto", "1920x1080"].includes(previousMaxResolution)
            && result.max_resolution === "1280x720";
        const switchedFrom1280 = previousMaxResolution === "1280x720"
            && ["auto", "1920x1080"].includes(result.max_resolution);
        if (switchedTo1280 || switchedFrom1280) {
            const botSettings = await fetchJSON("/api/settings/bot", {}, true);
            if (botSettings && botSettings.ok !== false) {
                state.bootstrap.settings.bot = botSettings;
            }
        }
        await refreshPlayerInfo(result.player_tag || "", false);
    }

    renderSettings();
}

async function clearSecretSetting(button) {
    const section = button.dataset.clearSecretSection;
    const key = button.dataset.clearSecretKey;
    const label = button.dataset.clearSecretLabel || "this sensitive value";
    if (!section || !key || !window.confirm(`Clear ${label}? This cannot be undone.`)) return;

    const result = await fetchJSON(`/api/settings/${section}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: "", _clear_secrets: [key] }),
    }, true);
    if (!result || result.ok === false) {
        showToast(result?.message || `Failed to clear ${label}.`, "error");
        return;
    }
    state.bootstrap.settings[section] = result;
    renderSettings();
    showToast(`${label} cleared.`, "success");
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
        if (input.type === "password" && !input.value) return;
        payload[key] = input.type === "checkbox" ? input.checked : input.value;
        if (key === "player_tag") {
            payload[key] = formatPlayerTagInput(input.value);
        }
    });

    if (section === "debug" && payload.debug_view === false) {
        payload.advanced_debug_visuals = false;
    }

    return payload;
}

function applySettingsSearch(query) {
    const normalized = String(query || "").trim().toLowerCase();
    const sections = Array.from(document.querySelectorAll("#view-settings .settings-section"));
    let visibleSettings = 0;

    sections.forEach((section) => {
        const rows = Array.from(section.querySelectorAll(".setting-row, .timer-box"));
        rows.forEach((row) => {
            const matches = !normalized || row.textContent.toLowerCase().includes(normalized);
            row.classList.toggle("settings-search-hidden", !matches);
            if (matches) visibleSettings += 1;
        });
        section.classList.toggle(
            "settings-search-hidden",
            Boolean(normalized) && !rows.some((row) => !row.classList.contains("settings-search-hidden"))
        );
    });

    const status = document.getElementById("settingsSearchStatus");
    if (status) {
        status.textContent = normalized && visibleSettings === 0
            ? "No settings found"
            : normalized
                ? `${visibleSettings} setting${visibleSettings === 1 ? "" : "s"} found`
                : "";
    }
}

async function handlePlaystyleImport(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    const result = await fetchJSON("/api/playstyles/import", { method: "POST", body: formData }, true);

    if (!result.ok) {
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

    const result = await fetchJSON("/api/queue/import", { method: "POST", body: formData }, true);

    if (!result.ok) {
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

function hasLivePlayerStats() {
    return Boolean(state.playerInfo.player_tag && Object.keys(state.playerInfo.stats || {}).length);
}

function getVisibleBrawlers() {
    const brawlers = state.bootstrap?.brawlers || [];
    if (!hasLivePlayerStats() || state.showAllBrawlers) {
        return brawlers;
    }
    return brawlers.filter((item) => item.name in state.playerInfo.stats);
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
    return [
        String(item.brawler || ""),
        `${item.current_label}: ${item.current_value}`,
        `${item.target_label}: ${item.push_until}`,
        `Auto Pick: ${item.automatically_pick ? "On" : "Off"}`,
    ].join("\n");
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
    if (!UI_API_TOKEN) {
        throw new Error("Local UI security token is missing.");
    }

    const headers = new Headers(options.headers || {});
    headers.set("X-Pyla-UI-Token", UI_API_TOKEN);
    const response = await fetch(url, {
        ...options,
        headers,
        credentials: "same-origin",
    });
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
        zap:        `<svg ${S}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
        import:     `<svg ${S}><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/></svg>`,
        close:      `<svg ${S}><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`,
        logs:       `<svg ${S}><path d="M12 19h8"/><path d="m4 17 6-6-6-6"/></svg>`,
        copy:       `<svg ${S}><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`,
        search:     `<svg ${S}><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>`,
        trash:      `<svg ${S}><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 15H6L5 6"/><path d="M10 11v5"/><path d="M14 11v5"/></svg>`,
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


function showPremiumModal() {
    let modal = document.getElementById("premiumFeatureModal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "premiumFeatureModal";
        modal.className = "modal-overlay";
        modal.innerHTML = `
            <div class="modal">
                <div class="modal-header">
                    <p class="eyebrow premium-copy">Premium Feature</p>
                    <h3>Unlock more automation</h3>
                    <p>Profiles, live player data, Push All and selected advanced controls are available in Pyla Premium. The public edition remains free and open-source.</p>
                </div>
                <div class="premium-modal-actions">
                    <a class="btn btn-primary w-full premium-cta" href="https://pyla-ai.angelfirela.dev/premium" target="_blank" rel="noreferrer">Explore Premium</a>
                    <button id="closePremiumModalBtn" class="btn w-full" type="button">Maybe later</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        document.getElementById("closePremiumModalBtn")?.addEventListener("click", () => modal.classList.add("hidden"));
        modal.addEventListener("click", (event) => { if (event.target === modal) modal.classList.add("hidden"); });
    }
    modal.classList.remove("hidden");
}

async function refreshLogs() {
    try {
        const data = await fetchJSON("/api/runtime/logs", {}, true);
        if (data && data.logs) {
            renderLogsContent(data.logs);
        }
    } catch (e) {
        console.error("Failed to fetch logs:", e);
    }
}

function renderLogsContent(logs) {
    const view = document.getElementById("view-logs");
    if (!view) return;

    if (!view.querySelector(".logs-layout")) {
        view.innerHTML = `
            <div class="logs-layout">
                <section class="panel">
                    <div class="panel-header logs-head">
                        <div class="panel-actions logs-actions">
                            <button id="btnCopyLogs" class="btn">Copy All</button>
                            <button id="btnSaveLogs" class="btn">Save TXT</button>
                            <button id="btnClearLogs" class="btn">Clear</button>
                            <button id="btnScrollToggle" class="btn btn-primary">Auto-scroll: ON</button>
                        </div>
                    </div>
                    <div class="logs-terminal-container">
                        <div id="logsTerminal" class="logs-terminal"></div>
                    </div>
                </section>
            </div>
        `;
        document.getElementById("btnCopyLogs").addEventListener("click", copyAllLogs);
        document.getElementById("btnSaveLogs").addEventListener("click", saveLogsToTxt);
        document.getElementById("btnClearLogs").addEventListener("click", clearLogs);
        document.getElementById("btnScrollToggle").addEventListener("click", toggleAutoScroll);
    }

    const terminal = document.getElementById("logsTerminal");
    if (!terminal) return;

    const container = document.querySelector(".logs-terminal-container");
    const wasAtBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 50;

    if (logs.length === 0) {
        terminal.innerHTML = `<div class="log-line text-muted">No logs recorded yet. Start the bot to see output.</div>`;
    } else {
        const currentLines = terminal.querySelectorAll(".log-line");
        const hasPlaceholder = terminal.querySelector(".text-muted");
        
        const firstLineMatches = currentLines.length > 0
            && currentLines[0].textContent === String(logs[0]);
            
        if (hasPlaceholder || currentLines.length > logs.length || !firstLineMatches) {
            const fragment = document.createDocumentFragment();
            logs.forEach((line) => {
                const div = document.createElement("div");
                div.className = "log-line";
                div.textContent = String(line);
                fragment.appendChild(div);
            });
            terminal.replaceChildren(fragment);
        } else if (currentLines.length < logs.length) {
            const fragment = document.createDocumentFragment();
            for (let i = currentLines.length; i < logs.length; i++) {
                const div = document.createElement("div");
                div.className = "log-line";
                div.textContent = String(logs[i]);
                fragment.appendChild(div);
            }
            terminal.appendChild(fragment);
        }
    }

    if (state.autoScrollLogs && (wasAtBottom || state.forceScrollLogs)) {
        container.scrollTop = container.scrollHeight;
        state.forceScrollLogs = false;
    }
}

function copyAllLogs() {
    const terminal = document.getElementById("logsTerminal");
    if (!terminal) return;
    
    const lines = Array.from(terminal.querySelectorAll(".log-line"))
        .map(el => el.textContent)
        .filter(text => text !== "No logs recorded yet. Start the bot to see output.");
        
    const fullText = lines.join("\n");
    if (!fullText) {
        showToast("No logs to copy.", "error");
        return;
    }
    
    navigator.clipboard.writeText(fullText)
        .then(() => showToast("Logs copied to clipboard.", "success"))
        .catch(err => {
            console.error("Could not copy logs: ", err);
            showToast("Failed to copy logs.", "error");
        });
}

function saveLogsToTxt() {
    const terminal = document.getElementById("logsTerminal");
    if (!terminal) return;
    
    const lines = Array.from(terminal.querySelectorAll(".log-line"))
        .map(el => el.textContent)
        .filter(text => text !== "No logs recorded yet. Start the bot to see output.");
        
    const fullText = lines.join("\n");
    if (!fullText) {
        showToast("No logs to save.", "error");
        return;
    }
    
    try {
        const blob = new Blob([fullText], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
        a.download = `pyla_bot_logs_${timestamp}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast("Logs saved successfully.", "success");
    } catch (err) {
        console.error("Could not save logs: ", err);
        showToast("Failed to save logs.", "error");
    }
}

function toggleAutoScroll() {
    state.autoScrollLogs = !state.autoScrollLogs;
    const btn = document.getElementById("btnScrollToggle");
    if (btn) {
        btn.textContent = `Auto-scroll: ${state.autoScrollLogs ? "ON" : "OFF"}`;
        btn.className = `btn btn-sm ${state.autoScrollLogs ? "btn-primary" : ""}`;
    }
    if (state.autoScrollLogs) {
        state.forceScrollLogs = true;
        const container = document.querySelector(".logs-terminal-container");
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }
}

async function clearLogs() {
    try {
        const result = await fetchJSON("/api/runtime/logs", { method: "DELETE" });
        if (result.ok) {
            showToast("Logs cleared.", "success");
            state.forceScrollLogs = true;
            await refreshLogs();
        }
    } catch (e) {
        showToast("Failed to clear logs.", "error");
    }
}






