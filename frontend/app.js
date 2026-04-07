async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return resp.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function isHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || "").trim());
}

function actionLinks(links) {
  const valid = links.filter((it) => it && it.url && isHttpUrl(it.url));
  if (!valid.length) return "";
  return `<div class="actions">${valid
    .map(
      (it) =>
        `<a class="btn-link" href="${escapeHtml(it.url)}" target="_blank" rel="noreferrer">${escapeHtml(it.label)}</a>`
    )
    .join("")}</div>`;
}

function renderCommunityOverview(data) {
  const root = document.getElementById("community-overview");
  if (!root) return;
  root.innerHTML = "";
  const kv = [
    ["仓库", data.repository || "-"],
    ["组织", data.organization || "-"],
    ["来源", data.source || "-"],
    ["Stars", String(data.stars ?? "-")],
    ["Forks", String(data.forks ?? "-")],
    ["Open Issues", String(data.open_issues ?? "-")],
    ["默认分支", data.default_branch || "-"],
  ];
  kv.forEach(([k, v]) => {
    const item = document.createElement("div");
    item.className = "kv-item";
    item.innerHTML = `<div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div>`;
    root.appendChild(item);
  });

  if (data.html_url && isHttpUrl(data.html_url)) {
    const jump = document.createElement("div");
    jump.className = "kv-item span-two";
    jump.innerHTML = `
      <div class="k">详情</div>
      <div class="v"><a href="${escapeHtml(data.html_url)}" target="_blank" rel="noreferrer">去 GitHub 查看</a></div>
    `;
    root.appendChild(jump);
  }
}

function renderIssues(data) {
  const root = document.getElementById("issues-list");
  if (!root) return;
  root.innerHTML = "";
  (data.items || []).slice(0, 8).forEach((it) => {
    const div = document.createElement("div");
    div.className = "item";
    const labels = (it.labels || []).map((x) => escapeHtml(x)).join(", ");
    const link =
      it.html_url && it.html_url !== "#"
        ? `<a href="${escapeHtml(it.html_url)}" target="_blank" rel="noreferrer">去 GitHub 查看</a>`
        : "";
    div.innerHTML = `
      <div class="title">#${escapeHtml(it.number)} ${escapeHtml(it.title || "-")}</div>
      <div class="meta">状态: ${escapeHtml(it.state || "-")} ${labels ? `| 标签: ${labels}` : ""} ${link ? `| ${link}` : ""}</div>
    `;
    root.appendChild(div);
  });
}

function renderOrgRepositories(data) {
  const root = document.getElementById("org-repos");
  if (!root) return;
  root.innerHTML = "";
  (data.items || []).slice(0, 12).forEach((repo) => {
    const div = document.createElement("div");
    div.className = "item module-card";
    div.innerHTML = `
      <div class="title">${escapeHtml(repo.full_name || repo.name || "-")}</div>
      <div class="meta">${escapeHtml(repo.description || "暂无描述")}</div>
      <div class="meta">语言: ${escapeHtml(repo.language || "-")} | Stars: ${escapeHtml(repo.stars ?? 0)} | Forks: ${escapeHtml(repo.forks ?? 0)}</div>
      ${actionLinks([{ label: "去 GitHub 查看", url: repo.html_url }])}
    `;
    root.appendChild(div);
  });
}

async function loadCommunity() {
  const [overview, issues, repos] = await Promise.allSettled([
    fetchJson("/api/community/overview"),
    fetchJson("/api/community/issues?state=open&per_page=20"),
    fetchJson("/api/community/org-repositories?org=openKG-field&per_page=30"),
  ]);
  renderCommunityOverview(overview.status === "fulfilled" ? overview.value : { source: "fallback" });
  renderIssues(issues.status === "fulfilled" ? issues.value : { items: [] });
  renderOrgRepositories(repos.status === "fulfilled" ? repos.value : { items: [] });
}

function renderLeaderboard(data) {
  const root = document.getElementById("leaderboard-list");
  if (!root) return;
  root.innerHTML = "";
  (data.items || []).forEach((item, index) => {
    const div = document.createElement("div");
    div.className = "item module-card";
    div.innerHTML = `
      <div class="title">#${index + 1} ${escapeHtml(item.task_id || "-")}</div>
      <div class="meta">模型: ${escapeHtml(item.model_name || "-")} | 指标: ${escapeHtml(item.metric || "-")} | 分数: ${escapeHtml(item.score ?? "-")}</div>
    `;
    root.appendChild(div);
  });
}

async function loadLeaderboard() {
  const data = await fetchJson("/api/benchmarks/leaderboard");
  renderLeaderboard(data);
}

function renderTaskboard(data) {
  const root = document.getElementById("taskboard-list");
  if (!root) return;
  root.innerHTML = "";
  (data.literature_taskboard || []).forEach((item) => {
    const div = document.createElement("div");
    div.className = "item module-card";
    div.innerHTML = `
      <div class="title">${escapeHtml(item.title || "-")}</div>
      <div class="meta">任务: ${escapeHtml(item.task || "-")} | 指标: ${escapeHtml(item.metric || "-")}</div>
      <div class="meta">数据集: ${escapeHtml(item.dataset || "-")} | Baseline: ${escapeHtml(item.baseline || "-")}</div>
      <div class="meta">${escapeHtml(item.paper_note || "")}</div>
      ${actionLinks([{ label: "去 GitHub 查看", url: item.github_url }])}
    `;
    root.appendChild(div);
  });
}

function renderAiFrontier(data) {
  const root = document.getElementById("ai-frontier-list");
  if (!root) return;
  root.innerHTML = "";
  (data.ai_frontier || []).forEach((item) => {
    const div = document.createElement("div");
    div.className = "item module-card";
    div.innerHTML = `
      <div class="title">${escapeHtml(item.title || "-")}</div>
      <div class="meta">类型: ${escapeHtml(item.type || "-")}</div>
      <div class="meta">${escapeHtml(item.summary || "")}</div>
      ${actionLinks([
        { label: "参考页面", url: item.reference_url },
        { label: "去 GitHub 查看", url: item.github_url },
      ])}
    `;
    root.appendChild(div);
  });
}

function renderOpenSharing(data) {
  const root = document.getElementById("open-sharing-list");
  if (!root) return;
  root.innerHTML = "";
  (data.open_source_sharing || []).forEach((item) => {
    const div = document.createElement("div");
    div.className = "item module-card";
    div.innerHTML = `
      <div class="title">${escapeHtml(item.title || "-")}</div>
      <div class="meta">分类: ${escapeHtml(item.category || "-")}</div>
      <div class="meta">${escapeHtml(item.description || "")}</div>
      ${actionLinks([
        { label: "去 GitHub 查看", url: item.github_url },
        { label: "补充资料", url: item.detail_url },
      ])}
    `;
    root.appendChild(div);
  });
}

function renderTopicForum(data) {
  const root = document.getElementById("topic-forum-list");
  if (!root) return;
  root.innerHTML = "";
  (data.topic_forum || []).forEach((item) => {
    const div = document.createElement("div");
    div.className = "item module-card";
    div.innerHTML = `
      <div class="title">${escapeHtml(item.topic || "-")}</div>
      <div class="meta">${escapeHtml(item.goal || "")}</div>
      ${actionLinks([
        { label: "参与讨论", url: item.discussion_url },
        { label: "提交 Issue", url: item.issue_url },
      ])}
    `;
    root.appendChild(div);
  });
}

function renderTaxonomy(data) {
  const root = document.getElementById("taxonomy-view");
  if (!root) return;
  const taxonomy = data.manager_taxonomy || {};
  const modules = (taxonomy.main_modules || []).map(escapeHtml).join(" / ") || "-";
  const axes = (taxonomy.task_axes || []).map(escapeHtml).join(" / ") || "-";
  const flow = (taxonomy.ingest_flow || []).map((x, i) => `${i + 1}. ${escapeHtml(x)}`).join("  ");
  root.innerHTML = `
    <div class="item">
      <div class="title">模块分层</div>
      <div class="meta">${modules}</div>
      <div class="title">任务维度</div>
      <div class="meta">${axes}</div>
      <div class="title">内容接入流程</div>
      <div class="meta">${flow}</div>
    </div>
  `;
}

function renderPdfHighlights(data) {
  const root = document.getElementById("pdf-highlights-list");
  if (!root) return;
  root.innerHTML = "";
  (data.pdf_research_highlights || []).forEach((item) => {
    const div = document.createElement("div");
    div.className = "item module-card";
    div.innerHTML = `
      <div class="title">${escapeHtml(item.title || "-")}</div>
      <div class="meta">模块: ${escapeHtml(item.module || "-")} | 来源: ${escapeHtml(item.source || "-")}</div>
      <div class="meta">${escapeHtml(item.summary || "")}</div>
      ${actionLinks([
        { label: "参考资料", url: item.reference_url },
        { label: "去 GitHub 查看", url: item.github_url },
      ])}
    `;
    root.appendChild(div);
  });
}

let readingDocsCache = [];
let knowledgeEntriesCache = [];
let linkageCache = [];

function normalizeText(value) {
  return String(value ?? "").toLowerCase().trim();
}

function renderReadingDoc(doc) {
  const toc = document.getElementById("reading-toc");
  const article = document.getElementById("reading-article");
  if (!toc || !article) return;

  if (!doc) {
    toc.innerHTML = `<div class="empty-hint">暂无阅读文档。</div>`;
    article.innerHTML = `<div class="empty-hint">请选择文档后查看内容。</div>`;
    return;
  }

  const sections = Array.isArray(doc.sections) ? doc.sections : [];
  toc.innerHTML = sections
    .map((sec, idx) => {
      const anchor = `rd-${doc.id || "doc"}-${sec.id || idx}`;
      return `<a href="#${escapeHtml(anchor)}">${idx + 1}. ${escapeHtml(sec.title || "未命名章节")}</a>`;
    })
    .join("");

  article.innerHTML = `
    <h3 class="doc-title">${escapeHtml(doc.title || "-")}</h3>
    <p class="doc-subtitle">${escapeHtml(doc.subtitle || "")} | 来源：${escapeHtml(doc.source || "-")} | 更新：${escapeHtml(doc.updated_at || "-")}</p>
    ${sections
      .map((sec, idx) => {
        const anchor = `rd-${doc.id || "doc"}-${sec.id || idx}`;
        const highlights = Array.isArray(sec.highlights) ? sec.highlights : [];
        const refs = Array.isArray(sec.references) ? sec.references : [];
        return `
          <section class="reading-section" id="${escapeHtml(anchor)}">
            <h4>${idx + 1}. ${escapeHtml(sec.title || "-")}</h4>
            <p>${escapeHtml(sec.body || "")}</p>
            ${
              highlights.length
                ? `<ul class="reading-list">${highlights.map((h) => `<li>${escapeHtml(h)}</li>`).join("")}</ul>`
                : ""
            }
            ${actionLinks(refs.map((r) => ({ label: r.label || "参考链接", url: r.url })))}
          </section>
        `;
      })
      .join("")}
  `;
}

function initReadingDocs(docs) {
  const select = document.getElementById("reading-doc-select");
  if (!select) return;
  readingDocsCache = Array.isArray(docs) ? docs : [];
  select.innerHTML = "";
  readingDocsCache.forEach((doc) => {
    const op = document.createElement("option");
    op.value = String(doc.id || "");
    op.textContent = doc.title || "未命名文档";
    select.appendChild(op);
  });
  renderReadingDoc(readingDocsCache[0]);
}

function bindReadingDocChange() {
  const select = document.getElementById("reading-doc-select");
  if (!select) return;
  select.addEventListener("change", () => {
    const target = readingDocsCache.find((doc) => String(doc.id || "") === select.value) || readingDocsCache[0];
    renderReadingDoc(target);
  });
}

function renderKnowledgeRows(rows) {
  const body = document.getElementById("knowledge-table-body");
  if (!body) return;
  body.innerHTML = "";
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7"><div class="empty-hint">没有匹配条目。</div></td></tr>`;
    return;
  }
  rows.forEach((row) => {
    const tags = Array.isArray(row.tags) ? row.tags : [];
    const statusClass = normalizeText(row.status || "active");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.module || "-")}</td>
      <td>${escapeHtml(row.type || "-")}</td>
      <td>${escapeHtml(row.title || "-")}</td>
      <td><div class="tag-set">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div></td>
      <td><span class="status-pill ${escapeHtml(statusClass)}">${escapeHtml(row.status || "-")}</span></td>
      <td>${escapeHtml(row.updated_at || "-")}</td>
      <td>${isHttpUrl(row.url) ? `<a class="btn-link" href="${escapeHtml(row.url)}" target="_blank" rel="noreferrer">查看</a>` : "-"}</td>
    `;
    body.appendChild(tr);
  });
}

function applyKnowledgeFilters() {
  const moduleSelect = document.getElementById("knowledge-module-filter");
  const typeSelect = document.getElementById("knowledge-type-filter");
  const keywordInput = document.getElementById("knowledge-keyword");
  if (!moduleSelect || !typeSelect || !keywordInput) return;

  const moduleValue = moduleSelect.value;
  const typeValue = typeSelect.value;
  const keyword = normalizeText(keywordInput.value);
  const rows = knowledgeEntriesCache.filter((row) => {
    if (moduleValue !== "all" && row.module !== moduleValue) return false;
    if (typeValue !== "all" && row.type !== typeValue) return false;
    if (!keyword) return true;
    const haystack = normalizeText([
      row.title,
      row.module,
      row.type,
      row.source,
      ...(Array.isArray(row.tags) ? row.tags : []),
    ].join(" "));
    return haystack.includes(keyword);
  });
  renderKnowledgeRows(rows);
}

function initKnowledgeEntries(items) {
  const moduleSelect = document.getElementById("knowledge-module-filter");
  const typeSelect = document.getElementById("knowledge-type-filter");
  if (!moduleSelect || !typeSelect) return;

  knowledgeEntriesCache = Array.isArray(items) ? items : [];
  const modules = Array.from(new Set(knowledgeEntriesCache.map((x) => x.module).filter(Boolean)));
  const types = Array.from(new Set(knowledgeEntriesCache.map((x) => x.type).filter(Boolean)));

  moduleSelect.innerHTML = `<option value="all">全部模块</option>${modules
    .map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`)
    .join("")}`;
  typeSelect.innerHTML = `<option value="all">全部类型</option>${types
    .map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`)
    .join("")}`;
  applyKnowledgeFilters();
}

function bindKnowledgeFilters() {
  ["knowledge-module-filter", "knowledge-type-filter", "knowledge-keyword"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", applyKnowledgeFilters);
    el.addEventListener("change", applyKnowledgeFilters);
  });
}

function renderLinkageRows(rows) {
  const root = document.getElementById("linkage-canvas");
  if (!root) return;
  root.innerHTML = "";
  if (!rows.length) {
    root.innerHTML = `<div class="empty-hint">当前筛选条件下没有联动记录。</div>`;
    return;
  }
  rows.forEach((row) => {
    const div = document.createElement("div");
    div.innerHTML = `
      <div class="linkage-row">
        <div class="linkage-node">
          <div class="label">研究条目</div>
          <div class="name">${escapeHtml(row.paper || "-")}</div>
          ${isHttpUrl(row.paper_url) ? `<div class="actions"><a class="btn-link" href="${escapeHtml(row.paper_url)}" target="_blank" rel="noreferrer">条目链接</a></div>` : ""}
        </div>
        <div class="linkage-edge">→</div>
        <div class="linkage-node">
          <div class="label">项目</div>
          <div class="name">${escapeHtml(row.project || "-")}</div>
          ${isHttpUrl(row.project_url) ? `<div class="actions"><a class="btn-link" href="${escapeHtml(row.project_url)}" target="_blank" rel="noreferrer">项目链接</a></div>` : ""}
        </div>
        <div class="linkage-edge">→</div>
        <div class="linkage-node">
          <div class="label">数据集</div>
          <div class="name">${escapeHtml(row.dataset || "-")}</div>
          ${isHttpUrl(row.dataset_url) ? `<div class="actions"><a class="btn-link" href="${escapeHtml(row.dataset_url)}" target="_blank" rel="noreferrer">数据集链接</a></div>` : ""}
        </div>
      </div>
      <div class="linkage-meta">任务: ${escapeHtml(row.task || "-")} | 指标: ${escapeHtml(row.benchmark || "-")}</div>
    `;
    root.appendChild(div);
  });
}

function applyLinkageFilters() {
  const paperSelect = document.getElementById("linkage-paper-filter");
  const taskSelect = document.getElementById("linkage-task-filter");
  if (!paperSelect || !taskSelect) return;

  const paper = paperSelect.value;
  const task = taskSelect.value;
  const rows = linkageCache.filter((row) => {
    if (paper !== "all" && row.paper !== paper) return false;
    if (task !== "all" && row.task !== task) return false;
    return true;
  });
  renderLinkageRows(rows);
}

function initLinkageMap(items) {
  const paperSelect = document.getElementById("linkage-paper-filter");
  const taskSelect = document.getElementById("linkage-task-filter");
  if (!paperSelect || !taskSelect) return;

  linkageCache = Array.isArray(items) ? items : [];
  const papers = Array.from(new Set(linkageCache.map((x) => x.paper).filter(Boolean)));
  const tasks = Array.from(new Set(linkageCache.map((x) => x.task).filter(Boolean)));
  paperSelect.innerHTML = `<option value="all">全部研究条目</option>${papers
    .map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
    .join("")}`;
  taskSelect.innerHTML = `<option value="all">全部任务</option>${tasks
    .map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`)
    .join("")}`;
  applyLinkageFilters();
}

function bindLinkageFilters() {
  ["linkage-paper-filter", "linkage-task-filter"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", applyLinkageFilters);
  });
}

async function askAssistant() {
  const input = document.getElementById("llm-input");
  const output = document.getElementById("llm-output");
  const btn = document.getElementById("ask-llm-btn");
  if (!input || !output || !btn) return;

  const text = input.value.trim();
  if (!text) {
    output.textContent = "请先输入要整理的问题或内容。";
    return;
  }

  btn.disabled = true;
  output.textContent = "正在生成建议，请稍候…";

  const payload = {
    messages: [
      {
        role: "system",
        content:
          "你是开源知识社区助手。请输出可直接用于社区发布的中文建议，优先给出：1) 三行摘要；2) 推荐标签；3) 下一步动作。",
      },
      { role: "user", content: text },
    ],
    temperature: 0.25,
    max_tokens: 900,
  };

  try {
    let data;
    try {
      data = await fetchJson("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      if (String(err).includes("404")) {
        data = await fetchJson("/api/llm/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        throw err;
      }
    }

    const textResp = data.response || data.content || data.answer || "模型暂时没有返回内容，请稍后重试。";
    const suffix = data.source ? `\n\n来源：${data.source}` : "";
    output.textContent = `${textResp}${suffix}`;
  } catch (err) {
    output.textContent = `请求失败：${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

function bindAssistant() {
  const btn = document.getElementById("ask-llm-btn");
  const input = document.getElementById("llm-input");
  if (!btn || !input) return;

  btn.addEventListener("click", askAssistant);
  input.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      askAssistant();
    }
  });
}

async function loadResources() {
  const data = await fetchJson("/api/resources/catalog");
  renderTaskboard(data);
  renderAiFrontier(data);
  renderOpenSharing(data);
  renderTopicForum(data);
  renderTaxonomy(data);
  renderPdfHighlights(data);
  initReadingDocs(data.reading_docs || []);
  initKnowledgeEntries(data.knowledge_entries || []);
  initLinkageMap(data.paper_project_dataset_links || []);
}

window.addEventListener("DOMContentLoaded", async () => {
  bindReadingDocChange();
  bindKnowledgeFilters();
  bindLinkageFilters();
  bindAssistant();

  try {
    await Promise.all([loadCommunity(), loadLeaderboard(), loadResources()]);
  } catch (err) {
    console.error(err);
  }
});

