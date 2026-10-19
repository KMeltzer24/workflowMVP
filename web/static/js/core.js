// Shared state, credentials, toasts, tabs.
// WorkflowMVP — web client
//
// Highlights:
//   - Tabs + toasts + Settings modal (creds kept in sessionStorage).
//   - SSE-based live run streaming.
//   - Save/load workflows in localStorage.
//   - Inline "missing credentials" prompt before running a workflow that
//     needs creds the session doesn't have.

const CREDS_KEY = "workflowmvp.credentials";
const SAVED_WORKFLOWS_KEY = "workflowmvp.savedWorkflows";
const CREDENTIAL_KEYS = [
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "EMAIL_USER",
    "EMAIL_PASSWORD",
    "EMAIL_FROM",
    "SMTP_SERVER",
    "SMTP_PORT",
];

const TAB_ORDER = ["workspace", "examples", "tools"];

const state = {
    parsedSteps: [],
    currentWorkflowPath: null,
    generatedCode: "",
    stepsEdited: false,
    streaming: false,
    parseConfidence: null,
    parseAiAssisted: false,
    parseAiRepair: null,
    parseSeconds: null,
    tools: [],
    parseTimerId: null,
    parseStartMs: null,
    generateTimerId: null,
    generateStartMs: null,
    lastGenerationSeconds: null,
};

// -------------------- Credentials --------------------

function loadCreds() {
    try {
        const raw = sessionStorage.getItem(CREDS_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return typeof parsed === "object" && parsed ? parsed : {};
    } catch (_) {
        return {};
    }
}

function saveCreds(creds) {
    const filtered = {};
    for (const key of CREDENTIAL_KEYS) {
        if (creds[key]) filtered[key] = String(creds[key]).trim();
    }
    sessionStorage.setItem(CREDS_KEY, JSON.stringify(filtered));
}

function clearCreds() {
    sessionStorage.removeItem(CREDS_KEY);
}

// -------------------- Saved workflows --------------------

function loadSavedWorkflows() {
    try {
        const raw = localStorage.getItem(SAVED_WORKFLOWS_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return typeof parsed === "object" && parsed ? parsed : {};
    } catch (_) {
        return {};
    }
}

function persistSavedWorkflows(all) {
    localStorage.setItem(SAVED_WORKFLOWS_KEY, JSON.stringify(all));
}

function refreshSavedList() {
    const select = document.getElementById("savedList");
    if (!select) return;
    const saved = loadSavedWorkflows();
    const names = Object.keys(saved).sort();
    select.innerHTML = '<option value="">Load saved…</option>';
    for (const name of names) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    }
}

// -------------------- Toasts --------------------

function toast(message, variant = "info") {
    const host = document.getElementById("toasts");
    if (!host) return;
    const node = document.createElement("div");
    node.className = `toast ${variant}`;
    node.textContent = message;
    host.appendChild(node);
    setTimeout(() => {
        node.style.opacity = "0";
        node.style.transition = "opacity 0.2s";
        setTimeout(() => node.remove(), 220);
    }, 3800);
}

// -------------------- Tabs --------------------

function activateTab(name) {
    document.querySelectorAll(".tab").forEach((btn) => {
        const on = btn.dataset.tab === name;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
        btn.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `tab-${name}`);
    });
    if (name === "workspace" && typeof updateRunSummary === "function") {
        updateRunSummary();
    }
}

document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
    btn.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
        event.preventDefault();
        const index = TAB_ORDER.indexOf(btn.dataset.tab);
        if (index < 0) return;
        const delta = event.key === "ArrowRight" ? 1 : -1;
        const next = TAB_ORDER[(index + delta + TAB_ORDER.length) % TAB_ORDER.length];
        activateTab(next);
        const nextBtn = document.querySelector(`.tab[data-tab="${next}"]`);
        if (nextBtn) nextBtn.focus();
    });
});

// -------------------- Helpers --------------------

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

