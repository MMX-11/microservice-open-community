(function (global) {
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderSection({
    title,
    count = 0,
    countLabel = "条",
    sectionClass = "module-block",
    bodyClass = "module-block-list recent-full-grid",
    bodyHtml = "",
    emptyText = "暂无内容",
  } = {}) {
    const content = String(bodyHtml || "").trim() || `<div class="empty-hint">${escapeHtml(emptyText)}</div>`;
    return `
      <section class="${escapeHtml(sectionClass)}">
        <div class="module-block-head">
          <h2>${escapeHtml(title || "未命名模块")}</h2>
          <span>${Number(count) || 0} ${escapeHtml(countLabel)}</span>
        </div>
        <div class="${escapeHtml(bodyClass)}">${content}</div>
      </section>
    `;
  }

  function renderGroupedSections({
    groups,
    order = [],
    renderItem,
    renderGroupTitle = (value) => value,
    sectionClass = "module-block forum-category-block",
    bodyClass = "module-block-list recent-full-grid",
    countLabel = "条",
    emptyText = "暂无内容",
  } = {}) {
    const map = groups instanceof Map ? groups : new Map();
    const orderedKeys = [
      ...order.filter((key) => map.has(key)),
      ...Array.from(map.keys())
        .filter((key) => !order.includes(key))
        .sort((a, b) => String(a).localeCompare(String(b), "zh-CN")),
    ];
    return orderedKeys
      .map((key) =>
        renderSection({
          title: renderGroupTitle(key),
          count: (map.get(key) || []).length,
          countLabel,
          sectionClass,
          bodyClass,
          bodyHtml: (map.get(key) || []).map((item) => renderItem(item)).join(""),
          emptyText,
        })
      )
      .join("");
  }

  function renderPills({
    items = [],
    activeKey = "all",
    allLabel = "全部",
  } = {}) {
    return [
      `<button type="button" data-module-key="all" class="quick-pill${activeKey === "all" ? " is-active" : ""}">${escapeHtml(allLabel)}</button>`,
      ...items.map((item) => {
        const key = String(item.key || "").trim();
        const label = String(item.label || key || "").trim();
        const count = Number.isFinite(Number(item.count)) ? ` (${Number(item.count)})` : "";
        return `<button type="button" data-module-key="${escapeHtml(key)}" class="quick-pill${activeKey === key ? " is-active" : ""}">${escapeHtml(label)}${escapeHtml(count)}</button>`;
      }),
    ].join("");
  }

  function renderCodeBlock(code) {
    return `<pre class="module-code-block">${escapeHtml(code || "")}</pre>`;
  }

  function renderModuleInstanceCard(module, { active = false } = {}) {
    const label = String(module?.label || "模块包").trim();
    const baseLabel = String(module?.base_label || module?.label || "模块").trim();
    const source = String(module?.source || "unknown").trim();
    const grouping = String(module?.default_grouping || "module").trim();
    const description = String(module?.description || "").trim();
    const code = String(module?.code || "").trim();
    const id = String(module?.id || "").trim();
    return `
      <article class="generated-module-card${active ? " is-active" : ""}" data-generated-id="${escapeHtml(id)}">
        <header class="generated-module-head">
          <div>
            <strong>${escapeHtml(label)}</strong>
            <small>基于 ${escapeHtml(baseLabel)}</small>
          </div>
          <span class="generated-module-badge">${escapeHtml(grouping)}</span>
        </header>
        <div class="generated-module-meta">
          <div><span>数据源</span><strong>${escapeHtml(source)}</strong></div>
          <div><span>说明</span><strong>${escapeHtml(description || "无")}</strong></div>
        </div>
        ${renderCodeBlock(code)}
        <div class="generated-module-actions">
          <button type="button" class="ghost-btn" data-generated-action="copy" data-generated-id="${escapeHtml(id)}">复制包</button>
          <button type="button" class="ghost-btn" data-generated-action="download" data-generated-id="${escapeHtml(id)}">下载包</button>
        </div>
      </article>
    `;
  }

  global.CommunityComponents = {
    escapeHtml,
    renderSection,
    renderGroupedSections,
    renderPills,
    renderCodeBlock,
    renderModuleInstanceCard,
  };
})(window);
