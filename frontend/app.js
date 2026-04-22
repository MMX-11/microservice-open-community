const PAGE_SIZE = 12;

const state = {
  allItems: [],
  filtered: [],
  page: 1,
  search: "",
  module: "all",
  tag: "",
  status: "all",
  sort: "updated_desc",
};

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

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return resp.json();
}

function formatGatewayError(err) {
  const raw = String(err?.message || err || "").trim();
  if (!raw) return "服务暂时不可用，请稍后重试。";
  const detailMatch = raw.match(/:\s*(\{[\s\S]*\})$/);
  if (detailMatch?.[1]) {
    try {
      const parsed = JSON.parse(detailMatch[1]);
      if (parsed && typeof parsed.detail === "string" && parsed.detail.trim()) {
        return parsed.detail.trim();
      }
    } catch (_ignored) {
      // ignore
    }
  }
  if (/Resource service unavailable/i.test(raw) || /HTTP Error 400/i.test(raw) || /HTTP Error 5\d\d/i.test(raw)) {
    return "资源服务暂时不可用，请稍后重试或检查 resource-service 状态。";
  }
  return raw.length > 160 ? `${raw.slice(0, 160)}...` : raw;
}

function toEpochMs(value) {
  const t = new Date(value || "").getTime();
  return Number.isFinite(t) ? t : 0;
}

function formatDateTime(value) {
  const d = new Date(value || "");
  if (Number.isNaN(d.getTime())) return "-";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function getDomain(url) {
  try {
    return new URL(String(url || "")).host || "community";
  } catch {
    return "community";
  }
}

function normalizeCommunityItem(item) {
  return {
    id: `c-${item.id || Math.random().toString(36).slice(2)}`,
    title: item.title || "未命名活动",
    summary: item.summary || "",
    url: item.url || "",
    module: item.module || "未分类",
    tags: [],
    status: "published",
    source: item.source || "community_item",
    created_at: item.created_at || item.updated_at || "",
    updated_at: item.updated_at || item.created_at || "",
    kind: "community",
  };
}

function normalizeBlogItem(post) {
  return {
    id: `b-${post.id || Math.random().toString(36).slice(2)}`,
    title: post.title || "未命名博客",
    summary: post.summary || post.excerpt || "",
    url: post.share_url || "",
    module: "博客",
    tags: Array.isArray(post.tags) ? post.tags : [],
    status: post.status || "published",
    source: post.source || "blog_post",
    created_at: post.created_at || post.updated_at || "",
    updated_at: post.updated_at || post.created_at || "",
    kind: "blog",
  };
}

function collectTags(items) {
  const tagSet = new Set();
  items.forEach((item) => {
    (item.tags || []).forEach((tag) => {
      const t = String(tag || "").trim();
      if (t) tagSet.add(t);
    });
  });
  return Array.from(tagSet).slice(0, 80);
}

function renderTagFilters(items) {
  const root = document.getElementById("tag-filter-list");
  if (!root) return;
  root.innerHTML = "";
  const tags = collectTags(items);
  if (!tags.length) {
    root.innerHTML = '<div class="empty-hint">暂无标签</div>';
    return;
  }
  tags.forEach((tag) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = tag;
    if (state.tag === tag) btn.classList.add("is-active");
    btn.addEventListener("click", () => {
      state.tag = state.tag === tag ? "" : tag;
      state.page = 1;
      applyFiltersAndRender();
    });
    root.appendChild(btn);
  });
}

function sortItems(items, sortMode) {
  const rows = [...items];
  if (sortMode === "created_desc") {
    rows.sort((a, b) => toEpochMs(b.created_at) - toEpochMs(a.created_at));
    return rows;
  }
  if (sortMode === "title_asc") {
    rows.sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), "zh-CN"));
    return rows;
  }
  rows.sort((a, b) => toEpochMs(b.updated_at || b.created_at) - toEpochMs(a.updated_at || a.created_at));
  return rows;
}

function updateSelectedHint() {
  const countEl = document.getElementById("selected-count");
  const detailEl = document.getElementById("selected-detail");
  const picks = [];
  if (state.search) picks.push(`关键词: ${state.search}`);
  if (state.module !== "all") picks.push(`模块: ${state.module}`);
  if (state.status !== "all") picks.push(`状态: ${state.status === "published" ? "已发布" : "草稿"}`);
  if (state.tag) picks.push(`标签: ${state.tag}`);

  if (countEl) countEl.textContent = String(picks.length);
  if (detailEl) detailEl.textContent = picks.length ? picks.join(" | ") : "当前未设置筛选条件";
}

function renderPagination() {
  const totalPages = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
  const indicator = document.getElementById("page-indicator");
  const prevBtn = document.getElementById("page-prev-btn");
  const nextBtn = document.getElementById("page-next-btn");

  if (state.page > totalPages) state.page = totalPages;
  if (indicator) indicator.textContent = `第 ${state.page} / ${totalPages} 页`;
  if (prevBtn) prevBtn.disabled = state.page <= 1;
  if (nextBtn) nextBtn.disabled = state.page >= totalPages;
}

function renderEventCards() {
  const root = document.getElementById("event-list");
  if (!root) return;
  root.innerHTML = "";

  if (!state.filtered.length) {
    root.innerHTML = '<div class="empty-hint">没有匹配活动，请调整筛选条件。</div>';
    renderPagination();
    return;
  }

  const start = (state.page - 1) * PAGE_SIZE;
  const rows = state.filtered.slice(start, start + PAGE_SIZE);

  rows.forEach((item) => {
    const statusLabel = item.status === "draft" ? "草稿" : "已发布";
    const card = document.createElement("article");
    card.className = "event-card";
    card.innerHTML = `
      <div class="event-cover">
        <span class="event-badge ${item.status === "draft" ? "is-draft" : "is-published"}">${escapeHtml(statusLabel)}</span>
        <div class="event-domain">${escapeHtml(getDomain(item.url))}</div>
      </div>
      <div class="event-main">
        <div class="event-meta">
          <span>${escapeHtml(item.module)}</span>
          <span>${escapeHtml(item.source)}</span>
          <span>${escapeHtml(formatDateTime(item.updated_at || item.created_at))}</span>
        </div>
        <h3 class="event-title">${escapeHtml(item.title)}</h3>
        <p class="event-summary">${escapeHtml(item.summary || "暂无摘要，建议补充活动亮点。")}</p>
        <div class="event-tags">
          ${(item.tags || []).slice(0, 4).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}
        </div>
        <div class="event-actions">
          ${isHttpUrl(item.url) ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">查看详情</a>` : '<button type="button" disabled>暂无链接</button>'}
        </div>
      </div>
    `;
    root.appendChild(card);
  });

  renderPagination();
}

function applyFiltersAndRender() {
  const q = state.search.trim().toLowerCase();
  const rows = state.allItems.filter((item) => {
    if (state.module !== "all" && item.module !== state.module) return false;
    if (state.status !== "all" && item.status !== state.status) return false;
    if (state.tag && !(item.tags || []).includes(state.tag)) return false;
    if (!q) return true;
    const haystack = [item.title, item.summary, item.module, item.source, ...(item.tags || [])]
      .join(" ")
      .toLowerCase();
    return haystack.includes(q);
  });
  state.filtered = sortItems(rows, state.sort);

  document.querySelectorAll("#module-tabs button").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.module === state.module);
  });

  updateSelectedHint();
  renderTagFilters(state.allItems);
  renderEventCards();
}

function bindFilters() {
  const searchInput = document.getElementById("global-search-input");
  const searchBtn = document.getElementById("global-search-btn");
  const statusSelect = document.getElementById("status-select");
  const sortSelect = document.getElementById("sort-select");
  const resetBtn = document.getElementById("reset-filters-btn");
  const prevBtn = document.getElementById("page-prev-btn");
  const nextBtn = document.getElementById("page-next-btn");

  searchBtn?.addEventListener("click", () => {
    state.search = String(searchInput?.value || "").trim();
    state.page = 1;
    applyFiltersAndRender();
  });

  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      state.search = String(searchInput.value || "").trim();
      state.page = 1;
      applyFiltersAndRender();
    }
  });

  statusSelect?.addEventListener("change", () => {
    state.status = String(statusSelect.value || "all");
    state.page = 1;
    applyFiltersAndRender();
  });

  sortSelect?.addEventListener("change", () => {
    state.sort = String(sortSelect.value || "updated_desc");
    state.page = 1;
    applyFiltersAndRender();
  });

  resetBtn?.addEventListener("click", () => {
    state.search = "";
    state.module = "all";
    state.tag = "";
    state.status = "all";
    state.sort = "updated_desc";
    state.page = 1;
    if (searchInput) searchInput.value = "";
    if (statusSelect) statusSelect.value = "all";
    if (sortSelect) sortSelect.value = "updated_desc";
    applyFiltersAndRender();
  });

  prevBtn?.addEventListener("click", () => {
    if (state.page <= 1) return;
    state.page -= 1;
    renderEventCards();
  });

  nextBtn?.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
    if (state.page >= totalPages) return;
    state.page += 1;
    renderEventCards();
  });

  document.querySelectorAll("#module-tabs button[data-module]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.module = String(btn.dataset.module || "all");
      state.page = 1;
      applyFiltersAndRender();
    });
  });
}

async function loadTeamHealthBanner() {
  const banner = document.getElementById("team-load-alert");
  if (!banner) return;
  banner.hidden = true;
  try {
    await fetchJson("/api/resources/community-items?module=团队模块&limit=1");
  } catch (err) {
    banner.textContent = `团队模块加载失败：${formatGatewayError(err)}`;
    banner.hidden = false;
  }
}

async function runMaintenanceAgent() {
  const input = document.getElementById("assistant-focus-input");
  const output = document.getElementById("llm-output");
  const btn = document.getElementById("run-maintenance-agent-btn");
  if (!output) return;

  const focus = String(input?.value || "").trim() || "请按社区日常维护标准做一次巡检，并输出本周可执行待办。";
  const oldText = btn?.textContent || "运行社区维护智能体";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "巡检中...";
  }
  output.textContent = "社区维护智能体正在巡检，请稍候...";

  try {
    const data = await fetchJson("/api/assistant/maintain-community", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ focus }),
    });
    const report = data.maintenance_markdown || data.community_markdown || data.response || "未返回巡检报告。";
    const suffix = data.source ? `\n\n[来源: ${data.source}]` : "";
    output.textContent = `${report}${suffix}`;
  } catch (err) {
    output.textContent = `社区维护智能体执行失败：${formatGatewayError(err)}`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }
}

async function askAssistantQuick() {
  const input = document.getElementById("assistant-focus-input");
  const output = document.getElementById("llm-output");
  const btn = document.getElementById("ask-llm-btn");
  if (!output) return;

  const text = String(input?.value || "").trim();
  if (!text) {
    output.textContent = "请先输入你的问题。";
    return;
  }

  const oldText = btn?.textContent || "快速问答";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "生成中...";
  }
  output.textContent = "正在生成建议...";

  try {
    const data = await fetchJson("/api/assistant/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: [
          {
            role: "system",
            content: "你是社区助手。请简短回答，并给出 3 条可执行建议。",
          },
          { role: "user", content: text },
        ],
        temperature: 0.25,
        max_tokens: 800,
      }),
    });
    const answer = data.response || data.content || data.answer || "暂无返回内容。";
    const suffix = data.source ? `\n\n[来源: ${data.source}]` : "";
    output.textContent = `${answer}${suffix}`;
  } catch (err) {
    output.textContent = `问答失败：${formatGatewayError(err)}`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }
}

function bindAssistantPanel() {
  const fab = document.getElementById("assistant-fab");
  const panel = document.getElementById("assistant-panel");
  const closeBtn = document.getElementById("assistant-close-btn");
  const runBtn = document.getElementById("run-maintenance-agent-btn");
  const askBtn = document.getElementById("ask-llm-btn");

  fab?.addEventListener("click", () => {
    if (!panel) return;
    panel.hidden = !panel.hidden;
  });
  closeBtn?.addEventListener("click", () => {
    if (panel) panel.hidden = true;
  });
  runBtn?.addEventListener("click", runMaintenanceAgent);
  askBtn?.addEventListener("click", askAssistantQuick);
}

async function loadAllData() {
  const [communityRes, blogRes] = await Promise.allSettled([
    fetchJson("/api/resources/community-items?limit=500"),
    fetchJson("/api/resources/blog-posts?page=1&page_size=120&status=all&include_content=false"),
  ]);

  const communityItems =
    communityRes.status === "fulfilled" && Array.isArray(communityRes.value?.items)
      ? communityRes.value.items.map(normalizeCommunityItem)
      : [];

  const blogItems =
    blogRes.status === "fulfilled" && Array.isArray(blogRes.value?.items)
      ? blogRes.value.items.map(normalizeBlogItem)
      : [];

  state.allItems = sortItems([...communityItems, ...blogItems], "updated_desc");
  state.filtered = [...state.allItems];
  state.page = 1;
  applyFiltersAndRender();

  if (communityRes.status !== "fulfilled" && blogRes.status !== "fulfilled") {
    const root = document.getElementById("event-list");
    if (root) {
      root.innerHTML = `<div class="empty-hint">活动数据加载失败：${escapeHtml(
        `${formatGatewayError(communityRes.reason)} / ${formatGatewayError(blogRes.reason)}`
      )}</div>`;
    }
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  bindFilters();
  bindAssistantPanel();
  await Promise.allSettled([loadAllData(), loadTeamHealthBanner()]);
});
