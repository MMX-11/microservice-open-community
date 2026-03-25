async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return resp.json();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderCommunityOverview(data) {
  const root = document.getElementById("community-overview");
  root.innerHTML = "";
  const kv = [
    ["仓库", data.repository || "-"],
    ["来源", data.source || "-"],
    ["Stars", String(data.stars ?? "-")],
    ["Forks", String(data.forks ?? "-")],
    ["Open Issues", String(data.open_issues ?? "-")],
    ["默认分支", data.default_branch || "-"],
  ];
  kv.forEach(([k, v]) => {
    const item = document.createElement("div");
    item.className = "kv-item";
    item.innerHTML = `<div class="k">${k}</div><div class="v">${v}</div>`;
    root.appendChild(item);
  });
}

function renderIssues(data) {
  const root = document.getElementById("issues-list");
  root.innerHTML = "";
  (data.items || []).slice(0, 8).forEach((it) => {
    const div = document.createElement("div");
    div.className = "item";
    const labels = (it.labels || []).join(", ");
    const link = it.html_url && it.html_url !== "#" ? `<a href="${it.html_url}" target="_blank" rel="noreferrer">查看</a>` : "";
    div.innerHTML = `
      <div class="title">#${it.number} ${it.title || "-"}</div>
      <div class="meta">状态: ${it.state || "-"} ${labels ? `| 标签: ${labels}` : ""} ${link ? `| ${link}` : ""}</div>
    `;
    root.appendChild(div);
  });
}

async function loadCommunity() {
  const [overview, issues] = await Promise.all([
    fetchJson("/api/community/overview"),
    fetchJson("/api/community/issues?state=open&per_page=20"),
  ]);
  renderCommunityOverview(overview);
  renderIssues(issues);
}

async function loadTasks() {
  const data = await fetchJson("/api/benchmarks/tasks");
  const select = document.getElementById("task-select");
  select.innerHTML = "";
  (data.tasks || []).forEach((task) => {
    const op = document.createElement("option");
    op.value = task.id;
    op.textContent = `${task.name} (${task.metric})`;
    select.appendChild(op);
  });
}

async function runBenchmark() {
  const taskId = document.getElementById("task-select").value;
  const predictions = document
    .getElementById("predictions")
    .value.split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);
  const references = document
    .getElementById("references")
    .value.split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);

  const payload = {
    task_id: taskId,
    predictions,
    references,
    model_name: "ui-submitted-model",
    run_name: "ui-manual-run",
  };

  const out = document.getElementById("eval-output");
  out.textContent = "评测中...";
  try {
    const data = await fetchJson("/api/benchmarks/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    out.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    out.textContent = String(err);
  }
}

async function askLLM() {
  const input = document.getElementById("llm-input").value.trim();
  if (!input) {
    setText("llm-output", "请输入问题后再发送。");
    return;
  }

  const payload = {
    model: "platform-default",
    messages: [
      { role: "system", content: "你是专利领域评测平台助手。" },
      { role: "user", content: input },
    ],
  };
  const out = document.getElementById("llm-output");
  out.textContent = "请求中...";
  try {
    const data = await fetchJson("/api/llm/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    out.textContent = `${data.response || ""}\n\n[来源: ${data.source || "-"}]`;
  } catch (err) {
    out.textContent = String(err);
  }
}

function renderResources(data) {
  const root = document.getElementById("resource-list");
  root.innerHTML = "";
  ["platforms", "datasets", "tasks"].forEach((section) => {
    const items = data[section] || [];
    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "item";
      const title = item.name || item.task_id || "-";
      const meta = item.role || item.metric || item.license || "";
      const link = item.url ? `<a href="${item.url}" target="_blank" rel="noreferrer">访问</a>` : "";
      div.innerHTML = `<div class="title">${title}</div><div class="meta">${meta} ${link ? `| ${link}` : ""}</div>`;
      root.appendChild(div);
    });
  });
}

async function loadResources() {
  const data = await fetchJson("/api/resources/catalog");
  renderResources(data);
}

window.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("run-eval-btn").addEventListener("click", runBenchmark);
  document.getElementById("ask-llm-btn").addEventListener("click", askLLM);

  try {
    await Promise.all([loadCommunity(), loadTasks(), loadResources()]);
  } catch (err) {
    console.error(err);
    setText("eval-output", `初始化失败: ${err}`);
  }
});

