const PAGE_SIZE = 12;

const MODULE = {
  taskboard: "\u6587\u732e\u4efb\u52a1\u699c",
  frontier: "AI\u524d\u6cbf",
  sharing: "\u5f00\u6e90\u5206\u4eab",
  forum: "\u4e3b\u9898\u8bba\u575b",
  team: "\u56e2\u961f\u6a21\u5757",
  unc: "\u672a\u5206\u7c7b",
  blogTag: "\u535a\u5ba2",
};

const MODULE_ORDER = [MODULE.taskboard, MODULE.frontier, MODULE.sharing, MODULE.forum, MODULE.team, MODULE.unc];
const FORUM_CATEGORY_ORDER = ["活动讨论", "项目协作", "资料资源", "工具链", "问题反馈", "综合讨论"];
const QUALITY = {
  draft: "草稿",
  usable: "可用",
  featured: "精选",
};

const ASSISTANT_MODE = {
  maintain: "maintain",
  openSource: "open_source",
  similarCommunity: "similar_community",
};
const ASSISTANT_PRESETS = {
  maintain: [
    { label: "本周巡检", mode: ASSISTANT_MODE.maintain, goal: "请做一次本周社区巡检，列出 5 条最值得优先处理的维护事项，并按影响程度排序。" },
    { label: "质量排查", mode: ASSISTANT_MODE.maintain, goal: "请检查当前社区内容的链接、时效和摘要质量，给出可执行修复建议。" },
  ],
  openSource: [
    { label: "建设路线", mode: ASSISTANT_MODE.openSource, goal: "请基于当前社区现状，生成一份可执行的开源社区建设路线图，包含内容、运营和协作机制。" },
    { label: "运营机制", mode: ASSISTANT_MODE.openSource, goal: "请设计一个适合这个社区的周报、内容发布和贡献激励机制，要求可直接落地。" },
  ],
  similarCommunity: [
    { label: "同类社区", mode: ASSISTANT_MODE.similarCommunity, goal: "请生成一个结构与当前社区相似的开源协作社区方案，并给出模块、角色和启动条目。" },
    { label: "冷启动包", mode: ASSISTANT_MODE.similarCommunity, goal: "请为一个新建社区生成冷启动方案，包含首批内容、任务榜、论坛话题和分享条目。" },
  ],
};
const AUTH_STORAGE_KEY = "metalab_auth_v1";
const MODULE_FACTORY_STORAGE_KEY = "metalab_module_factory_v1";

const state = {
  allItems: [],
  filtered: [],
  moduleManifest: { version: "", modules: [] },
  generatedModules: [],
  selectedModuleTemplateKey: "",
  page: 1,
  search: "",
  moduleKey: "all",
  tag: "",
  qualityTier: "all",
  sort: "updated_desc",
  timeWindow: "all",
  viewMode: "card",
  activeItemId: "",
  editingBlogId: 0,
  assistantMode: ASSISTANT_MODE.maintain,
  auth: {
    token: "",
    user: null,
  },
  authMode: "login",
  authChannel: "phone",
  authMethod: "password",
  qualitySummary: {
    invalid_url: 0,
    stale: 0,
  },
  authPasswordTouched: false,
  authPasswordGuardTimer: null,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function stripTeacherExportHint(value) {
  return String(value ?? "")
    .replace(/\u6574\u7406\u597d\u540e\u53ef\u76f4\u63a5\u5bfc\u51fa\s*word\s*\u53d1\u7ed9\u8001\u5e08/gi, "")
    .replace(/\u53ef\u76f4\u63a5\u5bfc\u51fa\s*word\s*\u53d1\u7ed9\u8001\u5e08/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function isHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || "").trim());
}

function waitMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getAuthHeader() {
  const token = String(state.auth?.token || "").trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function saveAuthState() {
  try {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(state.auth || {}));
  } catch (_err) {
    // ignore
  }
}

function loadAuthState() {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return;
    state.auth = {
      token: String(parsed.token || "").trim(),
      user: parsed.user && typeof parsed.user === "object" ? parsed.user : null,
    };
  } catch (_err) {
    // ignore
  }
}

function clearAuthState() {
  state.auth = { token: "", user: null };
  try {
    localStorage.removeItem(AUTH_STORAGE_KEY);
  } catch (_err) {
    // ignore
  }
}

function saveModuleFactoryState() {
  try {
    localStorage.setItem(MODULE_FACTORY_STORAGE_KEY, JSON.stringify(state.generatedModules || []));
  } catch (_err) {
    // ignore
  }
}

function loadModuleFactoryState() {
  try {
    const raw = localStorage.getItem(MODULE_FACTORY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => normalizeGeneratedModule(item))
      .filter(Boolean);
  } catch (_err) {
    return [];
  }
}

function currentRole() {
  return String(state.auth?.user?.role || "").trim();
}

function canManageBlogs() {
  return currentRole() === "admin";
}

async function fetchJson(url, options = {}) {
  const { timeoutMs = 45000, retry = 1, ...fetchOptions } = options || {};
  let lastError = null;
  for (let i = 0; i <= retry; i += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const mergedHeaders = {
        ...getAuthHeader(),
        ...(fetchOptions.headers || {}),
      };
      const resp = await fetch(url, {
        ...fetchOptions,
        headers: mergedHeaders,
        cache: "no-store",
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
      }
      return resp.json();
    } catch (err) {
      clearTimeout(timer);
      lastError = err;
      if (i < retry) await waitMs(600 * (i + 1));
    }
  }
  throw lastError || new Error("request failed");
}

function formatGatewayError(err) {
  const raw = String(err?.message || err || "").trim();
  if (!raw) return "服务暂时不可用，请稍后重试。";
  if (/AbortError|aborted|timeout/i.test(raw)) {
    return "请求超时：服务响应较慢，请重试。";
  }
  if (/Failed to fetch|NetworkError|Load failed|TypeError: Failed to fetch/i.test(raw)) {
    return "网络请求失败：请检查网关是否在线，或稍后重试。";
  }
  if (/LLM service unavailable:\s*timed out/i.test(raw) || /\btimed out\b/i.test(raw)) {
    return "生成超时：模型响应较慢。请重试，或缩短输入内容后再生成。";
  }
  const detailMatch = raw.match(/:\s*(\{[\s\S]*\})$/);
  if (detailMatch?.[1]) {
    try {
      const parsed = JSON.parse(detailMatch[1]);
      if (parsed && typeof parsed.detail === "string" && parsed.detail.trim()) {
        const inner = parsed.detail.trim();
        if (inner.startsWith("{") && inner.endsWith("}")) {
          try {
            const nested = JSON.parse(inner);
            if (nested && typeof nested.detail === "string" && nested.detail.trim()) return nested.detail.trim();
          } catch (_ignored_nested) {
            // ignore
          }
        }
        return inner;
      }
    } catch (_ignored) {
      // ignore
    }
  }
  return raw.length > 180 ? `${raw.slice(0, 180)}...` : raw;
}

function toEpochMs(value) {
  const t = new Date(value || "").getTime();
  return Number.isFinite(t) ? t : 0;
}

function getItemTimeMs(item) {
  return Math.max(toEpochMs(item.updated_at), toEpochMs(item.created_at));
}

function isWithinDays(item, days) {
  const t = getItemTimeMs(item);
  if (!t) return false;
  return Date.now() - t <= days * 24 * 60 * 60 * 1000;
}

function formatDateTime(value) {
  const d = new Date(value || "");
  if (Number.isNaN(d.getTime())) return "长期";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function getDomain(url) {
  try {
    return new URL(String(url || "")).host || "社区";
  } catch {
    return "社区";
  }
}

function moduleKeyToLabel(key) {
  if (key === "taskboard") return MODULE.taskboard;
  if (key === "frontier") return MODULE.frontier;
  if (key === "sharing") return MODULE.sharing;
  if (key === "forum") return MODULE.forum;
  if (key === "team") return MODULE.team;
  if (key === "unc") return MODULE.unc;
  return "全部";
}

function moduleLabelToKey(label) {
  const n = normalizeModuleName(label);
  if (n === MODULE.taskboard) return "taskboard";
  if (n === MODULE.frontier) return "frontier";
  if (n === MODULE.sharing) return "sharing";
  if (n === MODULE.forum) return "forum";
  if (n === MODULE.team) return "team";
  if (n === MODULE.unc) return "unc";
  return "all";
}

function normalizeModuleName(value) {
  const raw = String(value || "").trim();
  const key = raw.toLowerCase().replace(/[\s_-]+/g, "");
  const alias = {
    literaturetaskboard: MODULE.taskboard,
    taskboard: MODULE.taskboard,
    aifrontier: MODULE.frontier,
    opensourcesharing: MODULE.sharing,
    opensource: MODULE.sharing,
    topicforum: MODULE.forum,
    forum: MODULE.forum,
    teammodule: MODULE.team,
    team: MODULE.team,
    blog: MODULE.sharing,
  };
  if (alias[key]) return alias[key];
  if (raw === MODULE.taskboard || raw === MODULE.frontier || raw === MODULE.sharing || raw === MODULE.forum || raw === MODULE.team) {
    return raw;
  }
  return raw || MODULE.unc;
}

function compactText(parts) {
  return parts
    .map((part) => stripTeacherExportHint(part))
    .map((part) => String(part || "").trim())
    .filter(Boolean)
    .join(" | ");
}

function containsChinese(text) {
  return /[\u4e00-\u9fff]/.test(String(text || ""));
}

const ALLOWED_LATIN_TOKENS = [
  "AI",
  "arXiv",
  "CLIP",
  "CVPR",
  "DDD",
  "GPT",
  "HPA",
  "ICCV",
  "ICLR",
  "ICML",
  "LLM",
  "LLMs",
  "MEC",
  "MIMO",
  "NLP",
  "RSS",
  "SOTA",
  "ViT",
  "ViTs",
  "XL-RIS",
  "K3s",
  "Kubernetes",
];

function stripAllowedLatinTerms(text) {
  let value = String(text || "");
  ALLOWED_LATIN_TOKENS.forEach((token) => {
    value = value.replace(new RegExp(`\\b${token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "gi"), " ");
  });
  value = value.replace(/cs\.[A-Z]{2,3}/gi, " ");
  return value;
}

function truncateText(text, maxLen) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (value.length <= maxLen) return value;
  return `${value.slice(0, Math.max(0, maxLen - 1))}…`;
}

function stripEnglishPrefixes(text) {
  return String(text || "")
    .replace(/^\s*\[?\s*arxiv\s*\]?\s*/i, "")
    .replace(/^\s*\[?\s*cvpr\s*\]?\s*/i, "")
    .replace(/^\s*\[?\s*iclr\s*\]?\s*/i, "")
    .replace(/^\s*\[?\s*icml\s*\]?\s*/i, "")
    .trim();
}

const TITLE_TRANSLATION_RULES = [
  [/\bAgentic Coding Needs Proactivity, Not Just Autonomy\b/i, "代理式编程需要主动性，而不仅是自主性"],
  [/\bFrom Storage to Experience: A Survey on the Evolution of LLM Agent Memory\b/i, "从存储到体验：LLM Agent 记忆演进综述"],
  [/\bEdge Deep Learning in Computer Vision and Medical Diagnostics\b/i, "计算机视觉与医疗诊断中的边缘深度学习"],
  [/\bIndustrialization of Cyber Offense\b/i, "网络攻击的工业化"],
  [/\bTUANDROMD-X: Advanced Entropy and Visual Analytics Dataset for Enhanced Malware Detection\b/i, "TUANDROMD-X：用于增强恶意软件检测的高级熵与可视分析数据集"],
  [/\bNear-field Channel Estimation for XL-RIS-aided mmWave MIMO Systems\b/i, "XL-RIS辅助毫米波 MIMO 系统的近场信道估计"],
  [/\bStreaming 3DGS worlds on the web\b/i, "在网页端流式渲染 3DGS 世界"],
  [/\bA Survey on the Evolution of LLM Agent Memory\b/i, "LLM Agent 记忆演进综述"],
  [/\bFrom Storage to Experience\b/i, "从存储到体验"],
  [/\bAgentic AI\b/i, "代理式 AI"],
  [/\bComputer Vision\b/i, "计算机视觉"],
  [/\bMedical Diagnostics\b/i, "医疗诊断"],
  [/\bVisual Analytics\b/i, "可视分析"],
  [/\bMalware Detection\b/i, "恶意软件检测"],
  [/\bChannel Estimation\b/i, "信道估计"],
  [/\bDeep Learning\b/i, "深度学习"],
  [/\bSurvey\b/i, "综述"],
  [/\bEvolution\b/i, "演进"],
  [/\bMemory\b/i, "记忆"],
  [/\bExperience\b/i, "体验"],
  [/\bStorage\b/i, "存储"],
  [/\bAided\b/i, "辅助"],
  [/\bNeeds\b/i, "需要"],
  [/\bProactivity\b/i, "主动性"],
  [/\bAutonomy\b/i, "自主性"],
  [/\bProactive\b/i, "主动"],
  [/\bIndustrialization\b/i, "工业化"],
  [/\bCyber Offense\b/i, "网络攻击"],
  [/\bAgentic\b/i, "代理式"],
  [/\bCoding\b/i, "编程"],
  [/\bSystems?\b/i, "系统"],
  [/\bDataset\b/i, "数据集"],
  [/\bWeb\b/i, "网页"],
  [/\bworlds?\b/i, "世界"],
  [/\bStreaming\b/i, "流式"],
  [/\bEnhanced\b/i, "增强"],
  [/\bVisual\b/i, "视觉"],
  [/\bAnalytics\b/i, "分析"],
  [/\bMIMO\b/i, "MIMO"],
  [/\bmmWave\b/i, "毫米波"],
  [/\bXL-RIS\b/i, "XL-RIS"],
  [/\bLLM\b/i, "LLM"],
  [/\bAI\b/i, "AI"],
  [/\barXiv\b/i, "arXiv"],
];

function translateEnglishTitle(text) {
  let value = stripEnglishPrefixes(text);
  const exactRules = [
    [/\bCASCADE:\s*Case-Based Continual Adaptation for Large Language Models During Deployment\b/i, "CASCADE：面向部署阶段的大语言模型案例式持续适应"],
    [/\bHidden Coalitions in Multi-Agent AI:\s*A Spectral Diagnostic from Internal Representations\b/i, "多智能体 AI 中的隐性联盟：基于内部表征的谱诊断"],
    [/\bState Representation and Termination for Recursive Reasoning Systems\b/i, "递归推理系统的状态表征与终止机制"],
    [/\bRobustness of Refugee-Matching Gains to Off-Policy Evaluation Choices\b/i, "难民匹配收益对离策略评估选择的鲁棒性"],
    [/\bAn audio-to-analysis pipeline with certified transcription for information-theoretic\b/i, "具备认证转写的音频到分析流水线：面向信息论研究"],
    [/\bFrom Canopy to Collision:\s*A Hybrid Predictive Framework for Identifying Risk Factors\b/i, "从林冠到碰撞：识别风险因素的混合预测框架"],
    [/\bTeopitz MLP Mixers\b/i, "Toeplitz MLP 混合器"],
    [/\bTeoplitz MLP Mixers\b/i, "Toeplitz MLP 混合器"],
    [/\bToeplitz MLP Mixers\b/i, "Toeplitz MLP 混合器"],
    [/\bAgentic Coding Needs Proactivity, Not Just Autonomy\b/i, "代理式编程需要主动性，而不仅是自主性"],
    [/\bFrom Storage to Experience: A Survey on the Evolution of LLM Agent Memory\b/i, "从存储到体验：LLM Agent 记忆演进综述"],
    [/\bEdge Deep Learning in Computer Vision and Medical Diagnostics\b/i, "计算机视觉与医疗诊断中的边缘深度学习"],
    [/\bIndustrialization of Cyber Offense\b/i, "网络攻击的工业化"],
    [/\bTUANDROMD-X: Advanced Entropy and Visual Analytics Dataset for Enhanced Malware Detection\b/i, "TUANDROMD-X：用于增强恶意软件检测的高级熵与可视分析数据集"],
    [/\bNear-field Channel Estimation for XL-RIS-aided mmWave MIMO Systems\b/i, "XL-RIS辅助毫米波 MIMO 系统的近场信道估计"],
    [/\bStreaming 3DGS worlds on the web\b/i, "在网页端流式渲染 3DGS 世界"],
    [/\bA Survey on the Evolution of LLM Agent Memory\b/i, "LLM Agent 记忆演进综述"],
    [/\bFrom Storage to Experience\b/i, "从存储到体验"],
  ];
  for (const [pattern, replacement] of exactRules) {
    if (pattern.test(value)) return replacement;
  }
  if (containsChinese(value) && !/[A-Za-z]{4,}/.test(value)) return value;

  value = value.replace(/[\[\]()"']/g, " ").replace(/\s+/g, " ").trim();
  for (const [pattern, replacement] of TITLE_TRANSLATION_RULES) {
    value = value.replace(pattern, replacement);
  }
  value = value
    .replace(/\bof\b/gi, "的")
    .replace(/\band\b/gi, "与")
    .replace(/\bfor\b/gi, "用于")
    .replace(/\bwith\b/gi, "与")
    .replace(/\bon\b/gi, "在")
    .replace(/\bthe\b/gi, "")
    .replace(/\ba\b/gi, "")
    .replace(/\ban\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  if (!value || !containsChinese(value)) return "";
  return value.length > 80 ? `${value.slice(0, 79)}…` : value;
}

function hasLatinNoise(text) {
  return /[A-Za-z]{4,}/.test(stripAllowedLatinTerms(text));
}

function looksLikeChineseText(text) {
  const value = String(text || "").trim();
  return containsChinese(value) && !hasLatinNoise(value);
}

function stripResidualEnglishTerms(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  return value
    .replace(/\b[A-Za-z][A-Za-z0-9+\-']*\b/g, " ")
    .replace(/[()\[\]{}]/g, " ")
    .replace(/\s*[:\-–—]+\s*/g, "：")
    .replace(/\s{2,}/g, " ")
    .replace(/\s*([：，。；、])\s*/g, "$1")
    .trim();
}

function getCardTitle(item) {
  const title = String(item?.title || "未命名条目").trim() || "未命名条目";
  if (looksLikeChineseText(title)) return title;
  const translatedTitle = translateEnglishTitle(title);
  if (looksLikeChineseText(translatedTitle)) return translatedTitle;
  return title;
}

function getCardSubtitle(item) {
  return "";
}

function getCardSummary(item) {
  const summary = String(item?.summary || "").trim();
  if (!summary) return "暂无摘要";
  if (looksLikeChineseText(summary)) return truncateText(summary, 180);
  const translated = translateEnglishTitle(summary);
  if (looksLikeChineseText(translated)) return truncateText(translated, 180);
  return truncateText(summary, 180);
}

function getCardSource(item) {
  const source = String(item?.source || "社区").trim() || "社区";
  if (containsChinese(source)) return source;
  const sourceMap = {
    arxiv_cs_cn_sync: "AI 前沿同步",
    arxivorg: "arXiv 论文",
    openkg_field_repo: "openKG-field · 仓库",
    openkg_field_issue: "openKG-field · 议题",
    openkg_field: "openKG-field",
    catalog_ai_frontier: "目录导入 · AI前沿",
    catalog_literature_taskboard: "目录导入 · 文献任务榜",
    catalog_open_source_sharing: "目录导入 · 开源分享",
    catalog_topic_forum: "目录导入 · 主题论坛",
    catalog_seed: "目录种子",
    community_item: "社区条目",
    niuke_site: "Niuke 站点",
  };
  const normalized = source.toLowerCase().replace(/[\s-]+/g, "_");
  if (sourceMap[normalized]) return sourceMap[normalized];
  const translated = translateEnglishTitle(source);
  return translated || source;
}

function getCardTags(item) {
  return (item?.tags || []).map((tag) => {
    const value = String(tag || "").trim();
    if (!value) return value;
    if (containsChinese(value)) return value;
    const translated = translateEnglishTitle(value);
    return translated || value;
  });
}

function getCardDomain(item) {
  const raw = getDomain(item.url);
  if (containsChinese(raw)) return raw;
  const translated = translateEnglishTitle(raw);
  return translated || raw;
}

function normalizeCommunityItem(item) {
  const category = String(item.category || "").trim();
  const labels = Array.isArray(item.labels) ? item.labels.map((x) => String(x || "").trim()).filter(Boolean) : [];
  const tags = [];
  if (category) tags.push(category);
  labels.forEach((label) => {
    if (!tags.includes(label)) tags.push(label);
  });
  return {
    id: `c-${item.id || Math.random().toString(36).slice(2)}`,
    title: stripTeacherExportHint(item.title || "未命名条目"),
    summary: stripTeacherExportHint(item.summary || ""),
    url: item.url || "",
    module: normalizeModuleName(item.module || MODULE.unc),
    category,
    tags,
    source: item.source || "社区条目",
    created_at: item.created_at || item.updated_at || "",
    updated_at: item.updated_at || item.created_at || "",
    kind: "community",
  };
}

function normalizeBlogItem(post) {
  const tags = Array.isArray(post.tags) ? post.tags.map((x) => String(x || "").trim()).filter(Boolean) : [];
  if (!tags.includes(MODULE.blogTag)) tags.push(MODULE.blogTag);
  const authorName = String(post.author || "社区用户").trim() || "社区用户";
  const authorAvatarUrl = String(post.author_avatar_url || "").trim();
  return {
    id: `b-${post.id || Math.random().toString(36).slice(2)}`,
    blog_id: Number(post.id || 0),
    title: stripTeacherExportHint(post.title || "未命名博客"),
    summary: stripTeacherExportHint(post.summary || post.excerpt || ""),
    url: post.share_url || "",
    module: MODULE.sharing,
    tags,
    source: authorName,
    author: authorName,
    author_id: authorName,
    author_avatar_url: authorAvatarUrl,
    blog_status: String(post.status || "published").toLowerCase(),
    created_at: post.created_at || post.updated_at || "",
    updated_at: post.updated_at || post.created_at || "",
    content_markdown: "",
    kind: "blog",
  };
}

function getAuthorDisplayName(item) {
  return String(item?.author || item?.source || "社区用户").trim() || "社区用户";
}

function getAuthorIdentity(item) {
  return String(item?.author_id || item?.author || item?.source || "").trim();
}

function sectionToModule(section) {
  if (section === "literature_taskboard") return MODULE.taskboard;
  if (section === "ai_frontier") return MODULE.frontier;
  if (section === "open_source_sharing") return MODULE.sharing;
  if (section === "topic_forum") return MODULE.forum;
  return MODULE.unc;
}

function normalizeCatalogItem(section, row, index) {
  const module = sectionToModule(section);
  const title = stripTeacherExportHint(row.title || row.topic || `Item-${index + 1}`);
  const summary = compactText([row.paper_note, row.summary, row.goal, row.description]);
  const url = row.discussion_url || row.reference_url || row.github_url || row.detail_url || row.issue_url || "";
  const category = String(row.category || row.topic_category || row.group || "").trim();
  const forumTime = String(row.event_time || row.time || row.date || "").trim();
  const forumLocation = String(row.location || row.venue || "").trim();
  const forumSpeaker = String(row.speaker || row.host || "").trim();
  const forumSignupUrl = String(row.signup_url || row.registration_url || row.register_url || "").trim();
  const tags = [row.metric, row.dataset, row.task, row.baseline, row.type, row.category]
    .map((x) => String(x || "").trim())
    .filter(Boolean)
    .slice(0, 6);
  const sourceLabelMap = {
    literature_taskboard: "目录导入 · 文献任务榜",
    ai_frontier: "目录导入 · AI前沿",
    open_source_sharing: "目录导入 · 开源分享",
    topic_forum: "目录导入 · 主题论坛",
  };

  return {
    id: `k-${section}-${row.id || index + 1}`,
    title,
    summary,
    url,
    module,
    tags,
    source: sourceLabelMap[section] || `目录导入 · ${module}`,
    created_at: "",
    updated_at: "",
    forum_time: forumTime,
    forum_location: forumLocation,
    forum_speaker: forumSpeaker,
    forum_signup_url: forumSignupUrl,
    category,
    kind: "catalog",
  };
}

function normalizeCatalogItems(catalog) {
  if (!catalog || typeof catalog !== "object") return [];
  const sections = ["literature_taskboard", "ai_frontier", "open_source_sharing", "topic_forum"];
  const out = [];
  sections.forEach((section) => {
    const rows = Array.isArray(catalog[section]) ? catalog[section] : [];
    rows.forEach((row, idx) => out.push(normalizeCatalogItem(section, row || {}, idx)));
  });
  return out;
}

function isItemStaleByDays(item, days = 30) {
  const t = getItemTimeMs(item);
  if (!t) return false;
  return Date.now() - t > days * 24 * 60 * 60 * 1000;
}

function isFeaturedItem(item) {
  const tags = (item.tags || []).map((x) => String(x || "").trim().toLowerCase());
  return tags.includes("精选") || tags.includes("featured") || String(item.title || "").includes("精选");
}

function getItemQualityTier(item) {
  if (!item) return "draft";
  if (normalizeModuleName(item.module) === MODULE.forum) {
    return isHttpUrl(item.url) ? "usable" : "draft";
  }
  if (isFeaturedItem(item)) return "featured";
  if (item.kind === "blog" && String(item.blog_status || "").toLowerCase() === "draft") return "draft";
  const weakSummary = String(item.summary || "").trim().length < 12;
  if (weakSummary || !isHttpUrl(item.url) || isItemStaleByDays(item, 30)) return "draft";
  return "usable";
}

function matchesQualityFilter(item) {
  const tier = getItemQualityTier(item);
  if (state.qualityTier === "all") return true;
  if (state.qualityTier === "featured") return tier === "featured";
  if (state.qualityTier === "usable") return tier === "usable";
  if (state.qualityTier === "draft") return tier === "draft";
  return tier === "usable" || tier === "featured";
}

function normalizeBlogLevelFromItem(item) {
  const tier = getItemQualityTier(item);
  if (tier === "featured") return "featured";
  if (item && item.kind === "blog" && String(item.blog_status || "").toLowerCase() === "draft") return "draft";
  return "usable";
}

function itemScore(item) {
  let score = 0;
  if (item.kind === "community") score += 4;
  if (item.kind === "blog") score += 3;
  if (String(item.summary || "").trim()) score += 2;
  if (Array.isArray(item.tags) && item.tags.length) score += 1;
  if (isHttpUrl(item.url)) score += 1;
  if (getItemTimeMs(item)) score += 1;
  return score;
}

function dedupeItems(items) {
  const picked = new Map();
  items.forEach((item) => {
    const key = [normalizeModuleName(item.module || ""), String(item.title || "").trim().toLowerCase(), String(item.url || "").trim().toLowerCase()].join("::");
    if (!picked.has(key)) {
      picked.set(key, item);
      return;
    }
    const oldItem = picked.get(key);
    if (itemScore(item) >= itemScore(oldItem)) picked.set(key, item);
  });
  return Array.from(picked.values());
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
  if (sortMode === "module_asc") {
    rows.sort((a, b) => {
      const ma = MODULE_ORDER.indexOf(normalizeModuleName(a.module));
      const mb = MODULE_ORDER.indexOf(normalizeModuleName(b.module));
      if (ma !== mb) return ma - mb;
      return String(a.title || "").localeCompare(String(b.title || ""), "zh-CN");
    });
    return rows;
  }
  rows.sort((a, b) => getItemTimeMs(b) - getItemTimeMs(a));
  return rows;
}

function collectTags(items) {
  const set = new Set();
  items.forEach((item) => {
    (item.tags || []).forEach((tag) => {
      const t = String(tag || "").trim();
      if (t) set.add(t);
    });
  });
  return Array.from(set).slice(0, 80);
}

function renderTagFilters(items) {
  const root = document.getElementById("tag-filter-list");
  if (!root) return;
  const tags = collectTags(items);
  if (!tags.length) {
    root.innerHTML = '<div class="empty-hint">当前结果下无标签</div>';
    return;
  }
  root.innerHTML = "";
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

function renderModuleQuickPills(items) {
  const root = document.getElementById("module-quick-pills");
  if (!root) return;
  const counts = new Map();
  items.forEach((item) => {
    const module = normalizeModuleName(item.module);
    counts.set(module, (counts.get(module) || 0) + 1);
  });

  const rows = MODULE_ORDER.filter((m) => counts.has(m)).map((m) => [m, counts.get(m)]);
  const pills = rows.map(([label, count]) => ({
    key: moduleLabelToKey(label),
    label,
    count,
  }));
  root.innerHTML = window.CommunityComponents
    ? window.CommunityComponents.renderPills({ items: pills, activeKey: state.moduleKey, allLabel: "全部" })
    : [
        '<button type="button" data-module-key="all" class="quick-pill">全部</button>',
        ...rows.map(([label, count]) => {
          const key = moduleLabelToKey(label);
          return `<button type="button" data-module-key="${escapeHtml(key)}" class="quick-pill">${escapeHtml(label)} (${count})</button>`;
        }),
      ].join("");

  root.querySelectorAll("button[data-module-key]").forEach((btn) => {
    btn.classList.toggle("is-active", String(btn.dataset.moduleKey || "all") === state.moduleKey);
    btn.addEventListener("click", () => {
      state.moduleKey = String(btn.dataset.moduleKey || "all");
      state.page = 1;
      applyFiltersAndRender();
    });
  });
}

function updateSelectedHint() {
  const countEl = document.getElementById("selected-count");
  const detailEl = document.getElementById("selected-detail");
  const picks = [];
  if (state.search) picks.push(`关键词: ${state.search}`);
  if (state.moduleKey !== "all") picks.push(`分类: ${moduleKeyToLabel(state.moduleKey)}`);
  if (state.qualityTier !== "usable_plus") {
    const qualityLabel = state.qualityTier === "featured" ? "仅精选" : state.qualityTier === "usable" ? "仅可用" : state.qualityTier === "draft" ? "仅草稿" : "全部分级";
    picks.push(`分级: ${qualityLabel}`);
  }
  if (state.tag) picks.push(`标签: ${state.tag}`);
  if (state.timeWindow !== "all") {
    const label = state.timeWindow === "recent7" ? "近7天" : state.timeWindow === "recent30" ? "近30天" : "长期内容";
    picks.push(`时间: ${label}`);
  }
  if (countEl) countEl.textContent = String(picks.length);
  if (detailEl) detailEl.textContent = picks.length ? picks.join(" | ") : "当前未设置筛选条件";
}

function updatePageHeader() {
  const titleEl = document.getElementById("page-title");
  const subtitleEl = document.getElementById("page-subtitle");
  if (!titleEl || !subtitleEl) return;
  if (state.moduleKey === "all") {
    titleEl.textContent = "社区总览";
    subtitleEl.textContent = "仅保留最近更新、热门标签、模块计数与运营看板。";
    return;
  }
  titleEl.textContent = moduleKeyToLabel(state.moduleKey);
  subtitleEl.textContent = state.moduleKey === "forum" ? "来自 openKG-field 的主题讨论内容，按中文分类展示。" : "查看当前模块详细条目，支持筛选、编辑与运营治理。";
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

function renderItemCard(item) {
  const moduleLabel = normalizeModuleName(item.module);
  const moduleKey = moduleLabelToKey(moduleLabel);
  const moduleTheme = moduleKey === "all" ? "unc" : moduleKey;
  const hasLink = isHttpUrl(item.url);
  const domain = hasLink ? getCardDomain(item) : "暂无外链";
  const tagsHtml = getCardTags(item)
    .slice(0, 5)
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join("");
  const canAdminManage = canManageBlogs();
  const blogEditBtn = item.kind === "blog" && item.blog_id && canAdminManage ? `<button type="button" class="blog-edit-btn" data-blog-id="${item.blog_id}">编辑博客</button>` : "";
  const blogDeleteBtn = item.kind === "blog" && item.blog_id && canAdminManage ? `<button type="button" class="blog-delete-btn" data-blog-id="${item.blog_id}">删除博客</button>` : "";
  const qualityTier = getItemQualityTier(item);
  const qualityLabel = QUALITY[qualityTier] || QUALITY.usable;
  const staleBadge = isItemStaleByDays(item, 30) ? '<span class="tag tag-stale">待更新</span>' : "";
  const authorDisplay = getAuthorDisplayName(item);
  const authorAvatarUrl = String(item.author_avatar_url || "").trim();
  const authorIdentity = getAuthorIdentity(item);
  const authorBlock =
    item.kind === "blog"
      ? `
        <button type="button" class="author-chip author-open-btn" data-author="${escapeHtml(authorIdentity)}">
          ${
            authorAvatarUrl
              ? `<img class="author-chip-avatar" src="${escapeHtml(authorAvatarUrl)}" alt="${escapeHtml(authorDisplay)}" />`
              : `<span class="author-chip-fallback">${escapeHtml(authorDisplay.slice(0, 1).toUpperCase())}</span>`
          }
          <span class="author-chip-text">
            <strong>${escapeHtml(authorDisplay)}</strong>
            <span>发布者</span>
          </span>
        </button>
      `
      : "";
  const coverClass = authorAvatarUrl ? "event-cover has-avatar-cover" : "event-cover";
  const coverStyle = authorAvatarUrl ? ` style="--cover-image: url('${escapeHtml(authorAvatarUrl)}')"` : "";
  const isForum = moduleLabel === MODULE.forum;
  const forumTime = String(item.forum_time || "").trim();
  const forumLocation = String(item.forum_location || "").trim();
  const forumSpeaker = String(item.forum_speaker || "").trim();
  const forumSignupUrl = String(item.forum_signup_url || "").trim();
  const forumInfoHtml = isForum
    ? `
      <div class="event-tags forum-meta">
        ${forumTime ? `<span class="tag">时间：${escapeHtml(translateEnglishTitle(forumTime) || forumTime)}</span>` : ""}
        ${forumLocation ? `<span class="tag">地点：${escapeHtml(translateEnglishTitle(forumLocation) || forumLocation)}</span>` : ""}
        ${forumSpeaker ? `<span class="tag">主讲：${escapeHtml(translateEnglishTitle(forumSpeaker) || forumSpeaker)}</span>` : ""}
      </div>
    `
    : "";
  const forumSignupBtn = isForum && isHttpUrl(forumSignupUrl) ? `<a href="${escapeHtml(forumSignupUrl)}" target="_blank" rel="noreferrer">报名入口</a>` : "";

  return `
    <article class="event-card module-theme-${moduleTheme}" data-module-key="${moduleTheme}">
      <div class="${coverClass}"${coverStyle}>
        <span class="module-badge">${escapeHtml(moduleLabel)}</span>
        <div class="event-domain">${escapeHtml(domain)}</div>
      </div>
      <div class="event-main">
        <div class="event-meta">
          <span>${escapeHtml(getCardSource(item))}</span>
          <span>${escapeHtml(formatDateTime(item.updated_at || item.created_at))}</span>
          <span class="quality-badge quality-${escapeHtml(qualityTier)}">${escapeHtml(qualityLabel)}</span>
        </div>
        ${authorBlock}
        <h3 class="event-title">${escapeHtml(getCardTitle(item))}</h3>
        ${getCardSubtitle(item) ? `<p class="event-title-aux">${escapeHtml(getCardSubtitle(item))}</p>` : ""}
        ${getCardSummary(item) ? `<p class="event-summary">${escapeHtml(getCardSummary(item))}</p>` : ""}
        ${forumInfoHtml}
        <div class="event-tags">${staleBadge}${tagsHtml || '<span class="tag">无标签</span>'}</div>
        <div class="event-actions">
          <button type="button" class="detail-btn" data-item-id="${escapeHtml(item.id)}">查看详情</button>
          ${hasLink ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">打开原文</a>` : ""}
          ${forumSignupBtn}
          ${blogEditBtn}
          ${blogDeleteBtn}
        </div>
      </div>
    </article>
  `;
}

function groupRowsByModule(rows) {
  const groups = new Map();
  rows.forEach((item) => {
    const module = normalizeModuleName(item.module);
    if (!groups.has(module)) groups.set(module, []);
    groups.get(module).push(item);
  });
  return groups;
}

function normalizeForumCategory(value) {
  const text = String(value || "").trim();
  return text || "综合讨论";
}

function groupRowsByCategory(rows) {
  const groups = new Map();
  rows.forEach((item) => {
    const category = normalizeForumCategory(item.category || (Array.isArray(item.tags) ? item.tags[0] : ""));
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(item);
  });
  return groups;
}

const ARXIV_CATEGORY_LABELS = {
  "cs.AI": "人工智能",
  "cs.CL": "自然语言处理",
  "cs.CV": "计算机视觉",
  "cs.LG": "机器学习",
  "cs.RO": "机器人学",
  "cs.IR": "信息检索",
  "stat.ML": "统计机器学习",
  "cs.SI": "社会信息学",
  "cs.HC": "人机交互",
  "cs.NE": "神经计算",
};

function normalizeContentCategory(item) {
  const raw = String(item?.category || (Array.isArray(item?.tags) ? item.tags[0] : "") || "").trim();
  if (!raw) return "综合讨论";
  if (ARXIV_CATEGORY_LABELS[raw]) return ARXIV_CATEGORY_LABELS[raw];
  if (ARXIV_CATEGORY_LABELS[raw.toLowerCase()]) return ARXIV_CATEGORY_LABELS[raw.toLowerCase()];
  if (containsChinese(raw)) return raw;
  const translated = translateEnglishTitle(raw);
  return translated || raw;
}

function groupRowsByContentCategory(rows) {
  const groups = new Map();
  rows.forEach((item) => {
    const category = normalizeContentCategory(item);
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(item);
  });
  return groups;
}

function computeOpsMetrics(items) {
  const recent7 = items.filter((x) => isWithinDays(x, 7));
  const weekNew = recent7.length;
  const weekAuthors = new Set(
    recent7
      .filter((x) => x.kind === "blog")
      .map((x) => getAuthorIdentity(x) || getAuthorDisplayName(x))
      .filter(Boolean)
  ).size;

  const moduleFreq = new Map();
  recent7.forEach((x) => {
    const m = normalizeModuleName(x.module);
    moduleFreq.set(m, (moduleFreq.get(m) || 0) + 1);
  });
  const moduleRows = Array.from(moduleFreq.entries()).sort((a, b) => b[1] - a[1]);
  const stale30 = items.filter((x) => isItemStaleByDays(x, 30)).length;
  const localInvalid = items.filter((x) => !isHttpUrl(x.url)).length;
  const deadLinks = Math.max(Number(state.qualitySummary?.invalid_url || 0), localInvalid);

  return { weekNew, weekAuthors, moduleRows, stale30, deadLinks };
}

function getOverviewSnapshot() {
  const items = state.allItems || [];
  const metrics = computeOpsMetrics(items);
  const healthScore = computeHealthScore(metrics);
  const blogCount = items.filter((x) => x.kind === "blog").length;
  return {
    items,
    metrics,
    healthScore,
    blogCount,
    totalItems: items.length,
  };
}

function computeHealthScore(metrics) {
  const deadPenalty = Math.min(35, (metrics.deadLinks || 0) * 6);
  const stalePenalty = Math.min(30, (metrics.stale30 || 0) * 2);
  const activityBonus = Math.min(12, (metrics.weekNew || 0) * 0.8 + (metrics.weekAuthors || 0) * 1.5);
  return Math.max(0, Math.min(100, Math.round(100 - deadPenalty - stalePenalty + activityBonus)));
}

function renderModuleManifest(manifest) {
  const modules = Array.isArray(manifest?.modules) ? manifest.modules : [];
  if (!modules.length) return '<span class="empty-hint">暂无模块清单</span>';
  return modules
    .map((mod) => {
      const key = String(mod.key || mod.label || "").trim();
      const label = String(mod.label || key || "未命名模块").trim();
      const source = String(mod.source || "").trim();
      const grouping = String(mod.default_grouping || "").trim();
      const description = String(mod.description || "").trim();
      const activeClass = state.selectedModuleTemplateKey === key ? " is-active" : "";
      return `
        <div class="manifest-chip manifest-copy-btn${activeClass}" data-manifest-key="${escapeHtml(key)}" role="button" tabindex="0">
          <div class="manifest-chip-main">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(grouping || "module")}</span>
            ${source ? `<small>${escapeHtml(source)}</small>` : ""}
            ${description ? `<em>${escapeHtml(description)}</em>` : ""}
          </div>
          <div class="manifest-chip-actions">
            <button type="button" class="ghost-btn" data-manifest-action="generate" data-manifest-key="${escapeHtml(key)}">直接生成</button>
            <button type="button" class="ghost-btn" data-manifest-action="copy-json" data-manifest-key="${escapeHtml(key)}">复制配置</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function getModuleTemplate(key) {
  const mod = (Array.isArray(state.moduleManifest?.modules) ? state.moduleManifest.modules : []).find((x) => String(x.key || x.label || "").trim() === key);
  if (!mod) return null;
  return {
    key: String(mod.key || "").trim(),
    label: String(mod.label || "").trim(),
    source: String(mod.source || "").trim(),
    default_grouping: String(mod.default_grouping || "module").trim(),
    description: String(mod.description || "").trim(),
  };
}

function makeSafeExportName(label) {
  let name = String(label || "Module").replace(/[^\w\u4e00-\u9fff]/g, "");
  if (!name) name = "Module";
  if (!/^[A-Za-z_\u4e00-\u9fff]/.test(name)) name = `Module${name}`;
  return `${name}Module`;
}

function moduleTemplateToCode(template) {
  const exportName = makeSafeExportName(template.instance_label || template.label || "Module");
  return `export const ${exportName} = {
  key: ${JSON.stringify(template.instance_key || template.key)},
  base_key: ${JSON.stringify(template.key)},
  label: ${JSON.stringify(template.instance_label || template.label)},
  base_label: ${JSON.stringify(template.label)},
  source: ${JSON.stringify(template.source)},
  default_grouping: ${JSON.stringify(template.default_grouping)},
  description: ${JSON.stringify(template.description)},
  render(items) {
    return items.map((item) => item.title).join("\\n");
  },
};`;
}

function normalizeGeneratedModule(template) {
  if (!template || typeof template !== "object") return null;
  const baseKey = String(template.base_key || template.key || "").trim();
  const baseLabel = String(template.base_label || template.label || "").trim();
  const instanceLabel = String(template.instance_label || template.label || baseLabel).trim();
  const instanceKey = String(template.instance_key || template.key || baseKey).trim();
  if (!baseKey && !instanceKey) return null;
  return {
    id: String(template.id || `gen-${instanceKey || baseKey}`),
    key: instanceKey || baseKey,
    base_key: baseKey,
    label: instanceLabel,
    base_label: baseLabel,
    source: String(template.source || "").trim(),
    default_grouping: String(template.default_grouping || "module").trim(),
    description: String(template.description || "").trim(),
    code: String(template.code || moduleTemplateToCode({
      key: baseKey,
      label: baseLabel,
      instance_key: instanceKey || baseKey,
      instance_label: instanceLabel,
      source: template.source,
      default_grouping: template.default_grouping,
      description: template.description,
    })),
    created_at: String(template.created_at || new Date().toISOString()),
  };
}

function renderGeneratedModules() {
  const root = document.getElementById("overview-module-factory");
  const metaEl = document.getElementById("overview-module-factory-meta");
  if (!root || !metaEl) return;
  if (!state.generatedModules.length) {
    root.innerHTML = '<div class="empty-hint">先选模板，再输入名称，点“生成并保存”即可生成同款模块实例。</div>';
    metaEl.innerHTML = '<span class="empty-hint">暂无已生成模块</span>';
    return;
  }
  const current = state.generatedModules[state.generatedModules.length - 1];
  metaEl.innerHTML = `
    <div><span>已生成</span><strong>${state.generatedModules.length}</strong></div>
    <div><span>当前模块</span><strong>${escapeHtml(current.label)}</strong></div>
    <div><span>生成方式</span><strong>${escapeHtml(current.default_grouping)}</strong></div>
  `;
  root.innerHTML = window.CommunityComponents
    ? [
        window.CommunityComponents.renderSection({
          title: `当前模块实例 · ${current.label}`,
          count: 1,
          countLabel: "个",
          sectionClass: "module-block module-factory-preview-block",
          bodyHtml: `
            <div class="module-factory-preview-inner">
              <div class="module-factory-preview-line"><strong>模板来源：</strong><span>${escapeHtml(current.base_label || current.label)}</span></div>
              <div class="module-factory-preview-line"><strong>实例名称：</strong><span>${escapeHtml(current.label)}</span></div>
              <div class="module-factory-preview-line"><strong>数据源：</strong><span>${escapeHtml(current.source || "unknown")}</span></div>
              <div class="module-factory-preview-line"><strong>分组方式：</strong><span>${escapeHtml(current.default_grouping)}</span></div>
              <div class="module-factory-preview-line"><strong>说明：</strong><span>${escapeHtml(current.description || "无")}</span></div>
              <pre class="module-code-block">${escapeHtml(current.code)}</pre>
            </div>
          `,
        }),
        state.generatedModules
          .slice()
          .reverse()
          .map((module) => window.CommunityComponents.renderModuleInstanceCard(module, { active: module.id === current.id }))
          .join(""),
      ].join("")
    : "";
}

function renderGeneratedModuleSpotlight() {
  const root = document.getElementById("overview-generated-modules");
  if (!root) return;
  if (!state.generatedModules.length) {
    root.innerHTML = '<div class="empty-hint">还没有生成复用实例。点击左侧模板卡上的“直接生成”即可。</div>';
    return;
  }
  const latest = state.generatedModules[state.generatedModules.length - 1];
  const recent = state.generatedModules.slice(-3).reverse();
  root.innerHTML = recent
    .map((module) => window.CommunityComponents.renderModuleInstanceCard(module, { active: module.id === latest.id }))
    .join("");
}

function buildModuleInstanceFromTemplate(template, instanceLabel) {
  const label = String(instanceLabel || template.label || "").trim();
  const keySuffix = label ? label.replace(/[^\w\u4e00-\u9fff]+/g, "-").toLowerCase() : "";
  const instanceKey = keySuffix ? `${template.key}__${keySuffix}` : `${template.key}__${Date.now()}`;
  return normalizeGeneratedModule({
    ...template,
    id: `gen-${instanceKey}`,
    instance_key: instanceKey,
    instance_label: label,
    base_key: template.key,
    base_label: template.label,
    code: moduleTemplateToCode({
      ...template,
      instance_key: instanceKey,
      instance_label: label,
    }),
    created_at: new Date().toISOString(),
  });
}

function renderModuleFactoryPreview(moduleKey) {
  const template = getModuleTemplate(moduleKey);
  if (!template) return;
  state.selectedModuleTemplateKey = template.key;
  const nameInput = document.getElementById("module-factory-name-input");
  if (nameInput && !String(nameInput.value || "").trim()) {
    nameInput.value = `${template.label} - 复用实例`;
  }
  const instance = buildModuleInstanceFromTemplate(template, String(nameInput?.value || "").trim() || `${template.label} - 复用实例`);
  state.generatedModules.push(instance);
  saveModuleFactoryState();
  renderHomeOverview();
}

function scrollToModuleFactory() {
  const panel = document.getElementById("module-factory-panel");
  if (panel) {
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function openModuleFactoryPanel() {
  state.moduleKey = "all";
  state.page = 1;
  applyFiltersAndRender();
  window.setTimeout(scrollToModuleFactory, 80);
}

function renderHomeOverview() {
  const section = document.getElementById("overview-home");
  const quickPills = document.getElementById("module-quick-pills");
  const heroSummary = document.getElementById("hero-summary");
  const heroTotalItems = document.getElementById("hero-total-items");
  const heroNew7d = document.getElementById("hero-new-7d");
  const heroBlogCount = document.getElementById("hero-blog-count");
  const heroHealthScore = document.getElementById("hero-health-score");
  const heroHighlights = document.getElementById("hero-highlights");
  const moduleCounts = document.getElementById("overview-module-counts");
  const hotTags = document.getElementById("overview-hot-tags");
  const manifestList = document.getElementById("overview-module-manifest");
  const factoryCopyBtn = document.getElementById("module-factory-copy-btn");
  const factoryCopyJsonBtn = document.getElementById("module-factory-copy-json-btn");
  const factoryClearBtn = document.getElementById("module-factory-clear-btn");
  const factoryGenerateBtn = document.getElementById("module-factory-generate-btn");
  const factoryNameInput = document.getElementById("module-factory-name-input");
  const weekNewEl = document.getElementById("ops-week-new");
  const weekAuthorsEl = document.getElementById("ops-week-authors");
  const deadLinksEl = document.getElementById("ops-dead-links");
  const stale30El = document.getElementById("ops-stale-30");
  const moduleFreqEl = document.getElementById("ops-module-frequency");
  const leaderboardEl = document.getElementById("overview-leaderboard");
  const monthlyFeaturedEl = document.getElementById("overview-monthly-featured");
  const healthScoreEl = document.getElementById("community-health-score");
  const healthLabelEl = document.getElementById("community-health-label");
  const healthValueEl = document.getElementById("community-health-value");
  if (!section || !moduleCounts || !hotTags || !manifestList || !weekNewEl || !weekAuthorsEl || !deadLinksEl || !stale30El || !moduleFreqEl || !leaderboardEl || !monthlyFeaturedEl || !healthScoreEl || !healthLabelEl || !healthValueEl) return;

  const isHome = state.moduleKey === "all";
  section.hidden = !isHome;
  if (quickPills) quickPills.hidden = isHome;
  document.body.classList.toggle("is-home-overview", isHome);
  if (!isHome) {
    closeAuthorPanel();
    return;
  }

  // Keep overview module counts aligned with list filtering semantics,
  // so "总览模块计数" and "模块页数量" use the same quality rules.
  const overviewRows = state.allItems.filter((item) => matchesQualityFilter(item));
  const counts = new Map();
  overviewRows.forEach((item) => {
    const m = normalizeModuleName(item.module);
    counts.set(m, (counts.get(m) || 0) + 1);
  });
  moduleCounts.innerHTML = MODULE_ORDER.map((m) => `<div><span>${escapeHtml(m)}</span><strong>${counts.get(m) || 0}</strong></div>`).join("");

  const tagCounter = new Map();
  state.allItems.forEach((item) => {
    (item.tags || []).forEach((tag) => {
      const t = String(tag || "").trim();
      if (!t) return;
      tagCounter.set(t, (tagCounter.get(t) || 0) + 1);
    });
  });
  const hotRows = Array.from(tagCounter.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 14);
  hotTags.innerHTML = hotRows.length
    ? hotRows.map(([tag, count]) => `<button type="button" class="tag hot-tag" data-hot-tag="${escapeHtml(tag)}">${escapeHtml(tag)} (${count})</button>`).join("")
    : '<span class="empty-hint">暂无热门标签</span>';
  if (!state.selectedModuleTemplateKey) {
    const firstTemplate = Array.isArray(state.moduleManifest?.modules) ? state.moduleManifest.modules[0] : null;
    if (firstTemplate) {
      state.selectedModuleTemplateKey = String(firstTemplate.key || firstTemplate.label || "").trim();
    }
  }
  manifestList.innerHTML = renderModuleManifest(state.moduleManifest);
  renderGeneratedModuleSpotlight();
  renderGeneratedModules();

  if (factoryCopyBtn) {
    factoryCopyBtn.disabled = !state.generatedModules.length;
    factoryCopyBtn.onclick = async () => {
      const current = state.generatedModules[state.generatedModules.length - 1];
      if (!current) return;
      try {
        await navigator.clipboard.writeText(current.code || "");
        window.alert(`已复制模块代码：${current.label}`);
      } catch (_err) {
        window.alert(current.code || "");
      }
    };
  }

  if (factoryCopyJsonBtn) {
    factoryCopyJsonBtn.disabled = !state.generatedModules.length;
    factoryCopyJsonBtn.onclick = async () => {
      const current = state.generatedModules[state.generatedModules.length - 1];
      if (!current) return;
      const text = JSON.stringify(current, null, 2);
      try {
        await navigator.clipboard.writeText(text);
        window.alert(`已复制模块配置：${current.label}`);
      } catch (_err) {
        window.alert(text);
      }
    };
  }

  if (factoryClearBtn) {
    factoryClearBtn.disabled = !state.generatedModules.length;
    factoryClearBtn.onclick = () => {
      state.generatedModules = [];
      state.selectedModuleTemplateKey = "";
      if (factoryNameInput) factoryNameInput.value = "";
      saveModuleFactoryState();
      renderHomeOverview();
    };
  }

  if (factoryGenerateBtn) {
    factoryGenerateBtn.onclick = () => {
      const selectedKey = String(state.selectedModuleTemplateKey || "").trim();
      const template = getModuleTemplate(selectedKey);
      if (!template) {
        window.alert("请先点击上方模块卡选择一个模板。");
        return;
      }
      const instanceLabel = String(factoryNameInput?.value || "").trim() || `${template.label} - 复用实例`;
      const instance = buildModuleInstanceFromTemplate(template, instanceLabel);
      state.generatedModules.push(instance);
      saveModuleFactoryState();
      renderHomeOverview();
      applyFiltersAndRender();
    };
  }

  if (factoryNameInput) {
    factoryNameInput.onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        factoryGenerateBtn?.click();
      }
    };
  }

  const snapshot = getOverviewSnapshot();
  const metrics = snapshot.metrics;
  const healthScore = snapshot.healthScore;
  const healthLabel = healthScore >= 85 ? "优秀" : healthScore >= 65 ? "良好" : healthScore >= 45 ? "待加强" : "需修复";
  const visibleCount = overviewRows.length;
  const blogCount = overviewRows.filter((item) => item.kind === "blog").length;
  if (heroSummary) {
    heroSummary.textContent = `当前可见 ${visibleCount} 条内容，近 7 天更新 ${metrics.weekNew} 条，健康评分 ${healthScore}，已保存 ${state.generatedModules.length} 个复用实例。`;
  }
  if (heroTotalItems) heroTotalItems.textContent = String(visibleCount);
  if (heroNew7d) heroNew7d.textContent = String(metrics.weekNew);
  if (heroBlogCount) heroBlogCount.textContent = String(blogCount);
  if (heroHealthScore) heroHealthScore.textContent = String(healthScore);
  if (heroHighlights) {
    const highlights = sortItems([...overviewRows], "updated_desc").slice(0, 4);
    heroHighlights.innerHTML = highlights.length
      ? highlights
          .map(
            (item) => `
              <button type="button" class="hero-highlight-item detail-btn" data-item-id="${escapeHtml(item.id)}">
                <span class="hero-highlight-module">${escapeHtml(normalizeModuleName(item.module))}</span>
                <strong>${escapeHtml(item.title)}</strong>
                <small>${escapeHtml(item.source || "社区")}</small>
              </button>
            `
          )
          .join("")
      : '<div class="empty-hint">暂无可展示条目</div>';
  }
  healthScoreEl.innerHTML = `
    <div class="health-bar">
      <span style="width:${healthScore}%"></span>
    </div>
    <p>基于链接有效性、条目新鲜度与周活跃度计算。</p>
  `;
  healthLabelEl.textContent = healthLabel;
  healthValueEl.textContent = String(healthScore);
  weekNewEl.textContent = String(metrics.weekNew);
  weekAuthorsEl.textContent = String(metrics.weekAuthors);
  deadLinksEl.textContent = String(metrics.deadLinks);
  stale30El.textContent = String(metrics.stale30);
  moduleFreqEl.innerHTML = metrics.moduleRows.slice(0, 5).map(([m, c]) => `<div><span>${escapeHtml(m)}</span><strong>${c}/周</strong></div>`).join("");

  const contributors = new Map();
  state.allItems.forEach((item) => {
    const key = getAuthorIdentity(item) || getAuthorDisplayName(item);
    const label = getAuthorDisplayName(item);
    if (!key) return;
    const row = contributors.get(key) || { label, count: 0 };
    row.count += 1;
    if (!row.label || row.label === "社区用户") row.label = label;
    contributors.set(key, row);
  });
  const topContributors = Array.from(contributors.entries())
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 8);
  leaderboardEl.innerHTML = topContributors.length
    ? topContributors
        .map(
          ([key, row], idx) =>
            `<div><span>${idx + 1}. ${escapeHtml(row.label)}</span><button type="button" class="ghost-btn author-open-btn" data-author="${escapeHtml(key)}">${row.count} 条</button></div>`
        )
        .join("")
    : '<span class="empty-hint">暂无贡献数据</span>';

  const now = new Date();
  const thisMonth = state.allItems.filter((x) => {
    const t = new Date(getItemTimeMs(x));
    if (Number.isNaN(t.getTime())) return false;
    return t.getFullYear() === now.getFullYear() && t.getMonth() === now.getMonth();
  });
  const featured = sortItems(thisMonth.filter((x) => getItemQualityTier(x) === "featured"), "updated_desc").slice(0, 8);
  monthlyFeaturedEl.innerHTML = featured.length
    ? featured
        .map(
          (x) =>
            `<div><span>${escapeHtml(x.title)}</span><button type="button" class="ghost-btn detail-btn" data-item-id="${escapeHtml(x.id)}">查看</button></div>`
        )
        .join("")
    : '<span class="empty-hint">本月暂无精选条目</span>';
}

function renderEventCards() {
  const root = document.getElementById("event-list");
  const pager = document.querySelector(".events-pagination");
  if (!root) return;
  root.innerHTML = "";
  const isHome = state.moduleKey === "all";
  root.classList.toggle("is-list-mode", state.viewMode === "list" && !isHome);

  if (!state.filtered.length) {
    root.innerHTML = '<div class="empty-hint">没有匹配内容，请调整筛选条件。</div>';
    if (pager) pager.hidden = isHome;
    renderPagination();
    return;
  }

  if (isHome) {
    const rows = sortItems(state.filtered, "updated_desc").slice(0, 10);
    root.innerHTML = window.CommunityComponents
      ? window.CommunityComponents.renderSection({
          title: "最近更新",
          count: rows.length,
          countLabel: "条",
          bodyHtml: rows.map((item) => renderItemCard(item)).join(""),
        })
      : `
      <section class="module-block">
        <div class="module-block-head">
          <h2>最近更新</h2>
          <span>展示 ${rows.length} 条</span>
        </div>
        <div class="module-block-list recent-full-grid">${rows.map((item) => renderItemCard(item)).join("")}</div>
      </section>
    `;
    if (pager) pager.hidden = true;
  } else if (state.moduleKey === "forum") {
    const groups = groupRowsByCategory(state.filtered);
    root.innerHTML = window.CommunityComponents
      ? window.CommunityComponents.renderGroupedSections({
          groups,
          order: FORUM_CATEGORY_ORDER,
          renderItem: renderItemCard,
          sectionClass: "module-block forum-category-block",
          bodyClass: "module-block-list recent-full-grid",
          countLabel: "条",
        })
      : [
          ...FORUM_CATEGORY_ORDER.filter((category) => groups.has(category)),
          ...Array.from(groups.keys())
            .filter((category) => !FORUM_CATEGORY_ORDER.includes(category))
            .sort((a, b) => a.localeCompare(b, "zh-CN")),
        ]
          .map((category) => {
            const rows = groups.get(category) || [];
            return `
          <section class="module-block forum-category-block">
            <div class="module-block-head">
              <h2>${escapeHtml(category)}</h2>
              <span>${rows.length} 条</span>
            </div>
            <div class="module-block-list recent-full-grid">${rows.map((item) => renderItemCard(item)).join("")}</div>
          </section>
        `;
          })
          .join("");
    if (pager) pager.hidden = true;
  } else {
    const groups = groupRowsByContentCategory(state.filtered);
    root.innerHTML = window.CommunityComponents
      ? window.CommunityComponents.renderGroupedSections({
          groups,
          renderItem: renderItemCard,
          sectionClass: "module-block forum-category-block",
          bodyClass: "module-block-list recent-full-grid",
          countLabel: "条",
        })
      : Array.from(groups.keys())
          .sort((a, b) => a.localeCompare(b, "zh-CN"))
          .map((category) => {
            const rows = groups.get(category) || [];
            return `
          <section class="module-block forum-category-block">
            <div class="module-block-head">
              <h2>${escapeHtml(category)}</h2>
              <span>${rows.length} 条</span>
            </div>
            <div class="module-block-list recent-full-grid">${rows.map((item) => renderItemCard(item)).join("")}</div>
          </section>
        `;
          })
          .join("");
    if (pager) pager.hidden = true;
  }
}

function closeDetailDrawer() {
  const drawer = document.getElementById("event-detail-drawer");
  if (!drawer) return;
  drawer.hidden = true;
  state.activeItemId = "";
}

async function openDetailDrawer(item) {
  const drawer = document.getElementById("event-detail-drawer");
  const titleEl = document.getElementById("detail-title");
  const metaEl = document.getElementById("detail-meta");
  const summaryEl = document.getElementById("detail-summary");
  const tagsEl = document.getElementById("detail-tags");
  const openLink = document.getElementById("detail-open-link");
  const contentEl = document.getElementById("detail-content");
  if (!drawer || !titleEl || !metaEl || !summaryEl || !tagsEl || !openLink || !contentEl) return;

  state.activeItemId = item.id;
  titleEl.textContent = item.title || "未命名条目";
  metaEl.innerHTML = `
    <span>${escapeHtml(normalizeModuleName(item.module))}</span>
    <span>${escapeHtml(getCardSource(item))}</span>
    <span>${escapeHtml(formatDateTime(item.updated_at || item.created_at))}</span>
    <span class="quality-badge quality-${escapeHtml(getItemQualityTier(item))}">${escapeHtml(QUALITY[getItemQualityTier(item)] || QUALITY.usable)}</span>
  `;
  summaryEl.textContent = getCardSummary(item) || "暂无摘要。";
  tagsEl.innerHTML = getCardTags(item).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");

  if (isHttpUrl(item.url)) {
    openLink.href = item.url;
    openLink.classList.remove("is-disabled");
  } else {
    openLink.href = "#";
    openLink.classList.add("is-disabled");
  }

  contentEl.hidden = true;
  contentEl.textContent = "";

  if (item.kind === "blog" && item.blog_id) {
    try {
      if (!item.content_markdown) {
        const detail = await fetchJson(`/api/resources/blog-posts/${item.blog_id}`);
        item.content_markdown = String(detail?.content_markdown || "").trim();
      }
      if (item.content_markdown) {
        contentEl.hidden = false;
        contentEl.textContent = item.content_markdown;
      }
    } catch (err) {
      contentEl.hidden = false;
      contentEl.textContent = `博客正文加载失败：${formatGatewayError(err)}`;
    }
  }

  drawer.hidden = false;
}

function applyFiltersAndRender() {
  // Guardrail: "博客"标签只适用于开源分享模块，切到其他模块时自动清理，
  // 避免出现“有数据但被跨模块标签筛空”的误导状态。
  if (state.moduleKey !== "all" && state.moduleKey !== "sharing" && state.tag === MODULE.blogTag) {
    state.tag = "";
  }

  const q = state.search.trim().toLowerCase();
  const targetModule = moduleKeyToLabel(state.moduleKey);

  const baseRows = state.allItems.filter((item) => {
    if (state.moduleKey !== "all" && normalizeModuleName(item.module) !== targetModule) return false;
    if (!matchesQualityFilter(item)) return false;
    if (state.timeWindow === "recent7" && !isWithinDays(item, 7)) return false;
    if (state.timeWindow === "recent30" && !isWithinDays(item, 30)) return false;
    if (state.timeWindow === "undated" && getItemTimeMs(item) > 0) return false;
    if (!q) return true;
    const haystack = [item.title, item.summary, item.module, item.source, ...(item.tags || [])].join(" ").toLowerCase();
    return haystack.includes(q);
  });

  renderModuleQuickPills(baseRows);
  renderTagFilters(baseRows);

  const rows = state.tag ? baseRows.filter((item) => (item.tags || []).includes(state.tag)) : baseRows;
  state.filtered = sortItems(rows, state.sort);

  document.querySelectorAll("#module-tabs button[data-module-key]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.moduleKey === state.moduleKey);
  });
  document.querySelectorAll("#time-tabs button[data-time]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.time === state.timeWindow);
  });
  document.querySelectorAll("#view-mode-tabs button[data-view]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.view === state.viewMode);
  });
  document.querySelectorAll("#quality-tabs button[data-quality]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.quality === state.qualityTier);
  });
  document.querySelectorAll(".main-nav a[data-nav-module-key]").forEach((link) => {
    const active = String(link.dataset.navModuleKey || "all") === state.moduleKey;
    link.classList.toggle("is-active", active);
  });

  updatePageHeader();
  updateSelectedHint();
  renderHomeOverview();
  renderEventCards();
}

async function loadAllData() {
  const fetchBlogItemsCompat = async () => {
    try {
      const result = await fetchJson("/api/resources/blog-posts?page=1&page_size=120&status=all&include_content=false");
      return Array.isArray(result?.items) ? result.items : [];
    } catch (_) {
      const fallback = await fetchJson("/api/resources/blog-posts");
      return Array.isArray(fallback?.items) ? fallback.items : [];
    }
  };

  const [communityRes, blogRes, catalogRes, qualityRes, forumRes, manifestRes] = await Promise.allSettled([
    fetchJson("/api/resources/community-items?limit=500"),
    fetchBlogItemsCompat(),
    fetchJson("/api/resources/catalog"),
    fetchJson("/api/resources/community-items/quality-report?stale_days=30"),
    fetchJson("/api/community/forum-items?org=openKG-field&per_page=30"),
    fetchJson("/api/resources/community-items/modules-manifest"),
  ]);

  const communityItems = communityRes.status === "fulfilled" && Array.isArray(communityRes.value?.items)
    ? communityRes.value.items.map(normalizeCommunityItem)
    : [];
  const blogItems = blogRes.status === "fulfilled" && Array.isArray(blogRes.value) ? blogRes.value.map(normalizeBlogItem) : [];
  const catalogItems = catalogRes.status === "fulfilled" ? normalizeCatalogItems(catalogRes.value) : [];
  const forumItems = forumRes.status === "fulfilled" && Array.isArray(forumRes.value?.items) ? forumRes.value.items.map((item, index) => ({
    id: `f-${item.id || index + 1}`,
    title: stripTeacherExportHint(item.title || "主题讨论条目"),
    summary: stripTeacherExportHint(item.summary || ""),
    url: item.html_url || item.url || "",
    module: MODULE.forum,
    tags: Array.isArray(item.labels) ? item.labels.map((x) => String(x || "").trim()).filter(Boolean) : [],
    category: String(item.category || "综合讨论").trim() || "综合讨论",
    source: String(item.source || "openkg_field_topic").trim() || "openkg_field_topic",
    created_at: item.created_at || item.updated_at || "",
    updated_at: item.updated_at || item.created_at || "",
    kind: "community",
  })) : [];
  state.moduleManifest = manifestRes.status === "fulfilled" && manifestRes.value && typeof manifestRes.value === "object"
    ? manifestRes.value
    : { version: "1.0", modules: [] };
  state.generatedModules = loadModuleFactoryState();
  state.qualitySummary = qualityRes.status === "fulfilled" && qualityRes.value?.summary ? qualityRes.value.summary : { invalid_url: 0, stale: 0 };

  state.allItems = dedupeItems([...communityItems, ...blogItems, ...catalogItems, ...forumItems]);
  state.page = 1;
  applyFiltersAndRender();

  if (communityRes.status !== "fulfilled" && blogRes.status !== "fulfilled" && catalogRes.status !== "fulfilled" && forumRes.status !== "fulfilled") {
    const root = document.getElementById("event-list");
    if (root) {
      root.innerHTML = `<div class="empty-hint">数据加载失败：${escapeHtml(
        `${formatGatewayError(communityRes.reason)} / ${formatGatewayError(blogRes.reason)} / ${formatGatewayError(catalogRes.reason)} / ${formatGatewayError(forumRes.reason)}`
      )}</div>`;
    }
  }
}

function parseTagsInput(value) {
  return String(value || "")
    .split(/[,\uFF0C]/)
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 20);
}

function applyBlogTemplate() {
  const titleInput = document.getElementById("blog-title-input");
  const summaryInput = document.getElementById("blog-summary-input");
  const tagsInput = document.getElementById("blog-tags-input");
  const contentInput = document.getElementById("blog-content-input");
  if (titleInput && !String(titleInput.value || "").trim()) titleInput.value = "[开源分享] 请填写主题名称";
  if (summaryInput && !String(summaryInput.value || "").trim()) summaryInput.value = "背景：...；方案：...；价值：...。";
  if (tagsInput && !String(tagsInput.value || "").trim()) tagsInput.value = "开源分享, 工具实践, 社区共建";
  if (contentInput && !String(contentInput.value || "").trim()) {
    contentInput.value = [
      "# 背景与问题",
      "",
      "- 当前问题：",
      "- 目标收益：",
      "",
      "# 方案与实现",
      "",
      "- 技术路线：",
      "- 核心步骤：",
      "",
      "# 使用建议",
      "",
      "- 适用场景：",
      "- 后续计划：",
    ].join("\n");
  }
}

function validateSharingTemplate(title, summary, tags) {
  if (!/^\[[^\]]{2,14}\]\s*.+/.test(title)) {
    return "标题需符合 `[领域] 具体主题` 格式。";
  }
  const summaryLen = String(summary || "").trim().length;
  if (summaryLen < 30 || summaryLen > 220) {
    return "摘要建议保持在 30-220 字。";
  }
  if (!Array.isArray(tags) || tags.length < 3) {
    return "标签至少填写 3 个。";
  }
  const hasSharingTag = tags.some((x) => String(x || "").trim() === "开源分享");
  if (!hasSharingTag) return "标签需包含 `开源分享`。";
  return "";
}

function setBlogEditorTip(message, isError = false) {
  const tip = document.getElementById("blog-editor-tip");
  if (!tip) return;
  const text = String(message || "").trim();
  if (!text) {
    tip.hidden = true;
    tip.textContent = "";
    tip.classList.remove("is-error", "is-success");
    return;
  }
  tip.hidden = false;
  tip.textContent = text;
  tip.classList.toggle("is-error", isError);
  tip.classList.toggle("is-success", !isError);
}

function clearBlogEditorForm() {
  ["blog-title-input", "blog-author-input", "blog-summary-input", "blog-tags-input", "blog-url-input", "blog-content-input"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const avatarInput = document.getElementById("blog-author-avatar-file-input");
  const avatarHint = document.getElementById("blog-author-avatar-hint");
  if (avatarInput) avatarInput.value = "";
  if (avatarHint) avatarHint.textContent = "未选择头像（可选）";
}

function renderAuthUI() {
  const loginBtn = document.getElementById("open-login-modal");
  const userChip = document.getElementById("auth-user-chip");
  const logoutBtn = document.getElementById("auth-logout-btn");
  const adminBtn = document.getElementById("open-admin-modal");
  const writeTopBtn = document.getElementById("open-blog-editor");
  const writeSideBtn = document.getElementById("open-blog-editor-side");
  const user = state.auth?.user || null;
  const loggedIn = Boolean(state.auth?.token && user);
  if (loginBtn) loginBtn.hidden = loggedIn;
  if (userChip) {
    userChip.hidden = !loggedIn;
    userChip.textContent = loggedIn ? `${user.nickname || user.username}（${user.role === "admin" ? "管理员" : "用户"}）` : "";
  }
  if (logoutBtn) logoutBtn.hidden = !loggedIn;
  if (adminBtn) adminBtn.hidden = !(loggedIn && currentRole() === "admin");
  const writeLabel = loggedIn ? "写博客" : "登录后写博客";
  if (writeTopBtn) writeTopBtn.textContent = writeLabel;
  if (writeSideBtn) writeSideBtn.textContent = writeLabel;
}

function setAdminTip(message, isError = false) {
  const tip = document.getElementById("admin-tip");
  if (!tip) return;
  const text = String(message || "").trim();
  if (!text) {
    tip.hidden = true;
    tip.textContent = "";
    tip.classList.remove("is-error", "is-success");
    return;
  }
  tip.hidden = false;
  tip.textContent = text;
  tip.classList.toggle("is-error", isError);
  tip.classList.toggle("is-success", !isError);
}

function closeAdminModal() {
  const modal = document.getElementById("admin-modal");
  if (modal) modal.hidden = true;
}

async function refreshAdminPanel() {
  const moderationInput = document.getElementById("moderation-enabled-input");
  const listEl = document.getElementById("admin-user-list");
  try {
    const [settings, users] = await Promise.all([fetchJson("/api/auth/settings", { retry: 0 }), fetchJson("/api/auth/users", { retry: 0 })]);
    if (moderationInput) moderationInput.checked = Boolean(settings?.moderation_enabled);
    const rows = Array.isArray(users?.items) ? users.items : [];
    if (listEl) {
      listEl.hidden = false;
      listEl.textContent = rows.length
        ? `用户列表：\n${rows.map((x, i) => `${i + 1}. ${x.username} / ${x.nickname} / ${x.role}`).join("\n")}`
        : "暂无用户";
    }
    setAdminTip("", false);
  } catch (err) {
    setAdminTip(formatGatewayError(err), true);
  }
}

async function openAdminModal() {
  if (currentRole() !== "admin") return;
  const modal = document.getElementById("admin-modal");
  if (!modal) return;
  modal.hidden = false;
  await refreshAdminPanel();
}

async function saveModerationSetting() {
  const moderationInput = document.getElementById("moderation-enabled-input");
  try {
    await fetchJson("/api/auth/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ moderation_enabled: Boolean(moderationInput?.checked) }),
      retry: 0,
    });
    setAdminTip("已保存审核设置。", false);
  } catch (err) {
    setAdminTip(formatGatewayError(err), true);
  }
}

async function createMemberUser() {
  const username = String(document.getElementById("new-user-username")?.value || "").trim();
  const password = String(document.getElementById("new-user-password")?.value || "").trim();
  const nickname = String(document.getElementById("new-user-nickname")?.value || "").trim();
  if (!username || !password || !nickname) {
    setAdminTip("请完整填写用户名、密码、昵称。", true);
    return;
  }
  try {
    await fetchJson("/api/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, nickname }),
      retry: 0,
    });
    setAdminTip("普通用户创建成功。", false);
    await refreshAdminPanel();
  } catch (err) {
    setAdminTip(formatGatewayError(err), true);
  }
}

function setLoginTip(message, isError = false) {
  const tip = document.getElementById("login-tip");
  if (!tip) return;
  const text = String(message || "").trim();
  if (!text) {
    tip.hidden = true;
    tip.textContent = "";
    tip.classList.remove("is-error", "is-success");
    return;
  }
  tip.hidden = false;
  tip.textContent = text;
  tip.classList.toggle("is-error", isError);
  tip.classList.toggle("is-success", !isError);
}

function clearLoginSensitiveFields() {
  const accountInput = document.getElementById("login-phone-input");
  const passwordInput = document.getElementById("login-password-input");
  const nicknameInput = document.getElementById("register-nickname-input");
  if (accountInput) accountInput.value = "";
  if (passwordInput) passwordInput.value = "";
  if (nicknameInput) nicknameInput.value = "";
}

function rebuildAccountInput() {
  const oldInput = document.getElementById("login-phone-input");
  if (!oldInput || !oldInput.parentElement) return;
  const newInput = oldInput.cloneNode(false);
  newInput.id = "login-phone-input";
  newInput.name = `login-account-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  newInput.type = "text";
  newInput.value = "";
  newInput.defaultValue = "";
  newInput.setAttribute("value", "");
  newInput.setAttribute("autocomplete", "off");
  newInput.setAttribute("autocapitalize", "off");
  newInput.setAttribute("autocorrect", "off");
  newInput.setAttribute("spellcheck", "false");
  newInput.setAttribute("data-1p-ignore", "true");
  newInput.setAttribute("data-lpignore", "true");
  oldInput.parentElement.replaceChild(newInput, oldInput);
}

function rebuildPasswordInput() {
  const oldInput = document.getElementById("login-password-input");
  if (!oldInput || !oldInput.parentElement) return;
  const newInput = oldInput.cloneNode(false);
  newInput.id = "login-password-input";
  newInput.name = `login-password-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  newInput.type = "password";
  newInput.classList.add("masked-password-input");
  newInput.placeholder = oldInput.placeholder || "请输入密码";
  newInput.setAttribute("autocomplete", "off");
  newInput.setAttribute("autocapitalize", "off");
  newInput.setAttribute("autocorrect", "off");
  newInput.setAttribute("spellcheck", "false");
  newInput.setAttribute("data-1p-ignore", "true");
  newInput.setAttribute("data-lpignore", "true");
  newInput.setAttribute("readonly", "readonly");
  oldInput.parentElement.replaceChild(newInput, oldInput);
  newInput.addEventListener("focus", () => {
    newInput.removeAttribute("readonly");
  });
  newInput.addEventListener("input", () => {
    state.authPasswordTouched = true;
  });
}

function hardClearPasswordInput() {
  const input = document.getElementById("login-password-input");
  if (!input) return;
  input.value = "";
  input.defaultValue = "";
  input.setAttribute("value", "");
  input.type = "password";
  input.value = "";
}

function hardClearAccountInput() {
  const input = document.getElementById("login-phone-input");
  if (!input) return;
  input.value = "";
  input.defaultValue = "";
  input.setAttribute("value", "");
}

function renderPasswordLockedState() {
  const group = document.getElementById("auth-password-group");
  if (!group) return;
  const staleUnlockBtn = document.getElementById("login-password-enable-btn");
  if (staleUnlockBtn) staleUnlockBtn.remove();
  let input = document.getElementById("login-password-input");
  if (!input) {
    input = document.createElement("input");
    input.id = "login-password-input";
    input.type = "password";
    input.placeholder = "请输入密码";
    input.autocomplete = "off";
    input.autocapitalize = "off";
    input.autocorrect = "off";
    input.spellcheck = false;
    group.appendChild(input);
  }
  input.removeAttribute("readonly");
  input.addEventListener("input", () => {
    state.authPasswordTouched = true;
  });
}

function stopPasswordAutofillGuard() {
  if (state.authPasswordGuardTimer) {
    clearInterval(state.authPasswordGuardTimer);
    state.authPasswordGuardTimer = null;
  }
}

function startPasswordAutofillGuard() {
  stopPasswordAutofillGuard();
  const passwordInput = document.getElementById("login-password-input");
  if (!passwordInput) return;
  const started = Date.now();
  state.authPasswordGuardTimer = setInterval(() => {
    const modal = document.getElementById("login-modal");
    if (!modal || modal.hidden || state.authPasswordTouched) {
      stopPasswordAutofillGuard();
      return;
    }
    if (passwordInput.value) passwordInput.value = "";
  }, 180);
}

function openLoginModal() {
  const modal = document.getElementById("login-modal");
  if (!modal) return;
  rebuildAccountInput();
  renderPasswordLockedState();
  setAuthMode("password");
  setAuthChannel("phone");
  setLoginTip("", false);
  state.authPasswordTouched = false;
  clearLoginSensitiveFields();
  hardClearAccountInput();
  hardClearPasswordInput();
  modal.hidden = false;
  setTimeout(() => {
    clearLoginSensitiveFields();
    hardClearAccountInput();
    hardClearPasswordInput();
  }, 0);
  setTimeout(() => {
    clearLoginSensitiveFields();
    hardClearAccountInput();
    hardClearPasswordInput();
  }, 180);
  setTimeout(() => {
    rebuildAccountInput();
    renderPasswordLockedState();
    hardClearAccountInput();
    hardClearPasswordInput();
  }, 420);
  startPasswordAutofillGuard();
}

function closeLoginModal() {
  const modal = document.getElementById("login-modal");
  if (!modal) return;
  stopPasswordAutofillGuard();
  state.authPasswordTouched = false;
  clearLoginSensitiveFields();
  hardClearAccountInput();
  hardClearPasswordInput();
  modal.hidden = true;
  setTimeout(() => {
    rebuildAccountInput();
    renderPasswordLockedState();
  }, 0);
}

async function submitLogin() {
  const account = String(document.getElementById("login-phone-input")?.value || "").trim();
  const password = String(document.getElementById("login-password-input")?.value || "").trim();
  const nickname = String(document.getElementById("register-nickname-input")?.value || "").trim();
  const btn = document.getElementById("login-submit-btn");
  if (!account) {
    setLoginTip(state.authChannel === "email" ? "请输入邮箱。" : "请输入手机号。", true);
    return;
  }
  if (state.authMethod === "password" && !password) {
    setLoginTip("请输入密码。", true);
    return;
  }
  if (state.authMethod === "register" && !nickname) {
    setLoginTip("注册时请填写昵称。", true);
    return;
  }
  const oldText = btn?.textContent || "登录";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "登录中...";
  }
  try {
    let data;
    const isEmail = state.authChannel === "email";
    if (state.authMethod === "register") {
      await fetchJson("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(isEmail ? { email: account, password, nickname } : { phone: account, password, nickname }),
        retry: 0,
      });
      data = await fetchJson("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(isEmail ? { email: account, password } : { phone: account, password }),
        retry: 0,
      });
    } else {
      data = await fetchJson("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(isEmail ? { email: account, password } : { phone: account, password }),
        retry: 0,
      });
    }
    state.auth = {
      token: String(data?.token || "").trim(),
      user: data?.user && typeof data.user === "object" ? data.user : null,
    };
    saveAuthState();
    renderAuthUI();
    setLoginTip(state.authMethod === "register" ? "注册成功，已自动登录。" : "登录成功。", false);
    closeLoginModal();
    applyFiltersAndRender();
  } catch (err) {
    setLoginTip(formatGatewayError(err), true);
  } finally {
    clearLoginSensitiveFields();
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }
}

function setAuthChannel(channel) {
  state.authChannel = channel === "email" ? "email" : "phone";
  const phoneTab = document.getElementById("auth-tab-phone");
  const emailTab = document.getElementById("auth-tab-email");
  const label = document.getElementById("auth-account-label");
  const input = document.getElementById("login-phone-input");
  if (phoneTab) phoneTab.classList.toggle("is-active", state.authChannel === "phone");
  if (emailTab) emailTab.classList.toggle("is-active", state.authChannel === "email");
  if (label) label.textContent = state.authChannel === "email" ? "邮箱" : "手机号";
  if (input) input.placeholder = state.authChannel === "email" ? "请输入邮箱地址" : "请输入11位手机号";
  setAuthMode(state.authMethod);
}

function setAuthMode(mode) {
  state.authMethod = mode === "register" ? "register" : "password";
  const passwordSwitch = document.getElementById("auth-switch-password");
  const registerSwitch = document.getElementById("auth-switch-register");
  const extra = document.getElementById("register-extra-fields");
  const pwdGroup = document.getElementById("auth-password-group");
  const submit = document.getElementById("login-submit-btn");
  if (passwordSwitch) passwordSwitch.hidden = state.authMethod === "password";
  if (registerSwitch) registerSwitch.hidden = state.authMethod === "register";
  if (extra) extra.hidden = state.authMethod !== "register";
  if (pwdGroup) pwdGroup.hidden = false;
  if (submit) submit.textContent = state.authMethod === "register" ? "注册并登录" : "登录";
  state.authPasswordTouched = false;
}

function logout() {
  clearAuthState();
  renderAuthUI();
  applyFiltersAndRender();
}

function setBlogEditorMode(mode = "create") {
  const submitBtn = document.getElementById("blog-submit-btn");
  const titleEl = document.getElementById("blog-editor-title");
  if (mode === "edit") {
    if (submitBtn) submitBtn.textContent = "保存修改";
    if (titleEl) titleEl.textContent = "编辑社区博客";
  } else {
    if (submitBtn) submitBtn.textContent = "发布";
    if (titleEl) titleEl.textContent = "发布社区博客";
  }
}

function fillBlogEditorForm(item) {
  const titleInput = document.getElementById("blog-title-input");
  const authorInput = document.getElementById("blog-author-input");
  const avatarHint = document.getElementById("blog-author-avatar-hint");
  const summaryInput = document.getElementById("blog-summary-input");
  const tagsInput = document.getElementById("blog-tags-input");
  const urlInput = document.getElementById("blog-url-input");
  const contentInput = document.getElementById("blog-content-input");
  const levelInput = document.getElementById("blog-level-input");

  if (titleInput) titleInput.value = item.title || "";
  if (authorInput) authorInput.value = getAuthorDisplayName(item);
  if (avatarHint) avatarHint.textContent = item.author_avatar_url ? "当前头像已存在（如需替换，请重新选择文件）" : "未选择头像（可选）";
  if (summaryInput) summaryInput.value = item.summary || "";
  if (tagsInput) {
    const tags = (item.tags || []).filter((x) => x && x !== MODULE.blogTag);
    tagsInput.value = tags.join(", ");
  }
  if (urlInput) urlInput.value = item.url || "";
  if (contentInput) contentInput.value = item.content_markdown || "";
  if (levelInput) levelInput.value = normalizeBlogLevelFromItem(item);
}

function openBlogEditor() {
  const modal = document.getElementById("blog-editor-modal");
  const levelInput = document.getElementById("blog-level-input");
  if (!modal) return;
  if (!state.auth?.token) {
    setBlogEditorTip("请先登录后再发布博客。", true);
    openLoginModal();
    return;
  }
  state.editingBlogId = 0;
  setBlogEditorMode("create");
  clearBlogEditorForm();
  const authorInput = document.getElementById("blog-author-input");
  if (authorInput) authorInput.value = String(state.auth?.user?.nickname || "社区用户");
  if (levelInput) levelInput.value = "usable";
  setBlogEditorTip("", false);
  modal.hidden = false;
}

async function openBlogEditorForEdit(blogId) {
  if (!canManageBlogs()) {
    setBlogEditorTip("仅管理员可编辑博客。", true);
    return;
  }
  if (!blogId) return;
  const modal = document.getElementById("blog-editor-modal");
  if (!modal) return;
  const item = state.allItems.find((row) => row.kind === "blog" && Number(row.blog_id) === Number(blogId));
  if (!item) {
    setBlogEditorTip("未找到要编辑的博客条目。", true);
    return;
  }

  const editingItem = { ...item };
  if (!editingItem.content_markdown) {
    try {
      const detail = await fetchJson(`/api/resources/blog-posts/${blogId}`);
      editingItem.content_markdown = String(detail?.content_markdown || "").trim();
      if (detail?.author) editingItem.author = detail.author;
      if (detail?.author_avatar_url) editingItem.author_avatar_url = detail.author_avatar_url;
      editingItem.source = getAuthorDisplayName({ author: detail?.author, source: editingItem.source });
      if (detail?.summary) editingItem.summary = detail.summary;
      if (detail?.share_url) editingItem.url = detail.share_url;
      if (Array.isArray(detail?.tags)) editingItem.tags = detail.tags;
      if (detail?.status) editingItem.blog_status = String(detail.status).toLowerCase();
    } catch (err) {
      setBlogEditorTip(`读取博客详情失败：${formatGatewayError(err)}`, true);
      return;
    }
  }

  state.editingBlogId = Number(blogId);
  setBlogEditorMode("edit");
  fillBlogEditorForm(editingItem);
  setBlogEditorTip("", false);
  modal.hidden = false;
}

function closeBlogEditor() {
  const modal = document.getElementById("blog-editor-modal");
  const levelInput = document.getElementById("blog-level-input");
  if (!modal) return;
  modal.hidden = true;
  state.editingBlogId = 0;
  setBlogEditorMode("create");
  if (levelInput) levelInput.value = "usable";
  setBlogEditorTip("", false);
}

async function submitBlogPost() {
  const title = String(document.getElementById("blog-title-input")?.value || "").trim();
  const author = String(state.auth?.user?.nickname || "").trim() || "社区用户";
  const avatarFileInput = document.getElementById("blog-author-avatar-file-input");
  const avatarFile = avatarFileInput?.files?.[0] || null;
  let authorAvatarUrl = "";
  const summary = String(document.getElementById("blog-summary-input")?.value || "").trim();
  const level = String(document.getElementById("blog-level-input")?.value || "usable").trim();
  const tags = parseTagsInput(document.getElementById("blog-tags-input")?.value || "");
  if (!tags.includes("开源分享")) tags.push("开源分享");
  if (!tags.includes(MODULE.blogTag)) tags.push(MODULE.blogTag);
  if (level === "featured" && !tags.includes("精选")) tags.push("精选");
  if (level !== "featured") {
    const idx = tags.indexOf("精选");
    if (idx >= 0) tags.splice(idx, 1);
  }
  const shareUrlRaw = String(document.getElementById("blog-url-input")?.value || "").trim();
  const content = String(document.getElementById("blog-content-input")?.value || "").trim();
  const btn = document.getElementById("blog-submit-btn");
  if (!state.auth?.token) {
    setBlogEditorTip("请先登录后再发布博客。", true);
    openLoginModal();
    return;
  }

  if (!title) {
    setBlogEditorTip("请先填写标题。", true);
    return;
  }
  if (!content) {
    setBlogEditorTip("请先填写正文。", true);
    return;
  }
  if (shareUrlRaw && !isHttpUrl(shareUrlRaw)) {
    setBlogEditorTip("分享链接必须是 http/https 地址。", true);
    return;
  }
  if (avatarFile && avatarFile.size > 2 * 1024 * 1024) {
    setBlogEditorTip("头像文件不能超过 2MB。", true);
    return;
  }
  const templateErr = level === "draft" ? "" : validateSharingTemplate(title, summary, tags);
  if (templateErr) {
    setBlogEditorTip(templateErr, true);
    return;
  }

  const isEditing = state.editingBlogId > 0;
  const oldText = btn?.textContent || (isEditing ? "保存修改" : "发布");
  if (btn) {
    btn.disabled = true;
    btn.textContent = isEditing ? "保存中..." : "发布中...";
  }

  try {
    if (avatarFile) {
      const dataBase64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const raw = String(reader.result || "");
          const comma = raw.indexOf(",");
          resolve(comma >= 0 ? raw.slice(comma + 1) : "");
        };
        reader.onerror = () => reject(new Error("头像读取失败"));
        reader.readAsDataURL(avatarFile);
      });
      const uploadResp = await fetchJson("/api/resources/blog-avatars/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: avatarFile.name || "avatar.png",
          content_type: avatarFile.type || "image/png",
          data_base64: dataBase64,
        }),
      });
      authorAvatarUrl = String(uploadResp?.avatar_url || "").trim();
    } else if (state.editingBlogId > 0) {
      const old = state.allItems.find((x) => x.kind === "blog" && Number(x.blog_id) === state.editingBlogId);
      authorAvatarUrl = String(old?.author_avatar_url || "").trim();
    }

    const payload = {
      title,
      author,
      author_avatar_url: authorAvatarUrl || null,
      summary,
      content_markdown: content,
      share_url: shareUrlRaw || null,
      tags,
      status: level === "draft" ? "draft" : "published",
    };

    if (isEditing) {
      await fetchJson(`/api/resources/blog-posts/${state.editingBlogId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      await fetchJson("/api/resources/blog-posts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }

    clearBlogEditorForm();
    closeBlogEditor();
    state.moduleKey = "sharing";
    state.tag = MODULE.blogTag;
    await loadAllData();
  } catch (err) {
    setBlogEditorTip(`${isEditing ? "保存失败" : "发布失败"}：${formatGatewayError(err)}`, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }
}

async function deleteBlogPost(blogId) {
  if (!blogId) return;
  const ok = window.confirm(`确认删除博客 #${blogId} 吗？`);
  if (!ok) return;
  try {
    await fetchJson(`/api/resources/blog-posts/${blogId}`, { method: "DELETE" });
    closeDetailDrawer();
    state.moduleKey = "sharing";
    await loadAllData();
  } catch (err) {
    window.alert(`删除失败：${formatGatewayError(err)}`);
  }
}

function bindListActions() {
  const root = document.getElementById("event-list");
  root?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const detailBtn = target.closest(".detail-btn");
    if (detailBtn) {
      const id = String(detailBtn.getAttribute("data-item-id") || "");
      const item = state.allItems.find((row) => row.id === id);
      if (item) await openDetailDrawer(item);
      return;
    }

    const editBtn = target.closest(".blog-edit-btn");
    if (editBtn) {
      const blogId = Number(editBtn.getAttribute("data-blog-id") || "0");
      if (blogId > 0) await openBlogEditorForEdit(blogId);
      return;
    }

    const deleteBtn = target.closest(".blog-delete-btn");
    if (deleteBtn) {
      const blogId = Number(deleteBtn.getAttribute("data-blog-id") || "0");
      if (blogId > 0) await deleteBlogPost(blogId);
    }
  });
}

function bindFilters() {
  const searchInput = document.getElementById("global-search-input");
  const searchBtn = document.getElementById("global-search-btn");
  const sortSelect = document.getElementById("sort-select");
  const resetBtn = document.getElementById("reset-filters-btn");
  const prevBtn = document.getElementById("page-prev-btn");
  const nextBtn = document.getElementById("page-next-btn");
  let searchTimer = null;
  const clearSearchInputHard = () => {
    if (!searchInput) return;
    searchInput.value = "";
    searchInput.defaultValue = "";
    searchInput.setAttribute("value", "");
    state.search = "";
  };
  if (searchInput) {
    clearSearchInputHard();
    searchInput.setAttribute("readonly", "readonly");
    setTimeout(() => searchInput.removeAttribute("readonly"), 240);
    [0, 120, 400, 1000, 2200].forEach((delay) => {
      setTimeout(() => clearSearchInputHard(), delay);
    });
  }
  state.search = "";

  searchBtn?.addEventListener("click", () => {
    state.search = String(searchInput?.value || "").trim();
    state.page = 1;
    applyFiltersAndRender();
  });

  searchInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    state.search = String(searchInput.value || "").trim();
    state.page = 1;
    applyFiltersAndRender();
  });

  searchInput?.addEventListener("input", () => {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = String(searchInput.value || "").trim();
      state.page = 1;
      applyFiltersAndRender();
    }, 220);
  });

  sortSelect?.addEventListener("change", () => {
    state.sort = String(sortSelect.value || "updated_desc");
    state.page = 1;
    applyFiltersAndRender();
  });

  resetBtn?.addEventListener("click", () => {
    state.search = "";
    state.moduleKey = "all";
    state.tag = "";
    state.qualityTier = "all";
    state.sort = "updated_desc";
    state.timeWindow = "all";
    state.viewMode = "card";
    state.page = 1;
    if (searchInput) searchInput.value = "";
    if (sortSelect) sortSelect.value = "updated_desc";
    closeDetailDrawer();
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

  document.querySelectorAll("#module-tabs button[data-module-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.moduleKey = String(btn.dataset.moduleKey || "all");
      if (state.moduleKey !== "all" && state.moduleKey !== "sharing" && state.tag === MODULE.blogTag) {
        state.tag = "";
      }
      state.page = 1;
      applyFiltersAndRender();
    });
  });

  document.querySelectorAll("#time-tabs button[data-time]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.timeWindow = String(btn.dataset.time || "all");
      state.page = 1;
      applyFiltersAndRender();
    });
  });

  document.querySelectorAll("#quality-tabs button[data-quality]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.qualityTier = String(btn.dataset.quality || "usable_plus");
      state.page = 1;
      applyFiltersAndRender();
    });
  });

  document.querySelectorAll("#view-mode-tabs button[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.viewMode = String(btn.dataset.view || "card");
      applyFiltersAndRender();
    });
  });

  document.querySelectorAll(".main-nav a[data-nav-module-key]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      state.moduleKey = String(link.dataset.navModuleKey || "all");
      if (state.moduleKey !== "all" && state.moduleKey !== "sharing" && state.tag === MODULE.blogTag) {
        state.tag = "";
      }
      state.page = 1;
      applyFiltersAndRender();
    });
  });
}

function bindDetailDrawer() {
  const closeBtn = document.getElementById("detail-close-btn");
  const copyBtn = document.getElementById("detail-copy-btn");
  const openLink = document.getElementById("detail-open-link");

  closeBtn?.addEventListener("click", closeDetailDrawer);
  copyBtn?.addEventListener("click", async () => {
    const item = state.allItems.find((row) => row.id === state.activeItemId);
    if (!item || !isHttpUrl(item.url)) return;
    try {
      await navigator.clipboard.writeText(item.url);
      copyBtn.textContent = "已复制";
      setTimeout(() => {
        copyBtn.textContent = "复制链接";
      }, 900);
    } catch (_err) {
      copyBtn.textContent = "复制失败";
      setTimeout(() => {
        copyBtn.textContent = "复制链接";
      }, 900);
    }
  });

  openLink?.addEventListener("click", (event) => {
    if (openLink.classList.contains("is-disabled")) event.preventDefault();
  });
}

function openAuthorPanel(authorName) {
  const panel = document.getElementById("author-panel");
  const titleEl = document.getElementById("author-panel-title");
  const summaryEl = document.getElementById("author-panel-summary");
  const listEl = document.getElementById("author-panel-list");
  if (!panel || !titleEl || !summaryEl || !listEl) return;

  const name = String(authorName || "").trim();
  if (!name) return;
  const rows = sortItems(
    state.allItems.filter((item) => (getAuthorIdentity(item) || getAuthorDisplayName(item)) === name),
    "updated_desc"
  );
  const displayName = rows.length ? getAuthorDisplayName(rows[0]) : name;
  titleEl.textContent = `作者页：${displayName}`;
  summaryEl.textContent = `累计贡献 ${rows.length} 条，按最近更新时间排序。`;
  listEl.innerHTML = rows.length
    ? rows
        .slice(0, 30)
        .map((item) => `<div><span>${escapeHtml(item.title)}</span><button type="button" class="ghost-btn detail-btn" data-item-id="${escapeHtml(item.id)}">查看</button></div>`)
        .join("")
    : '<span class="empty-hint">暂无作者条目</span>';
  panel.hidden = false;
}

function closeAuthorPanel() {
  const panel = document.getElementById("author-panel");
  if (!panel) return;
  panel.hidden = true;
}

function bindOverviewInteractions() {
  const overview = document.getElementById("overview-home");
  const authorCloseBtn = document.getElementById("author-close-btn");
  const authorPanel = document.getElementById("author-panel");
  overview?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const manifestActionBtn = target.closest("[data-manifest-action]");
    if (manifestActionBtn) {
      const action = String(manifestActionBtn.getAttribute("data-manifest-action") || "").trim();
      const key = String(manifestActionBtn.getAttribute("data-manifest-key") || "").trim();
      if (!key) return;
      if (action === "generate") {
        renderModuleFactoryPreview(key);
        return;
      }
      if (action === "copy-json") {
        const template = getModuleTemplate(key);
        if (!template) return;
        const text = JSON.stringify(template, null, 2);
        try {
          await navigator.clipboard.writeText(text);
          window.alert(`已复制模板配置：${template.label}`);
        } catch (_err) {
          window.alert(text);
        }
        return;
      }
    }

    const manifestCopyBtn = target.closest("[data-manifest-key]");
    if (manifestCopyBtn) {
      const key = String(manifestCopyBtn.getAttribute("data-manifest-key") || "").trim();
      renderModuleFactoryPreview(key);
      return;
    }

    const hotTagBtn = target.closest("[data-hot-tag]");
    if (hotTagBtn) {
      state.tag = String(hotTagBtn.getAttribute("data-hot-tag") || "").trim();
      state.page = 1;
      applyFiltersAndRender();
      return;
    }

    const authorBtn = target.closest(".author-open-btn");
    if (authorBtn) {
      const name = String(authorBtn.getAttribute("data-author") || "").trim();
      openAuthorPanel(name);
      return;
    }

    const detailBtn = target.closest(".detail-btn");
    if (detailBtn) {
      const id = String(detailBtn.getAttribute("data-item-id") || "");
      const item = state.allItems.find((x) => x.id === id);
      if (item) await openDetailDrawer(item);
    }

    const generatedActionBtn = target.closest("[data-generated-action]");
    if (generatedActionBtn) {
      const action = String(generatedActionBtn.getAttribute("data-generated-action") || "").trim();
      const id = String(generatedActionBtn.getAttribute("data-generated-id") || "").trim();
      const module = state.generatedModules.find((x) => x.id === id);
      if (!module) return;
      if (action === "remove") {
        state.generatedModules = state.generatedModules.filter((x) => x.id !== id);
        saveModuleFactoryState();
        renderGeneratedModules();
        return;
      }
      const text = action === "copy-json" ? JSON.stringify(module, null, 2) : module.code || "";
      try {
        await navigator.clipboard.writeText(text);
        window.alert(action === "copy-json" ? `已复制配置：${module.label}` : `已复制代码：${module.label}`);
      } catch (_err) {
        window.alert(text);
      }
    }
  });

  authorCloseBtn?.addEventListener("click", closeAuthorPanel);
  authorPanel?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const detailBtn = target.closest(".detail-btn");
    if (!detailBtn) return;
    const id = String(detailBtn.getAttribute("data-item-id") || "");
    const item = state.allItems.find((x) => x.id === id);
    if (item) await openDetailDrawer(item);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeAuthorPanel();
  });
}

function bindBlogEditor() {
  const openTopBtn = document.getElementById("open-blog-editor");
  const openSideBtn = document.getElementById("open-blog-editor-side");
  const closeBtn = document.getElementById("blog-editor-close");
  const cancelBtn = document.getElementById("blog-cancel-btn");
  const submitBtn = document.getElementById("blog-submit-btn");
  const clearBtn = document.getElementById("blog-clear-btn");
  const templateBtn = document.getElementById("blog-template-btn");
  const avatarFileInput = document.getElementById("blog-author-avatar-file-input");
  const avatarHint = document.getElementById("blog-author-avatar-hint");
  const modal = document.getElementById("blog-editor-modal");

  openTopBtn?.addEventListener("click", openBlogEditor);
  openSideBtn?.addEventListener("click", openBlogEditor);
  closeBtn?.addEventListener("click", closeBlogEditor);
  cancelBtn?.addEventListener("click", closeBlogEditor);
  submitBtn?.addEventListener("click", submitBlogPost);
  clearBtn?.addEventListener("click", () => {
    clearBlogEditorForm();
    const levelInput = document.getElementById("blog-level-input");
    if (levelInput) levelInput.value = "usable";
    setBlogEditorTip("已清空，可重新填写。", false);
  });
  templateBtn?.addEventListener("click", () => {
    applyBlogTemplate();
    setBlogEditorTip("已套用开源分享模板。", false);
  });
  avatarFileInput?.addEventListener("change", () => {
    const file = avatarFileInput.files?.[0];
    if (!avatarHint) return;
    avatarHint.textContent = file ? `已选择头像：${file.name}` : "未选择头像（可选）";
  });

  modal?.addEventListener("click", (event) => {
    if (event.target === modal) closeBlogEditor();
  });

  // 兜底：即使事件绑定顺序异常，也可以通过按钮 id 关闭弹窗
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.id === "blog-editor-close" || target.id === "blog-cancel-btn") {
      closeBlogEditor();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (modal && !modal.hidden) closeBlogEditor();
  });
}

function setAssistantTip(message, isError = false) {
  const tip = document.getElementById("assistant-tip");
  if (!tip) return;
  const text = String(message || "").trim();
  if (!text) {
    tip.hidden = true;
    tip.textContent = "";
    tip.classList.remove("is-error", "is-success");
    return;
  }
  tip.hidden = false;
  tip.textContent = text;
  tip.classList.toggle("is-error", isError);
  tip.classList.toggle("is-success", !isError);
}

function setAssistantMode(mode) {
  const value =
    mode === ASSISTANT_MODE.openSource
      ? ASSISTANT_MODE.openSource
      : mode === ASSISTANT_MODE.similarCommunity
      ? ASSISTANT_MODE.similarCommunity
      : ASSISTANT_MODE.maintain;
  state.assistantMode = value;

  const maintainBtn = document.getElementById("assistant-tab-maintain");
  const openSourceBtn = document.getElementById("assistant-tab-open-source");
  const similarCommunityBtn = document.getElementById("assistant-tab-similar-community");
  const card = document.querySelector("#assistant-modal .assistant-card");
  maintainBtn?.classList.toggle("is-active", value === ASSISTANT_MODE.maintain);
  openSourceBtn?.classList.toggle("is-active", value === ASSISTANT_MODE.openSource);
  similarCommunityBtn?.classList.toggle("is-active", value === ASSISTANT_MODE.similarCommunity);
  if (card) {
    card.classList.remove("assistant-mode-maintain", "assistant-mode-open-source", "assistant-mode-similar-community");
    if (value === ASSISTANT_MODE.openSource) card.classList.add("assistant-mode-open-source");
    else if (value === ASSISTANT_MODE.similarCommunity) card.classList.add("assistant-mode-similar-community");
    else card.classList.add("assistant-mode-maintain");
  }

  const label = document.getElementById("assistant-goal-label");
  const input = document.getElementById("assistant-goal-input");
  const result = document.getElementById("assistant-result");
  const actionLog = document.getElementById("assistant-action-log");
  const contextNote = document.getElementById("assistant-context-note");
  const presetsRoot = document.getElementById("assistant-presets");
  if (value === ASSISTANT_MODE.openSource) {
    if (label) label.textContent = "建设目标";
    if (input) input.placeholder = "例如：建立可持续的开源社区生产机制，并把周报与巡检流程标准化";
    if (contextNote) contextNote.textContent = "适合生成治理方案、发布节奏和协作机制，也可直接自动执行少量安全动作。";
  } else if (value === ASSISTANT_MODE.similarCommunity) {
    if (label) label.textContent = "社区需求";
    if (input) input.placeholder = "例如：搭建一个教育科技方向社区，包含任务榜+论坛+开源分享，并自动注入启动条目";
    if (contextNote) contextNote.textContent = "适合快速搭建同类社区蓝图，帮助你把模块结构、角色和冷启动内容一次性理顺。";
  } else {
    if (label) label.textContent = "维护重点";
    if (input) input.placeholder = "例如：做一次本周巡检，并自动生成执行草稿给运营同学";
    if (contextNote) contextNote.textContent = "适合做周度巡检、质量修复和内容维护，输出能直接落地的待办。";
  }
  if (presetsRoot) {
    const presets = ASSISTANT_PRESETS[value] || ASSISTANT_PRESETS[ASSISTANT_MODE.maintain];
    presetsRoot.innerHTML = presets
      .map(
        (preset, idx) => `
          <button type="button" class="assistant-preset-btn" data-preset-mode="${escapeHtml(preset.mode)}" data-preset-goal="${escapeHtml(preset.goal)}">
            <span>${escapeHtml(preset.label)}</span>
            <small>快捷任务 ${idx + 1}</small>
          </button>
        `
      )
      .join("");
  }
  if (result) {
    result.hidden = true;
    result.textContent = "";
  }
  if (actionLog) {
    actionLog.hidden = true;
    actionLog.textContent = "";
  }
  setAssistantTip("", false);
}

function openAssistantPanel() {
  const modal = document.getElementById("assistant-modal");
  if (!modal) return;
  modal.hidden = false;
  setAssistantMode(state.assistantMode || ASSISTANT_MODE.maintain);
  const snapshot = getOverviewSnapshot();
  const totalEl = document.getElementById("assistant-total-items");
  const recentEl = document.getElementById("assistant-recent-7d");
  const healthEl = document.getElementById("assistant-health-score");
  if (totalEl) totalEl.textContent = String(snapshot.totalItems);
  if (recentEl) recentEl.textContent = String(snapshot.metrics.weekNew);
  if (healthEl) healthEl.textContent = String(snapshot.healthScore);
  setAssistantTip("", false);
}

function closeAssistantPanel() {
  const modal = document.getElementById("assistant-modal");
  if (!modal) return;
  modal.hidden = true;
  setAssistantTip("", false);
}

function renderAssistantActionLog(data) {
  const actionLogEl = document.getElementById("assistant-action-log");
  if (!actionLogEl) return;
  const executed = Array.isArray(data?.executed_actions) ? data.executed_actions : [];
  if (!executed.length) {
    actionLogEl.hidden = true;
    actionLogEl.textContent = "";
    return;
  }
  const lines = executed.map((row, idx) => {
    const id = String(row?.id || `action-${idx + 1}`);
    const name = String(row?.name || id);
    const status = String(row?.status || "unknown");
    const detail = String(row?.detail || "").trim();
    return `${idx + 1}. ${name} [${status}]${detail ? `\n   ${detail}` : ""}`;
  });
  actionLogEl.hidden = false;
  actionLogEl.textContent = `自动执行结果：\n${lines.join("\n")}`;
}

async function runAssistantTask() {
  const inputEl = document.getElementById("assistant-goal-input");
  const resultEl = document.getElementById("assistant-result");
  const actionLogEl = document.getElementById("assistant-action-log");
  const runBtn = document.getElementById("assistant-run-btn");
  const autoExecEl = document.getElementById("assistant-auto-exec");
  const budgetEl = document.getElementById("assistant-action-budget");
  const mode = state.assistantMode || ASSISTANT_MODE.maintain;
  const text = String(inputEl?.value || "").trim();
  const autoExec = Boolean(autoExecEl?.checked);
  const budget = Number.parseInt(String(budgetEl?.value || "2"), 10);
  const endpoint = "/api/assistant/agent-manage";
  const payload = {
    mode,
    goal:
      text ||
      (mode === ASSISTANT_MODE.openSource
        ? "请基于当前社区快照给出可执行建设方案。"
        : mode === ASSISTANT_MODE.similarCommunity
        ? "请生成一个结构与当前社区相似的开源协作社区方案。"
        : "请做一次本周社区巡检并给出优先级待办。"),
    execute_actions: autoExec,
    action_budget: Number.isFinite(budget) ? budget : 2,
    max_tokens: mode === ASSISTANT_MODE.similarCommunity ? 1300 : 1100,
    temperature: mode === ASSISTANT_MODE.maintain ? 0.15 : 0.2,
  };
  const oldText = runBtn?.textContent || "生成建议";

  if (runBtn) {
    runBtn.disabled = true;
    runBtn.textContent = "生成中...";
  }
  if (actionLogEl) {
    actionLogEl.hidden = true;
    actionLogEl.textContent = "";
  }
  setAssistantTip("正在生成，请稍候...", false);

  try {
    const data = await fetchJson(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: autoExec ? 90000 : 60000,
      retry: 1,
    });
    const markdown = String(data?.plan_markdown || "").trim();
    const source = String(data?.source || "unknown");
    const model = String(data?.model || "");
    const executed = Array.isArray(data?.executed_actions) ? data.executed_actions : [];
    const executedDone = executed.filter((x) => String(x?.status || "").toLowerCase() === "done").length;
    if (resultEl) {
      resultEl.hidden = false;
      resultEl.textContent = markdown || "未生成有效内容，请调整输入后重试。";
    }
    renderAssistantActionLog(data);
    setAssistantTip(
      autoExec
        ? `已生成并执行 ${executedDone}/${executed.length} 个动作（来源：${source}${model ? ` / 模型：${model}` : ""}）`
        : `已生成（来源：${source}${model ? ` / 模型：${model}` : ""}）`,
      false
    );
  } catch (err) {
    setAssistantTip(`生成失败：${formatGatewayError(err)}`, true);
  } finally {
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.textContent = oldText;
    }
  }
}

async function copyAssistantResult() {
  const resultEl = document.getElementById("assistant-result");
  const actionLogEl = document.getElementById("assistant-action-log");
  const text = [String(resultEl?.textContent || "").trim(), String(actionLogEl?.textContent || "").trim()].filter(Boolean).join("\n\n");
  if (!text) {
    setAssistantTip("当前没有可复制的内容。", true);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setAssistantTip("结果已复制到剪贴板。", false);
  } catch (_err) {
    setAssistantTip("复制失败，请稍后重试。", true);
  }
}

function bindAssistantPanel() {
  const openBtn = document.getElementById("open-assistant-panel");
  const heroOpenBtn = document.getElementById("hero-open-assistant");
  const heroFactoryBtn = document.getElementById("hero-open-module-factory");
  const closeBtn = document.getElementById("assistant-close-btn");
  const cancelBtn = document.getElementById("assistant-cancel-btn");
  const runBtn = document.getElementById("assistant-run-btn");
  const copyBtn = document.getElementById("assistant-copy-btn");
  const modal = document.getElementById("assistant-modal");

  openBtn?.addEventListener("click", openAssistantPanel);
  heroOpenBtn?.addEventListener("click", openAssistantPanel);
  heroFactoryBtn?.addEventListener("click", openModuleFactoryPanel);
  closeBtn?.addEventListener("click", closeAssistantPanel);
  cancelBtn?.addEventListener("click", closeAssistantPanel);
  runBtn?.addEventListener("click", runAssistantTask);
  copyBtn?.addEventListener("click", copyAssistantResult);

  document.querySelectorAll("[data-hero-module]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const moduleKey = String(btn.getAttribute("data-hero-module") || "all");
      state.moduleKey = moduleKey;
      state.page = 1;
      applyFiltersAndRender();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  document.querySelectorAll("[data-assistant-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = String(btn.getAttribute("data-assistant-mode") || ASSISTANT_MODE.maintain);
      setAssistantMode(mode);
    });
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const presetBtn = target.closest(".assistant-preset-btn");
    if (!presetBtn) return;
    const mode = String(presetBtn.getAttribute("data-preset-mode") || ASSISTANT_MODE.maintain);
    const goal = String(presetBtn.getAttribute("data-preset-goal") || "");
    setAssistantMode(mode);
    const input = document.getElementById("assistant-goal-input");
    if (input) input.value = goal;
    openAssistantPanel();
  });

  modal?.addEventListener("click", (event) => {
    if (event.target === modal) closeAssistantPanel();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (modal && !modal.hidden) closeAssistantPanel();
  });
}

function bindAuthPanel() {
  const openBtn = document.getElementById("open-login-modal");
  const closeBtn = document.getElementById("login-close-btn");
  const cancelBtn = document.getElementById("login-cancel-btn");
  const submitBtn = document.getElementById("login-submit-btn");
  const logoutBtn = document.getElementById("auth-logout-btn");
  const modal = document.getElementById("login-modal");
  const phoneTab = document.getElementById("auth-tab-phone");
  const emailTab = document.getElementById("auth-tab-email");
  const passwordSwitch = document.getElementById("auth-switch-password");
  const registerSwitch = document.getElementById("auth-switch-register");
  openBtn?.addEventListener("click", openLoginModal);
  closeBtn?.addEventListener("click", closeLoginModal);
  cancelBtn?.addEventListener("click", closeLoginModal);
  submitBtn?.addEventListener("click", submitLogin);
  logoutBtn?.addEventListener("click", logout);
  phoneTab?.addEventListener("click", () => setAuthChannel("phone"));
  emailTab?.addEventListener("click", () => setAuthChannel("email"));
  passwordSwitch?.addEventListener("click", () => setAuthMode("password"));
  registerSwitch?.addEventListener("click", () => setAuthMode("register"));
  rebuildPasswordInput();
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) closeLoginModal();
  });
}

function bindAdminPanel() {
  const openBtn = document.getElementById("open-admin-modal");
  const closeBtn = document.getElementById("admin-close-btn");
  const saveBtn = document.getElementById("moderation-save-btn");
  const createUserBtn = document.getElementById("create-user-btn");
  const modal = document.getElementById("admin-modal");
  openBtn?.addEventListener("click", openAdminModal);
  closeBtn?.addEventListener("click", closeAdminModal);
  saveBtn?.addEventListener("click", saveModerationSetting);
  createUserBtn?.addEventListener("click", createMemberUser);
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) closeAdminModal();
  });
}

async function validateAuthState() {
  if (!state.auth?.token) return;
  try {
    const data = await fetchJson("/api/auth/me", { retry: 0, timeoutMs: 12000 });
    if (data?.user && typeof data.user === "object") {
      state.auth.user = data.user;
      saveAuthState();
      return;
    }
    clearAuthState();
  } catch (_err) {
    clearAuthState();
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  loadAuthState();
  await validateAuthState();
  renderAuthUI();
  bindAuthPanel();
  bindAdminPanel();
  bindFilters();
  bindListActions();
  bindOverviewInteractions();
  bindDetailDrawer();
  bindBlogEditor();
  bindAssistantPanel();
  await loadAllData();
});

window.addEventListener("pageshow", () => {
  const searchInput = document.getElementById("global-search-input");
  if (searchInput) {
    searchInput.value = "";
    searchInput.defaultValue = "";
    searchInput.setAttribute("value", "");
  }
  state.search = "";
  applyFiltersAndRender();
});
