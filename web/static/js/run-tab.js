// Run tab: SSE streaming + missing-credential prompt
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
