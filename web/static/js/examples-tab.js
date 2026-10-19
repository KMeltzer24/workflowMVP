// Examples tab
async function loadExamples() {
    try {
        const response = await fetch("/api/examples");
        const examples = await response.json();
        const host = document.getElementById("examples");
        if (!host) return;
        host.innerHTML = "";
        const pill = document.getElementById("examplesCountPill");
        if (pill) {
            const n = Array.isArray(examples) ? examples.length : 0;
            pill.textContent = n === 1 ? "1 starter workflow" : `${n} starter workflows`;
        }
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
