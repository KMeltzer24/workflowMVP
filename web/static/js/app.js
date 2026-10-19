// Boot + settings + save/load. Vanilla JS, no bundler; scripts load in index.html order.
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

// -------------------- Save/Load workflows --------------------

document.getElementById("saveBtn").addEventListener("click", () => {
    const text = document.getElementById("workflowText").value.trim();
    if (!text) {
        toast("Nothing to save", "warning");
        return;
    }
    const nameInput = document.getElementById("saveName");
    const name = (nameInput && nameInput.value.trim()) || "";
    if (!name) {
        toast("Enter a name next to Save", "warning");
        if (nameInput) nameInput.focus();
        return;
    }
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
document.getElementById("copyCodeBtn").addEventListener("click", async () => {
    if (!state.generatedCode) return;
    try {
        await navigator.clipboard.writeText(state.generatedCode);
        toast("Copied generated Python", "success");
    } catch (_) {
        toast("Could not copy", "error");
    }
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

// -------------------- Boot --------------------

loadTools();
loadExamples();
refreshSavedList();
