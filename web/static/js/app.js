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
    "EMAIL_USER",
    "EMAIL_PASSWORD",
    "EMAIL_FROM",
    "SMTP_SERVER",
    "SMTP_PORT",
];

const state = {
    parsedSteps: [],
    currentWorkflowPath: null,
    stepsEdited: false,
    streaming: false,
    parseConfidence: null,
    parseAiAssisted: false,
    tools: [],
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
    select.innerHTML = '<option value="">Load saved workflow...</option>';
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
        btn.classList.toggle("active", btn.dataset.tab === name);
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `tab-${name}`);
    });
}

document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

// -------------------- Initial data --------------------

async function loadTools() {
    try {
        const response = await fetch("/api/tools");
        const tools = await response.json();
        state.tools = Array.isArray(tools) ? tools : [];
        buildToolCategoryOptions(state.tools);
        renderTools();
    } catch (err) {
        toast(`Could not load tools: ${err.message}`, "error");
    }
}

function buildToolCategoryOptions(tools) {
    const select = document.getElementById("toolCategorySelect");
    if (!select) return;
    const categories = new Set(["all"]);
    for (const tool of tools) {
        categories.add(toolCategory(tool.name));
    }
    const ordered = Array.from(categories).sort();
    select.innerHTML = "";
    for (const category of ordered) {
        const option = document.createElement("option");
        option.value = category;
        option.textContent = category === "all" ? "All categories" : category;
        select.appendChild(option);
    }
}

function renderTools() {
    const host = document.getElementById("tools");
    if (!host) return;
    const search = (document.getElementById("toolSearchInput").value || "")
        .trim()
        .toLowerCase();
    const category = document.getElementById("toolCategorySelect").value || "all";
    const filtered = state.tools.filter((tool) => {
        const params = Object.keys(tool.parameters || {}).join(" ").toLowerCase();
        const haystack = `${tool.name || ""} ${tool.description || ""} ${params}`.toLowerCase();
        const matchesSearch = !search || haystack.includes(search);
        const matchesCategory = category === "all" || toolCategory(tool.name) === category;
        return matchesSearch && matchesCategory;
    });

    host.innerHTML = "";
    for (const tool of filtered) {
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `
            <h3>${escapeHtml(tool.name)}</h3>
            <p>${escapeHtml(tool.description || "")}</p>
            <p class="muted" style="margin-top:8px"><code>${
                Object.keys(tool.parameters || {})
                    .map(escapeHtml)
                    .join(", ") || "(no parameters)"
            }</code></p>
        `;
        host.appendChild(card);
    }
    document.getElementById("toolCountPill").textContent =
        `${filtered.length} / ${state.tools.length} tools`;
}

function toolCategory(name) {
    const n = String(name || "").toLowerCase();
    if (n === "generate_text") return "ai";
    if (n === "fetch_stock_price") return "finance";
    if (n === "http_request") return "network";
    if (n.includes("email") || n.includes("notification")) return "communication";
    if (n.includes("csv") || n.includes("json") || n.includes("analyze") || n.includes("process_data")) return "data";
    if (n.includes("sqlite") || n.includes("query") || n.includes("insert")) return "database";
    if (n.includes("download") || n.includes("scrape")) return "network";
    if (n.includes("compress") || n.includes("archive")) return "archive";
    if (n.includes("file") || n.includes("directory") || n.includes("copy") || n.includes("move") || n.includes("delete") || n.includes("read") || n.includes("write") || n.includes("list")) return "filesystem";
    if (n.includes("command") || n.includes("wait")) return "system";
    return "general";
}

async function loadExamples() {
    try {
        const response = await fetch("/api/examples");
        const examples = await response.json();
        const host = document.getElementById("examples");
        host.innerHTML = "";
        for (const example of examples) {
            const card = document.createElement("div");
            card.className = "card clickable";
            const needs = Array.isArray(example.requires_credentials)
                ? example.requires_credentials
                : [];
            const stepCount = (example.workflow || "").split("\n").filter(l => /^\d+\./.test(l.trim())).length;
            card.innerHTML = `
                <div class="card-title-row">
                    <h3>${escapeHtml(example.name)}</h3>
                    <span class="pill">${stepCount} step${stepCount !== 1 ? "s" : ""}</span>
                </div>
                <p>${escapeHtml(example.description || "")}</p>
                <div class="card-badges">
                    ${needs.length
                        ? `<span class="badge badge-warn">Needs: ${needs.map(escapeHtml).join(", ")}</span>`
                        : `<span class="badge badge-ok">No credentials needed</span>`
                    }
                    <span class="badge badge-action">Click to load →</span>
                </div>
            `;
            card.addEventListener("click", () => {
                document.getElementById("workflowText").value = example.workflow;
                document.querySelector("input[name='inputType'][value='text']").checked = true;
                toggleInputType();
                activateTab("create");
                parseWorkflow();
                toast(`Loaded: ${example.name}`, "success");
            });
            host.appendChild(card);
        }
    } catch (err) {
        toast(`Could not load examples: ${err.message}`, "error");
    }
}

// -------------------- Parse workflow --------------------

function parseWorkflow() {
    const inputType = document.querySelector("input[name='inputType']:checked").value;
    if (inputType === "text") {
        const text = document.getElementById("workflowText").value;
        if (!text.trim()) {
            toast("Enter a workflow description first", "warning");
            return;
        }
        parseTextWorkflow(text);
    } else {
        const videoFile = document.getElementById("videoFile").files[0];
        if (!videoFile) {
            toast("Choose a video file first", "warning");
            return;
        }
        parseVideoWorkflow(videoFile);
    }
}

async function parseTextWorkflow(text) {
    toast("Parsing workflow...");
    try {
        const response = await fetch("/api/parse-workflow", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workflow_text: text,
                credentials: loadCreds(),
            }),
        });
        const data = await response.json();
        if (!data.success) {
            toast(`Parse failed: ${data.error}`, "error");
            return;
        }
        state.parsedSteps = data.steps;
        state.stepsEdited = false;
        state.parseConfidence = data.parse_confidence || null;
        state.parseAiAssisted = Boolean(data.ai_assisted);
        displaySteps(data.steps);
        renderParseInsights();
        enableGenerate(true);
        if (data.ai_assisted) {
            toast(
                `Parsed ${data.steps.length} steps (AI-assisted for low-confidence input)`,
                "success"
            );
        } else {
            toast(`Parsed ${data.steps.length} steps`, "success");
        }
    } catch (err) {
        toast(`Parse error: ${err.message}`, "error");
    }
}

async function parseVideoWorkflow(videoFile) {
    toast("Processing video (this can take a moment)...");
    try {
        const formData = new FormData();
        formData.append("video", videoFile);
        formData.append("credentials", JSON.stringify(loadCreds()));

        const response = await fetch("/api/parse-video", {
            method: "POST",
            body: formData,
        });
        const data = await response.json();
        if (!data.success) {
            if (
                Array.isArray(data.missing_requirements) &&
                data.missing_requirements.includes("GEMINI_API_KEY")
            ) {
                toast(
                    "Gemini API key required. Open Settings to add one.",
                    "warning"
                );
                openSettings();
                return;
            }
            toast(`Video parse failed: ${data.error}`, "error");
            return;
        }
        state.parsedSteps = data.steps;
        state.stepsEdited = false;
        state.parseConfidence = data.parse_confidence || null;
        state.parseAiAssisted = Boolean(data.ai_assisted);
        displaySteps(data.steps);
        renderParseInsights();
        enableGenerate(true);
        toast(`Parsed ${data.steps.length} steps from video`, "success");
    } catch (err) {
        toast(`Video parse error: ${err.message}`, "error");
    }
}

function enableGenerate(enabled) {
    const btn = document.getElementById("generateBtn");
    btn.disabled = !enabled;
    btn.textContent = "Generate Python code";
}

function displaySteps(steps) {
    const host = document.getElementById("parsedSteps");
    host.innerHTML = "";
    steps.forEach((step, index) => {
        const div = document.createElement("div");
        div.className = "step";
        div.innerHTML = `
            <div class="step-header">
                <strong>Step ${index + 1}</strong>
                <button class="edit-btn" data-index="${index}" type="button">Edit</button>
            </div>
            <div id="step-display-${index}">
                <div class="step-description">${escapeHtml(step.description)}</div>
                <div class="step-meta">Action: ${escapeHtml(step.action)} &middot; Depends on: ${
            step.dependencies.length ? escapeHtml(step.dependencies.join(", ")) : "none"
        }</div>
            </div>
            <div id="step-edit-${index}" class="hidden">
                <textarea class="edit-description" id="edit-desc-${index}">${escapeHtml(
            step.description
        )}</textarea>
                <div class="edit-actions">
                    <button class="save-btn" data-save="${index}" type="button">Save</button>
                    <button class="cancel-btn" data-cancel="${index}" type="button">Cancel</button>
                </div>
            </div>
        `;
        host.appendChild(div);
    });
    document.getElementById("stepsPanel").hidden = false;
    document.getElementById("stepCountPill").textContent = `${steps.length} steps`;
}

document.addEventListener("click", (event) => {
    const edit = event.target.closest(".edit-btn");
    const save = event.target.closest(".save-btn");
    const cancel = event.target.closest(".cancel-btn");
    if (edit) toggleEdit(+edit.dataset.index);
    if (save) saveStep(+save.dataset.save);
    if (cancel) cancelEdit(+cancel.dataset.cancel);
});

function toggleEdit(index) {
    const display = document.getElementById(`step-display-${index}`);
    const edit = document.getElementById(`step-edit-${index}`);
    if (!display || !edit) return;
    display.classList.toggle("hidden");
    edit.classList.toggle("hidden");
    if (!edit.classList.contains("hidden")) {
        document.getElementById(`edit-desc-${index}`).focus();
    }
}

function saveStep(index) {
    const value = document.getElementById(`edit-desc-${index}`).value.trim();
    if (!value) {
        toast("Description cannot be empty", "warning");
        return;
    }
    state.parsedSteps[index].description = value;
    state.stepsEdited = true;
    reparseStep(index, value)
        .finally(() => {
            const row = document.querySelector(`#step-display-${index} .step-description`);
            row.textContent = value;
            const meta = document.querySelector(`#step-display-${index} .step-meta`);
            if (meta) {
                const step = state.parsedSteps[index];
                meta.innerHTML = `Action: ${escapeHtml(step.action)} &middot; Depends on: ${
                    step.dependencies.length ? escapeHtml(step.dependencies.join(", ")) : "none"
                }`;
            }
            toggleEdit(index);
            const generateBtn = document.getElementById("generateBtn");
            generateBtn.textContent = "Generate Python code (modified)";
            markParseInsightsStale();
            toast(`Updated step ${index + 1}`, "success");
        });
}

function cancelEdit(index) {
    document.getElementById(`edit-desc-${index}`).value =
        state.parsedSteps[index].description;
    toggleEdit(index);
}

async function reparseStep(index, description) {
    try {
        const response = await fetch("/api/parse-single-step", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ description }),
        });
        const data = await response.json();
        if (data.success) {
            state.parsedSteps[index].action = data.action || state.parsedSteps[index].action;
            state.parsedSteps[index].parameters = data.parameters || state.parsedSteps[index].parameters;
        }
    } catch (_) {
        // Non-fatal: keep edited description even if re-parse fails.
    }
}

function renderParseInsights() {
    const box = document.getElementById("parseInsights");
    if (!box) return;
    const c = state.parseConfidence;
    if (!c) {
        box.classList.add("hidden");
        box.innerHTML = "";
        return;
    }
    const scorePct = Math.round(Number(c.score || 0) * 100);
    const mode = state.parseAiAssisted ? "AI-assisted" : "Rule-first";
    const reasons = Array.isArray(c.reasons) ? c.reasons.slice(0, 3) : [];
    box.innerHTML = `
        <strong>Parse quality:</strong> ${scorePct}% (${mode})
        <div class="hint">Custom steps: ${c.custom_steps || 0}, missing-param steps: ${c.missing_param_steps || 0}</div>
        ${
            reasons.length
                ? `<div class="hint">${reasons.map(escapeHtml).join(" | ")}</div>`
                : ""
        }
    `;
    box.dataset.stale = "0";
    box.classList.remove("hidden");
}

function markParseInsightsStale() {
    const box = document.getElementById("parseInsights");
    if (!box || box.classList.contains("hidden")) return;
    if (box.dataset.stale === "1") return;
    box.dataset.stale = "1";
    box.innerHTML += '<div class="hint">Step descriptions were edited manually; re-parse for refreshed confidence.</div>';
}

// -------------------- Generate --------------------

async function generateWorkflow() {
    if (!state.parsedSteps.length) {
        toast("Parse a workflow first", "warning");
        return;
    }
    toast("Generating Python code...");
    try {
        const response = await fetch("/api/generate-workflow", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                steps: state.parsedSteps,
                name: `workflow_${Date.now()}`,
                credentials: loadCreds(),
            }),
        });
        const data = await response.json();
        if (!data.success) {
            if (Array.isArray(data.missing_requirements) && data.missing_requirements.length) {
                toast(`Missing ${data.missing_requirements.join(", ")} — open Settings`, "warning");
                openSettings();
                return;
            }
            toast(`Generation failed: ${data.error}`, "error");
            return;
        }
        state.currentWorkflowPath = data.output_path;
        document.getElementById("runBtn").disabled = false;
        document.getElementById("runMeta").textContent = `Ready to run: ${data.output_path}`;
        toast("Python code generated", "success");
        activateTab("run");
    } catch (err) {
        toast(`Generate error: ${err.message}`, "error");
    }
}

// -------------------- Run (SSE) --------------------

async function runWorkflow() {
    if (!state.currentWorkflowPath) {
        toast("Generate a workflow first", "warning");
        return;
    }
    if (state.streaming) return;

    const creds = loadCreds();
    const missing = await checkRequirements(state.parsedSteps, creds);
    if (missing.length) {
        openPrompt(missing, (promptCreds, persist) => {
            const merged = { ...creds, ...promptCreds };
            if (persist) saveCreds(merged);
            startStream(merged);
        });
        return;
    }
    startStream(creds);
}

async function checkRequirements(steps, creds) {
    try {
        const response = await fetch("/api/check-requirements", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ steps, credentials: creds }),
        });
        const data = await response.json();
        if (!data.success) return [];
        return Array.isArray(data.missing) ? data.missing : [];
    } catch (_) {
        return [];
    }
}

function startStream(creds) {
    const out = document.getElementById("runOutput");
    out.innerHTML = "";
    const statusPill = document.getElementById("runStatusPill");
    statusPill.textContent = "running";
    statusPill.className = "pill running";
    state.streaming = true;
    document.getElementById("runBtn").disabled = true;

    // Use fetch + ReadableStream so we can POST the body (EventSource is GET-only).
    fetch("/api/run-workflow/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            workflow_path: state.currentWorkflowPath,
            credentials: creds,
        }),
    })
        .then((response) => {
            if (!response.ok || !response.body) {
                throw new Error(`HTTP ${response.status}`);
            }
            return consumeSSE(response.body, out, statusPill);
        })
        .catch((err) => {
            appendLine(out, `stream error: ${err.message}`, "err");
            statusPill.textContent = "error";
            statusPill.className = "pill error";
        })
        .finally(() => {
            state.streaming = false;
            document.getElementById("runBtn").disabled = false;
        });
}

async function consumeSSE(stream, out, statusPill) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const chunk = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            handleSSEChunk(chunk, out, statusPill);
        }
    }
}

function handleSSEChunk(chunk, out, statusPill) {
    let event = "message";
    let data = "";
    for (const rawLine of chunk.split("\n")) {
        if (rawLine.startsWith("event:")) {
            event = rawLine.slice(6).trim();
        } else if (rawLine.startsWith("data:")) {
            data += rawLine.slice(5).trim();
        }
    }
    if (!data) return;
    let payload;
    try {
        payload = JSON.parse(data);
    } catch (_) {
        return;
    }
    switch (event) {
        case "status":
            appendLine(out, `[${payload.message}] run_id=${payload.run_id}`, "info");
            break;
        case "log":
            appendLine(out, payload.line || "");
            break;
        case "done":
            if (payload.success) {
                appendLine(out, `workflow completed (exit ${payload.returncode})`, "info");
                statusPill.textContent = "success";
                statusPill.className = "pill success";
                toast("Workflow completed", "success");
            } else {
                appendLine(
                    out,
                    `workflow failed (exit ${payload.returncode})`,
                    "err"
                );
                statusPill.textContent = "error";
                statusPill.className = "pill error";
                toast("Workflow failed", "error");
            }
            break;
        case "error":
            appendLine(out, payload.message || "error", "err");
            statusPill.textContent = "error";
            statusPill.className = "pill error";
            toast(`Run error: ${payload.message}`, "error");
            break;
    }
}

function appendLine(host, text, kind = "ok") {
    const span = document.createElement("span");
    span.className = `line-${kind}`;
    span.textContent = text + "\n";
    host.appendChild(span);
    host.scrollTop = host.scrollHeight;
}

// -------------------- Settings modal --------------------

function openSettings() {
    const modal = document.getElementById("settingsModal");
    const form = document.getElementById("settingsForm");
    const creds = loadCreds();
    for (const key of CREDENTIAL_KEYS) {
        const input = form.elements.namedItem(key);
        if (input) input.value = creds[key] || "";
    }
    modal.classList.remove("hidden");
}

function closeSettings() {
    document.getElementById("settingsModal").classList.add("hidden");
}

document.getElementById("settingsBtn").addEventListener("click", openSettings);
document.getElementById("closeSettingsBtn").addEventListener("click", closeSettings);
document.getElementById("clearCredsBtn").addEventListener("click", () => {
    clearCreds();
    document.getElementById("settingsForm").reset();
    toast("Credentials cleared", "success");
});
document.getElementById("settingsForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = {};
    for (const key of CREDENTIAL_KEYS) {
        const input = form.elements.namedItem(key);
        if (input) values[key] = input.value;
    }
    saveCreds(values);
    closeSettings();
    toast("Credentials saved in this browser session", "success");
});

// -------------------- Inline creds prompt --------------------

let promptResolve = null;

function openPrompt(missingKeys, onSubmit) {
    const modal = document.getElementById("promptModal");
    const fields = document.getElementById("promptFields");
    fields.innerHTML = "";
    for (const key of missingKeys) {
        const label = document.createElement("label");
        const isSecret = key.includes("PASSWORD") || key.includes("KEY");
        label.innerHTML = `${escapeHtml(key)}
            <input type="${isSecret ? "password" : "text"}" name="${escapeHtml(
            key
        )}" required>`;
        fields.appendChild(label);
    }
    promptResolve = onSubmit;
    modal.classList.remove("hidden");
    const first = fields.querySelector("input");
    if (first) first.focus();
}

function closePrompt() {
    document.getElementById("promptModal").classList.add("hidden");
    promptResolve = null;
}

document.getElementById("closePromptBtn").addEventListener("click", closePrompt);
document.getElementById("cancelPromptBtn").addEventListener("click", closePrompt);
document.getElementById("promptForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const creds = {};
    for (const input of form.querySelectorAll("input[type='text'], input[type='password']")) {
        if (input.name) creds[input.name] = input.value;
    }
    const persist = document.getElementById("persistCredsCheckbox").checked;
    const cb = promptResolve;
    closePrompt();
    if (cb) cb(creds, persist);
});

// -------------------- Save/Load workflows --------------------

document.getElementById("saveBtn").addEventListener("click", () => {
    const text = document.getElementById("workflowText").value.trim();
    if (!text) {
        toast("Nothing to save", "warning");
        return;
    }
    const name = prompt("Save as:");
    if (!name) return;
    const all = loadSavedWorkflows();
    all[name] = { text, savedAt: new Date().toISOString() };
    persistSavedWorkflows(all);
    refreshSavedList();
    toast(`Saved "${name}"`, "success");
});

document.getElementById("savedList").addEventListener("change", (event) => {
    const name = event.target.value;
    if (!name) return;
    const all = loadSavedWorkflows();
    const item = all[name];
    if (!item) return;
    document.getElementById("workflowText").value = item.text;
    toast(`Loaded "${name}"`, "success");
});

document.getElementById("deleteSavedBtn").addEventListener("click", () => {
    const select = document.getElementById("savedList");
    const name = select.value;
    if (!name) {
        toast("Pick a saved workflow first", "warning");
        return;
    }
    const all = loadSavedWorkflows();
    delete all[name];
    persistSavedWorkflows(all);
    refreshSavedList();
    toast(`Deleted "${name}"`, "success");
});

// -------------------- Misc wiring --------------------

document.getElementById("parseBtn").addEventListener("click", parseWorkflow);
document.getElementById("generateBtn").addEventListener("click", generateWorkflow);
document.getElementById("runBtn").addEventListener("click", runWorkflow);
document.getElementById("clearLogsBtn").addEventListener("click", () => {
    document.getElementById("runOutput").innerHTML = "";
});
document.getElementById("toolSearchInput").addEventListener("input", renderTools);
document.getElementById("toolCategorySelect").addEventListener("change", renderTools);
document
    .querySelectorAll("input[name='inputType']")
    .forEach((radio) => radio.addEventListener("change", toggleInputType));

function toggleInputType() {
    const inputType = document.querySelector("input[name='inputType']:checked").value;
    document.getElementById("textInput").classList.toggle("hidden", inputType !== "text");
    document
        .getElementById("videoInput")
        .classList.toggle("hidden", inputType !== "video");
}

document.getElementById("videoFile").addEventListener("change", () => {
    const videoFile = document.getElementById("videoFile").files[0];
    const preview = document.getElementById("videoPreview");
    const video = document.getElementById("previewVideo");
    if (videoFile) {
        video.src = URL.createObjectURL(videoFile);
        preview.classList.remove("hidden");
    } else {
        preview.classList.add("hidden");
    }
});

// Close modals when clicking backdrop
document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
    backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) {
            backdrop.classList.add("hidden");
        }
    });
});

// Escape key closes modals
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        document.querySelectorAll(".modal-backdrop").forEach((b) =>
            b.classList.add("hidden")
        );
    }
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

// -------------------- Boot --------------------

loadTools();
loadExamples();
refreshSavedList();
