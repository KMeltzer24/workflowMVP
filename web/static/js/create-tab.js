// Create tab: parse, edit steps, generate
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
    startParseProgress("Parsing workflow");
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
        state.parseAiRepair = data.ai_repair || null;
        state.parseSeconds = parseDurationSeconds(data);
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
    } finally {
        stopParseProgress();
    }
}

async function parseVideoWorkflow(videoFile) {
    toast("Processing video (this can take a moment)...");
    startParseProgress("Processing video");
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
        state.parseAiRepair = data.ai_repair || null;
        state.parseSeconds = parseDurationSeconds(data);
        displaySteps(data.steps);
        renderParseInsights();
        enableGenerate(true);
        toast(`Parsed ${data.steps.length} steps from video`, "success");
    } catch (err) {
        toast(`Video parse error: ${err.message}`, "error");
    } finally {
        stopParseProgress();
    }
}

function parseDurationSeconds(data) {
    const serverSeconds = Number(data?.parse_seconds);
    if (Number.isFinite(serverSeconds)) return serverSeconds;
    if (state.parseStartMs == null) return null;
    return (Date.now() - state.parseStartMs) / 1000;
}

function startParseProgress(label) {
    const btn = document.getElementById("parseBtn");
    if (!btn) return;
    btn.dataset.prevLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = `${label}... 0s`;
    state.parseStartMs = Date.now();
    state.parseTimerId = window.setInterval(() => {
        if (state.parseStartMs == null) return;
        btn.textContent = `${label}... ${formatGenerateElapsed(Date.now() - state.parseStartMs)}`;
    }, 250);
}

function stopParseProgress() {
    if (state.parseTimerId != null) {
        window.clearInterval(state.parseTimerId);
        state.parseTimerId = null;
    }
    state.parseStartMs = null;
    const btn = document.getElementById("parseBtn");
    if (!btn) return;
    btn.disabled = false;
    const prev = btn.dataset.prevLabel;
    if (prev) {
        btn.textContent = prev;
        delete btn.dataset.prevLabel;
    }
}

function enableGenerate(enabled) {
    const btn = document.getElementById("generateBtn");
    btn.disabled = !enabled;
    btn.textContent = "Generate Python";
}

function showGeneratedCode(code, path) {
    const view = document.getElementById("generatedCode");
    const meta = document.getElementById("codeMeta");
    const copyBtn = document.getElementById("copyCodeBtn");
    state.generatedCode = code || "";
    if (!view) return;
    if (state.generatedCode) {
        view.textContent = state.generatedCode;
    } else {
        view.innerHTML = '<span class="empty-hint">No script yet.</span>';
    }
    if (meta) {
        meta.textContent = path
            ? `Saved as ${path}`
            : "Generate a script to inspect it before running.";
    }
    if (copyBtn) copyBtn.disabled = !state.generatedCode;
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
            generateBtn.textContent = "Generate Python (modified)";
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
    const duration = formatGenerationWallClockSeconds(state.parseSeconds);
    const reasons = Array.isArray(c.reasons) ? c.reasons.slice(0, 3) : [];
    const repair = state.parseAiRepair;
    const repairMessage = repair?.needed && !state.parseAiAssisted
        ? repair.error
            ? "Using rule-first parse; AI cleanup could not improve these steps."
            : repair.attempted
                ? "Using rule-first parse; AI cleanup did not change the result."
                : "Using rule-first parse."
        : "";
    box.innerHTML = `
        <strong>Parse quality:</strong> ${scorePct}% (${mode})
        ${duration ? `<div class="hint">Parsed in ${escapeHtml(duration)}</div>` : ""}
        <div class="hint">Custom steps: ${c.custom_steps || 0}, missing-param steps: ${c.missing_param_steps || 0}</div>
        ${repairMessage ? `<div class="hint">${escapeHtml(repairMessage)}</div>` : ""}
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

function formatGenerationWallClockSeconds(sec) {
    const n = Number(sec);
    if (sec == null || Number.isNaN(n)) return null;
    if (n < 60) {
        return `${n < 10 ? n.toFixed(2) : n.toFixed(1)}s`;
    }
    const m = Math.floor(n / 60);
    const r = n - m * 60;
    return `${m}m ${r.toFixed(0)}s`;
}

function updateRunSummary() {
    const el = document.getElementById("runMeta");
    if (!el) return;
    const path = state.currentWorkflowPath;
    if (!path) {
        el.textContent =
            "Generate Python code from a parsed workflow to enable the run button.";
        return;
    }
    const formatted = formatGenerationWallClockSeconds(state.lastGenerationSeconds);
    const tail = formatted ? ` — generated in ${formatted} (Gemini)` : "";
    el.textContent = `Ready to run: ${path}${tail}.`;
}

function formatGenerateElapsed(ms) {
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const r = s - m * 60;
    return `${m}m ${r}s`;
}

function startGenerateProgress() {
    const btn = document.getElementById("generateBtn");
    const status = document.getElementById("generateStatus");
    if (!btn) return;
    btn.dataset.prevLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generating…";
    if (status) {
        status.textContent = "Calling the model and validating Python… 0s";
        status.classList.remove("hidden");
        status.classList.add("is-active");
    }
    state.generateStartMs = Date.now();
    state.generateTimerId = window.setInterval(() => {
        if (!status || state.generateStartMs == null) return;
        const elapsed = Date.now() - state.generateStartMs;
        status.textContent = `Calling the model and validating Python… ${formatGenerateElapsed(elapsed)}`;
    }, 250);
}

function stopGenerateProgress() {
    if (state.generateTimerId != null) {
        window.clearInterval(state.generateTimerId);
        state.generateTimerId = null;
    }
    state.generateStartMs = null;
    const btn = document.getElementById("generateBtn");
    const status = document.getElementById("generateStatus");
    if (btn) {
        btn.disabled = false;
        const prev = btn.dataset.prevLabel;
        if (prev) {
            btn.textContent = prev;
            delete btn.dataset.prevLabel;
        }
    }
    if (status && status.classList.contains("is-active")) {
        status.classList.add("hidden");
        status.classList.remove("is-active");
        status.textContent = "";
    }
}

function formatValidationIssue(issue) {
    if (!issue || typeof issue !== "object") return "";
    const parts = [];
    if (issue.step_id) parts.push(issue.step_id);
    if (issue.field) parts.push(issue.field);
    const prefix = parts.length ? `${parts.join(" · ")}: ` : "";
    return `${prefix}${issue.message || "Invalid step"}`;
}

function formatGenerationFailure(data) {
    const base = data?.error || "Generation failed";
    const errors = Array.isArray(data?.validation_errors)
        ? data.validation_errors.map(formatValidationIssue).filter(Boolean)
        : [];
    const repairError = data?.ai_repair?.error
        ? `AI cleanup failed: ${data.ai_repair.error}`
        : "";
    const details = [...errors, repairError].filter(Boolean);
    if (!details.length) return base;
    return `${base}\n${details.join("\n")}`;
}

function showGenerateFailure(data) {
    const message = formatGenerationFailure(data);
    const status = document.getElementById("generateStatus");
    if (status) {
        status.classList.remove("hidden", "is-active");
        status.textContent = message;
    }
    toast(message.split("\n")[0], "error");
}

async function generateWorkflow() {
    if (!state.parsedSteps.length) {
        toast("Parse a workflow first", "warning");
        return;
    }
    toast("Generating Python code...");
    startGenerateProgress();
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
            showGenerateFailure(data);
            return;
        }
        state.currentWorkflowPath = data.output_path;
        const gs = data.generation_seconds;
        const sec = typeof gs === "number" ? gs : parseFloat(gs);
        state.lastGenerationSeconds = Number.isFinite(sec) ? sec : null;
        showGeneratedCode(data.code || "", data.output_path);
        document.getElementById("runBtn").disabled = false;
        updateRunSummary();
        toast("Python code generated", "success");
        activateTab("workspace");
    } catch (err) {
        toast(`Generate error: ${err.message}`, "error");
    } finally {
        stopGenerateProgress();
    }
}
