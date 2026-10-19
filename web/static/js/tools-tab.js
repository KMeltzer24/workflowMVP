// Tools tab
// -------------------- Initial data --------------------

async function loadTools() {
    try {
        const response = await fetch("/api/tools");
        const tools = await response.json();
        state.tools = Array.isArray(tools) ? tools : [];
        buildToolCategoryOptions(state.tools);
        renderTools();
        const note = document.getElementById("toolRegistryTotalNote");
        if (note) {
            const n = state.tools.length;
            note.textContent = `${n === 1 ? "1 builtin registered" : `${n} builtins registered`}`;
        }
    } catch (err) {
        toast(`Could not load tools: ${err.message}`, "error");
    }
}

function buildToolCategoryOptions(tools) {
    const select = document.getElementById("toolCategorySelect");
    if (!select) return;
    const categories = new Set(["all"]);
    for (const tool of tools) {
        categories.add(toolCategory(tool));
    }
    const ordered = Array.from(categories).sort((a, b) => {
        if (a === "all") return -1;
        if (b === "all") return 1;
        return a.localeCompare(b);
    });
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
        const matchesCategory = category === "all" || toolCategory(tool) === category;
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

function toolCategory(tool) {
    if (tool && typeof tool === "object" && tool.category) {
        return String(tool.category);
    }
    const name = tool && typeof tool === "object" ? tool.name : tool;
    const n = String(name || "").toLowerCase();
    if (n === "generate_text") return "ai";
    if (n === "fetch_stock_price") return "finance";
    if (n === "http_request") return "network";
    if (n === "read_json" || n === "write_json") return "data";
    if (n === "append_file") return "filesystem";
    if (n === "hash_file") return "filesystem";
    if (n === "get_current_time") return "datetime";
    if (n.includes("email") || n.includes("notification")) return "communication";
    if (n.includes("csv") || n.includes("json") || n.includes("analyze") || n.includes("process_data")) return "data";
    if (n.includes("sqlite") || n.includes("query") || n.includes("insert")) return "database";
    if (n.includes("download") || n.includes("scrape")) return "network";
    if (n.includes("compress") || n.includes("archive")) return "archive";
    if (n.includes("file") || n.includes("directory") || n.includes("copy") || n.includes("move") || n.includes("delete") || n.includes("read") || n.includes("write") || n.includes("list")) return "filesystem";
    if (n.includes("command") || n.includes("wait")) return "system";
    return "general";
}
