import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode, quote_plus, urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="resource-service", version="0.3.0")
logger = logging.getLogger("resource-service")

RESOURCE_FILE = Path(os.getenv("RESOURCE_FILE", "/app/resources/catalog.json"))
RESOURCE_DB_FILE = Path(os.getenv("RESOURCE_DB_FILE", "/app/data/community.db"))
BLOG_AVATAR_DIR = Path(os.getenv("BLOG_AVATAR_DIR", "/app/data/blog_avatars"))
COMMUNITY_SERVICE_URL = os.getenv("COMMUNITY_SERVICE_URL", "http://community-service:8001").rstrip("/")
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm-service:8003").rstrip("/")
ARXIV_API_URL = os.getenv("ARXIV_API_URL", "https://export.arxiv.org/api/query").rstrip("/")
ARXIV_DEFAULT_QUERY = os.getenv(
    "ARXIV_DEFAULT_QUERY",
    "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:cs.RO OR cat:stat.ML",
).strip()
ARXIV_USER_AGENT = os.getenv("ARXIV_USER_AGENT", "openkgfield-community/0.3").strip() or "openkgfield-community/0.3"
ARXIV_AUTO_SYNC_ENABLED = os.getenv("ARXIV_AUTO_SYNC_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
ARXIV_AUTO_SYNC_INTERVAL_HOURS = max(1, int(os.getenv("ARXIV_AUTO_SYNC_INTERVAL_HOURS", "24")))
ARXIV_AUTO_SYNC_INITIAL_DELAY_SECONDS = max(5, int(os.getenv("ARXIV_AUTO_SYNC_INITIAL_DELAY_SECONDS", "60")))
ARXIV_AUTO_SYNC_RETRY_SECONDS = max(300, int(os.getenv("ARXIV_AUTO_SYNC_RETRY_SECONDS", "3600")))
ARXIV_AUTO_SYNC_MAX_RESULTS = max(1, min(50, int(os.getenv("ARXIV_AUTO_SYNC_MAX_RESULTS", "12"))))
ARXIV_AUTO_SYNC_QUERY = os.getenv("ARXIV_AUTO_SYNC_QUERY", ARXIV_DEFAULT_QUERY).strip() or ARXIV_DEFAULT_QUERY
ARXIV_AUTO_SYNC_DAILY_AT = os.getenv("ARXIV_AUTO_SYNC_DAILY_AT", "03:30").strip() or "03:30"
ARXIV_AUTO_SYNC_USE_LLM_TRANSLATION = os.getenv("ARXIV_AUTO_SYNC_USE_LLM_TRANSLATION", "true").strip().lower() in {"1", "true", "yes", "on"}
SHANGHAI_TZ = timezone(timedelta(hours=8))
_ARXIV_SYNC_LOCK = threading.Lock()
_ARXIV_SYNC_THREAD_STARTED = False

ALLOWED_MODULES = {"文献任务榜", "AI前沿", "开源分享", "主题论坛", "团队模块"}
MODULE_ALIASES = {
    "文献任务榜": "文献任务榜",
    "AI前沿": "AI前沿",
    "开源分享": "开源分享",
    "主题论坛": "主题论坛",
    "团队模块": "团队模块",
    "team": "团队模块",
    "literature_taskboard": "文献任务榜",
    "ai_frontier": "AI前沿",
    "open_source_sharing": "开源分享",
    "topic_forum": "主题论坛",
}
BLOG_ALLOWED_STATUSES = {"draft", "published"}

NIUKE_SITE_URL = "https://niuke.pages.dev/"
NIUKE_SITE_ITEMS: list[dict[str, str]] = [
    {"title": "团队项目与里程碑", "url": f"{NIUKE_SITE_URL}#projects", "module": "团队模块", "summary": "团队模块入口，用于沉淀项目、成果和协作说明。", "source": "niuke_site"},
    {"title": "研究方向与前沿观察", "url": f"{NIUKE_SITE_URL}#research", "module": "AI前沿", "summary": "用于记录前沿论文、项目和研究趋势。", "source": "niuke_site"},
    {"title": "项目成果与周报", "url": f"{NIUKE_SITE_URL}#results", "module": "开源分享", "summary": "用于沉淀阶段性成果、分享和经验总结。", "source": "niuke_site"},
    {"title": "活动与讨论", "url": f"{NIUKE_SITE_URL}#activities", "module": "主题论坛", "summary": "用于承接活动、讨论与协作话题。", "source": "niuke_site"},
]


class _BlockTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._ignore = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignore = True
            return
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "section", "article", "div", "br"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignore = False
            return
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "section"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignore and data:
            self._chunks.append(data)

    def lines(self) -> list[str]:
        out: list[str] = []
        for line in "".join(self._chunks).splitlines():
            text = re.sub(r"\s+", " ", line).strip()
            if text:
                out.append(text)
        return out


class CommunityItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    url: str = Field(..., min_length=1, max_length=2000)
    module: str = Field(..., min_length=1, max_length=64)
    summary: str = Field(default="", max_length=2000)
    source: str = Field(default="manager", max_length=128)


class CommunityItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    module: str | None = Field(default=None, min_length=1, max_length=64)
    summary: str | None = Field(default=None, max_length=2000)


class CommunityItemBulkImportRequest(BaseModel):
    items: list[CommunityItemCreate] = Field(default_factory=list, max_length=500)
    replace_existing: bool = False


class PresetImportRequest(BaseModel):
    replace_existing: bool = False
    scrape: bool = True
    timeout_seconds: int = Field(default=12, ge=3, le=60)


class ArxivImportRequest(BaseModel):
    query: str | None = Field(default=None, max_length=500)
    max_results: int = Field(default=12, ge=1, le=50)
    replace_existing: bool = False
    timeout_seconds: int = Field(default=20, ge=5, le=60)
    use_llm_translation: bool = True


class ForumImportRequest(BaseModel):
    org: str = Field(default="openKG-field", min_length=1, max_length=128)
    per_page: int = Field(default=30, ge=1, le=100)
    replace_existing: bool = False


class CommunityModuleInstallRequest(BaseModel):
    template_key: str = Field(..., min_length=1, max_length=64)
    alias: str | None = Field(default=None, max_length=128)
    replace_existing: bool = True


class CommunityModuleImportRequest(BaseModel):
    packages: list[dict] = Field(default_factory=list, max_length=200)
    replace_existing: bool = True


class BlogPostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    author: str = Field(default="community-user", max_length=128)
    author_avatar_url: str | None = Field(default=None, max_length=2000)
    summary: str = Field(default="", max_length=2000)
    content_markdown: str = Field(..., min_length=1, max_length=100000)
    share_url: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    status: str = Field(default="published", max_length=32)


class BlogPostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    author: str | None = Field(default=None, max_length=128)
    author_avatar_url: str | None = Field(default=None, max_length=2000)
    summary: str | None = Field(default=None, max_length=2000)
    content_markdown: str | None = Field(default=None, min_length=1, max_length=100000)
    share_url: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, max_length=32)


class BlogAvatarUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=256)
    content_type: str = Field(..., min_length=1, max_length=128)
    data_base64: str = Field(..., min_length=20, max_length=8_000_000)


class AuthUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: str = Field(..., min_length=1, max_length=64)
    role: str = Field(default="member", max_length=16)


class AuthUserVerify(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class AuthPhoneRegister(BaseModel):
    phone: str = Field(..., min_length=11, max_length=16)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: str = Field(..., min_length=1, max_length=64)


class AuthPhoneVerify(BaseModel):
    phone: str = Field(..., min_length=11, max_length=16)
    password: str = Field(..., min_length=1, max_length=128)


class AuthEmailRegister(BaseModel):
    email: str = Field(..., min_length=5, max_length=128)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: str = Field(..., min_length=1, max_length=64)


class AuthEmailVerify(BaseModel):
    email: str = Field(..., min_length=5, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)


class AuthSetPasswordByEmail(BaseModel):
    email: str = Field(..., min_length=5, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


def _default_catalog() -> dict:
    return {
        "platforms": [],
        "datasets": [],
        "tasks": [],
        "literature_taskboard": [],
        "ai_frontier": [],
        "open_source_sharing": [],
        "topic_forum": [],
        "pdf_research_highlights": [],
        "reading_docs": [],
        "knowledge_entries": [],
        "paper_project_dataset_links": [],
    }


def load_catalog() -> dict:
    if RESOURCE_FILE.exists():
        with RESOURCE_FILE.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    return _default_catalog()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _safe_http_get(url: str, *, timeout: int = 20, headers: dict[str, str] | None = None) -> bytes:
    req = urlrequest.Request(url=url, headers=headers or {}, method="GET")
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urlerror.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=exc.read().decode("utf-8", errors="ignore") or str(exc))
    except urlerror.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc.reason}")


def _safe_http_json(
    url: str,
    *,
    method: str = "GET",
    timeout: int = 20,
    headers: dict[str, str] | None = None,
    query: dict[str, str | int] | None = None,
    payload: dict | None = None,
) -> dict:
    if query:
        url = f"{url}?{urlencode(query)}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    merged_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urlrequest.Request(url=url, data=body, headers=merged_headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urlerror.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=exc.code, detail=text or str(exc))
    except urlerror.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc.reason}")


def _validate_module(module: str) -> str:
    name = module.strip()
    normalized = MODULE_ALIASES.get(name)
    if normalized not in ALLOWED_MODULES:
        raise HTTPException(status_code=400, detail=f"Invalid module: {module}")
    return normalized


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", str(value or "").strip())
    name = re.sub(r"-{2,}", "-", name).strip("-.")
    return name or "module"


def _normalize_item(*, title: str, url: str, module: str, summary: str, source: str) -> dict[str, str]:
    normalized = {
        "title": title.strip(),
        "url": url.strip(),
        "module": _validate_module(module),
        "summary": summary.strip(),
        "source": source.strip() or "manager",
    }
    if not normalized["title"]:
        raise HTTPException(status_code=400, detail="title is required")
    if not _valid_url(normalized["url"]):
        raise HTTPException(status_code=400, detail="url must be a valid http/https URL")
    return normalized


def _get_conn() -> sqlite3.Connection:
    RESOURCE_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(RESOURCE_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS community_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                module TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manager',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(title, url, module)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS community_modules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                default_grouping TEXT NOT NULL DEFAULT 'module',
                description TEXT NOT NULL DEFAULT '',
                package_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blog_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT 'community-user',
                author_avatar_url TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                content_markdown TEXT NOT NULL,
                share_url TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'published',
                source TEXT NOT NULL DEFAULT 'blog_editor',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL DEFAULT '' UNIQUE,
                email TEXT NOT NULL DEFAULT '' UNIQUE,
                password_hash TEXT NOT NULL,
                nickname TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


def _insert_item(conn: sqlite3.Connection, *, title: str, url: str, module: str, summary: str, source: str, replace_existing: bool) -> str:
    now = _utc_now()
    if replace_existing:
        existing = conn.execute(
            "SELECT id FROM community_items WHERE title = ? AND module = ? ORDER BY id DESC LIMIT 1",
            (title, module),
        ).fetchone()
        if existing is not None:
            conn.execute(
                "UPDATE community_items SET url = ?, summary = ?, source = ?, updated_at = ? WHERE id = ?",
                (url, summary, source, now, int(existing["id"])),
            )
            return "upserted"
    try:
        conn.execute(
            """
            INSERT INTO community_items (title, url, module, summary, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (title, url, module, summary, source, now, now),
        )
        return "created"
    except sqlite3.IntegrityError:
        return "skipped"


def _bulk_insert(items: list[dict[str, str]], replace_existing: bool) -> dict:
    created = skipped = upserted = 0
    with _get_conn() as conn:
        for item in items:
            status = _insert_item(conn, replace_existing=replace_existing, **item)
            if status == "created":
                created += 1
            elif status == "upserted":
                upserted += 1
            else:
                skipped += 1
        conn.commit()
    return {"created": created, "skipped": skipped, "upserted": upserted}


def _item_identity_key(item: dict[str, str]) -> tuple[str, str, str]:
    title = re.sub(r"\s+", " ", str(item.get("title") or "").strip()).lower()
    url = re.sub(r"\s+", " ", str(item.get("url") or "").strip()).lower()
    module = re.sub(r"\s+", " ", str(item.get("module") or "").strip()).lower()
    return title, url, module


def _bulk_insert_by_identity(items: list[dict[str, str]], replace_existing: bool) -> dict:
    created = skipped = upserted = 0
    with _get_conn() as conn:
        for item in items:
            _title, url, _module = _item_identity_key(item)
            source = item.get("source", "manager")
            summary = item.get("summary", "")
            now = _utc_now()
            existing = conn.execute(
                "SELECT id FROM community_items WHERE lower(trim(url)) = ? ORDER BY id DESC LIMIT 1",
                (url,),
            ).fetchone()
            if existing is not None:
                if replace_existing:
                    conn.execute(
                        "UPDATE community_items SET title = ?, url = ?, module = ?, summary = ?, source = ?, updated_at = ? WHERE id = ?",
                        (item["title"], item["url"], item["module"], summary, source, now, int(existing["id"])),
                    )
                    upserted += 1
                else:
                    skipped += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO community_items (title, url, module, summary, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (item["title"], item["url"], item["module"], summary, source, now, now),
                )
                created += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()
    return {"created": created, "skipped": skipped, "upserted": upserted}


def _query_community_items(module_name: str | None = None) -> list[dict]:
    sql = "SELECT id, title, url, module, summary, source, updated_at FROM community_items"
    params: list[object] = []
    if module_name:
        sql += " WHERE module = ?"
        params.append(module_name)
    sql += " ORDER BY module, updated_at DESC, id DESC"
    with _get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _normalize_blog_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags[:30]:
        text = re.sub(r"\s+", " ", str(raw or "").strip())[:32]
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalize_share_url(url: str | None) -> str:
    value = str(url or "").strip()
    return value if value and _valid_url(value) else ""


def _normalize_author_avatar_url(url: str | None) -> str:
    value = str(url or "").strip()
    return value if value and _valid_url(value) else ""


def _normalize_blog_status(status: str | None, *, allow_all: bool = False) -> str:
    value = str(status or "").strip().lower()
    if allow_all and not value:
        return "all"
    return value if value in BLOG_ALLOWED_STATUSES else "published"


def _password_hash(raw: str) -> str:
    salt = b"metalab-open-community"
    return hashlib.sha256(salt + raw.encode("utf-8")).hexdigest()


def _normalize_user_role(role: str | None) -> str:
    value = str(role or "member").strip().lower()
    return "admin" if value == "admin" else "member"


def _normalize_phone(phone: str | None) -> str:
    value = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(value) != 11 or not value.startswith("1"):
        raise HTTPException(status_code=400, detail="invalid phone")
    return value


def _normalize_email(email: str | None) -> str:
    value = str(email or "").strip().lower()
    if "@" not in value or "." not in value.split("@")[-1]:
        raise HTTPException(status_code=400, detail="invalid email")
    return value


def _placeholder_email_for_phone(phone: str) -> str:
    return f"{phone}@placeholder.local"


def _placeholder_phone_for_email(email: str) -> str:
    cleaned = re.sub(r"[^0-9]", "", email)
    return (cleaned[:11] or "10000000000").ljust(11, "0")


def _placeholder_phone_for_text(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return "1" + "".join(ch for ch in digest if ch.isdigit())[:10].ljust(10, "0")


def _placeholder_email_for_text(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^A-Za-z0-9]+", "", text.lower())[:16] or "user"
    return f"{slug}.{digest}@placeholder.local"


def _summary_from_markdown(summary: str, content_markdown: str, max_chars: int = 240) -> str:
    text = str(summary or "").strip() or re.sub(r"\s+", " ", str(content_markdown or "").strip())
    return text[:max_chars]


def _strip_html(text: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _normalize_arxiv_id(raw_id: str) -> str:
    value = str(raw_id or "").strip()
    value = value.rsplit("/", 1)[-1]
    value = value.replace("abs/", "").replace("pdf/", "")
    value = value.replace(".pdf", "")
    return value


def _arxiv_abs_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/abs/{_normalize_arxiv_id(arxiv_id)}"


def _arxiv_pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{_normalize_arxiv_id(arxiv_id)}.pdf"


def _chinese_char_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", str(text or "")))


_ALLOWED_LATIN_TOKENS = (
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
    "K3s",
    "Kubernetes",
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
)


def _strip_allowed_latin_terms(text: str) -> str:
    value = str(text or "")
    for token in _ALLOWED_LATIN_TOKENS:
        value = re.sub(rf"\b{re.escape(token)}\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"cs\.[A-Z]{2,3}", " ", value, flags=re.IGNORECASE)
    return value


def _latin_word_count(text: str) -> int:
    words = re.findall(r"[A-Za-z][A-Za-z0-9+\-']*", _strip_allowed_latin_terms(text))
    allowed = {"AI", "arXiv", "GPT", "LLM", "LLMs", "MIMO", "XL-RIS", "ViT", "ViTs", "CLIP", "SOTA"}
    return sum(1 for word in words if word not in allowed and len(word) > 3)


def _translation_looks_clean(text: str, *, kind: str = "标题") -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _chinese_char_count(value) == 0:
        return False
    if _latin_word_count(value) > 1:
        return False
    if kind == "标题" and _chinese_char_count(value) < 2:
        return False
    if kind == "标题" and len(value) > 120:
        return False
    return True


def _normalize_translation_output(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = value.strip().strip('"').strip("'").strip("“").strip("”").strip("‘").strip("’").strip()
    value = re.sub(r"^\s*(中文标题|中文摘要|译文|翻译结果|标题|摘要)\s*[:：]\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _translate_with_llm(text: str, *, kind: str = "标题", timeout_seconds: int = 25) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    system_prompt = (
        "你是论文标题和摘要翻译助手。"
        "你的任务是把输入完整翻译成中文。"
        "必须只输出最终中文结果，禁止输出英文原文、双语对照、项目符号、编号、引号或解释。"
        "如果遇到专有名词，优先采用中文学术常用译法；如果没有通用译法，采用自然意译。"
    )
    user_prompts = [
        f"请将下面的{kind}完整翻译成中文，只输出译文，不要保留英文原句，也不要加解释。\n{value}",
        f"请重新翻译下面的{kind}。要求：1. 只输出中文；2. 不要保留任何英文词组或整句原文；3. 不要双语并列；4. 不要解释。\n{value}",
    ]
    for user_prompt in user_prompts:
        try:
            response = _safe_http_json(
                f"{LLM_SERVICE_URL}/chat",
                method="POST",
                timeout=timeout_seconds,
                payload={
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 384 if kind == "标题" else 640,
                },
            )
            content = ""
            if isinstance(response, dict):
                choices = response.get("choices", [])
                if choices and isinstance(choices, list):
                    content = str(choices[0].get("message", {}).get("content", "") or "").strip()
            content = _normalize_translation_output(content)
            if _translation_looks_clean(content, kind=kind):
                return content[:600]
        except HTTPException:
            continue
    return ""


def _fallback_title_translation(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    replacements = [
        (r"\bCASCADE:\s*Case-Based Continual Adaptation for Large Language Models During Deployment\b", "CASCADE：面向部署阶段的大语言模型案例式持续适应"),
        (r"\bHidden Coalitions in Multi-Agent AI:\s*A Spectral Diagnostic from Internal Representations\b", "多智能体 AI 中的隐性联盟：基于内部表征的谱诊断"),
        (r"\bState Representation and Termination for Recursive Reasoning Systems\b", "递归推理系统的状态表征与终止机制"),
        (r"\bRobustness of Refugee-Matching Gains to Off-Policy Evaluation Choices\b", "难民匹配收益对离策略评估选择的鲁棒性"),
        (r"\bAn audio-to-analysis pipeline with certified transcription for information-theoretic\b", "具备认证转写的音频到分析流水线：面向信息论研究"),
        (r"\bFrom Canopy to Collision:\s*A Hybrid Predictive Framework for Identifying Risk Factors\b", "从林冠到碰撞：识别风险因素的混合预测框架"),
        (r"\bTeopitz MLP Mixers\b", "Toeplitz MLP 混合器"),
        (r"\bTeoplitz MLP Mixers\b", "Toeplitz MLP 混合器"),
        (r"\bToeplitz MLP Mixers\b", "Toeplitz MLP 混合器"),
        (r"\bAgentic Coding Needs Proactivity, Not Just Autonomy\b", "代理式编程需要主动性，而不仅是自主性"),
        (r"\bFrom Storage to Experience: A Survey on the Evolution of LLM Agent Memory\b", "从存储到体验：LLM Agent 记忆演进综述"),
        (r"\bEdge Deep Learning in Computer Vision and Medical Diagnostics\b", "计算机视觉与医疗诊断中的边缘深度学习"),
        (r"\bIndustrialization of Cyber Offense\b", "网络攻击的工业化"),
        (r"\bTUANDROMD-X: Advanced Entropy and Visual Analytics Dataset for Enhanced Malware Detection\b", "TUANDROMD-X：用于增强恶意软件检测的高级熵与可视分析数据集"),
        (r"\bNear-field Channel Estimation for XL-RIS-aided mmWave MIMO Systems\b", "XL-RIS辅助毫米波 MIMO 系统的近场信道估计"),
        (r"\bStreaming 3DGS worlds on the web\b", "在网页端流式渲染 3DGS 世界"),
        (r"\bA Survey on the Evolution of LLM Agent Memory\b", "LLM Agent 记忆演进综述"),
        (r"\bFrom Storage to Experience\b", "从存储到体验"),
    ]
    for pattern, replacement in replacements:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return replacement
    return ""


def _best_effort_translate(text: str, *, kind: str = "标题", use_llm: bool = True) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    translated = ""
    if re.search(r"[\u4e00-\u9fff]", value) and not re.search(r"[A-Za-z]{4,}", value):
        return value
    if use_llm:
        translated = _translate_with_llm(value, kind=kind)
        if translated and _translation_looks_clean(translated, kind=kind):
            return translated
    fallback = _fallback_title_translation(value)
    if fallback and _translation_looks_clean(fallback, kind=kind):
        return fallback
    return translated or fallback


def _strip_arxiv_original_suffix(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"（原题[:：].*?）\s*$", "", value)
    value = re.sub(r"\(原题[:：].*?\)\s*$", "", value)
    value = re.sub(r"（原文摘要[:：].*?）\s*$", "", value)
    value = re.sub(r"\(原文摘要[:：].*?\)\s*$", "", value)
    return value.strip()


def _row_to_blog_post(row: sqlite3.Row, include_content: bool = False) -> dict:
    item = {
        "id": int(row["id"]),
        "title": row["title"],
        "author": row["author"],
        "author_avatar_url": row["author_avatar_url"] or "",
        "summary": row["summary"] or "",
        "share_url": row["share_url"] or "",
        "tags": json.loads(row["tags_json"] or "[]"),
        "status": row["status"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_content:
        item["content_markdown"] = row["content_markdown"]
    return item


def _seed_from_catalog_if_empty() -> None:
    _seed_catalog_items(replace_existing=False)


def _seed_catalog_items(*, replace_existing: bool) -> dict:
    catalog = load_catalog()
    rows = []
    for section in ["literature_taskboard", "ai_frontier", "open_source_sharing", "topic_forum"]:
        for entry in catalog.get(section, []) or []:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or entry.get("topic") or "").strip()
            url = str(entry.get("github_url") or entry.get("reference_url") or entry.get("detail_url") or entry.get("issue_url") or entry.get("discussion_url") or "").strip()
            if not title or not url:
                continue
            try:
                rows.append(
                    _normalize_item(
                        title=title,
                        url=url,
                        module=MODULE_ALIASES[section],
                        summary=str(entry.get("paper_note") or entry.get("summary") or entry.get("goal") or entry.get("description") or "").strip(),
                        source="catalog_seed",
                    )
                )
            except HTTPException:
                continue
    if rows:
        return _bulk_insert(rows, replace_existing=replace_existing)
    return {"created": 0, "skipped": 0, "upserted": 0}


def _parse_arxiv_feed(feed_xml: bytes) -> list[dict]:
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid arXiv feed: {exc}")
    items: list[dict] = []
    for entry in root.findall("atom:entry", ns):
        title = _strip_html(entry.findtext("atom:title", default="", namespaces=ns))
        summary = _strip_html(entry.findtext("atom:summary", default="", namespaces=ns))
        arxiv_id = _normalize_arxiv_id(entry.findtext("atom:id", default="", namespaces=ns))
        published = entry.findtext("atom:published", default="", namespaces=ns) or ""
        updated = entry.findtext("atom:updated", default="", namespaces=ns) or ""
        authors = [author.findtext("atom:name", default="", namespaces=ns) for author in entry.findall("atom:author", ns)]
        primary_category = entry.find("arxiv:primary_category", ns)
        category = str(primary_category.get("term", "")).strip() if primary_category is not None else ""
        if not title or not arxiv_id:
            continue
        tags = [tag.get("term", "").strip() for tag in entry.findall("atom:category", ns) if tag.get("term")]
        items.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "summary": summary,
                "published": published,
                "updated": updated,
                "authors": [author for author in authors if author],
                "category": category,
                "tags": [tag for tag in tags if tag],
                "abs_url": _arxiv_abs_url(arxiv_id),
                "pdf_url": _arxiv_pdf_url(arxiv_id),
            }
        )
    return items


def _arxiv_item_to_community(arxiv_item: dict, *, use_llm_translation: bool = True) -> dict:
    original_title = str(arxiv_item.get("title") or "").strip()
    original_summary = str(arxiv_item.get("summary") or "").strip()
    translated_title = _strip_arxiv_original_suffix(
        _best_effort_translate(original_title, kind="标题", use_llm=use_llm_translation) or original_title
    )
    translated_summary = _strip_arxiv_original_suffix(
        _best_effort_translate(original_summary, kind="摘要", use_llm=use_llm_translation) or original_summary
    )
    authors = arxiv_item.get("authors") or []
    author_text = "，".join(authors[:4])
    title = translated_title if _translation_looks_clean(translated_title, kind="标题") else original_title
    title = _strip_arxiv_original_suffix(title)
    summary_parts = []
    if translated_summary:
        summary_parts.append(translated_summary)
    if author_text:
        summary_parts.append(f"作者：{author_text}")
    if arxiv_item.get("category"):
        summary_parts.append(f"分类：{arxiv_item['category']}")
    summary_parts.append(f"arXiv 号：{arxiv_item.get('arxiv_id', '')}")
    return _normalize_item(
        title=title,
        url=str(arxiv_item.get("abs_url") or "").strip(),
        module="AI前沿",
        summary=" | ".join(part for part in summary_parts if part),
        source="arxivorg",
    )


def _fetch_arxiv_items(query: str, *, max_results: int, timeout_seconds: int) -> list[dict]:
    safe_query = query.strip() or ARXIV_DEFAULT_QUERY
    url = (
        f"{ARXIV_API_URL}?search_query={quote_plus(safe_query)}"
        f"&start=0&max_results={int(max_results)}&sortBy=submittedDate&sortOrder=descending"
    )
    raw = _safe_http_get(url, timeout=timeout_seconds, headers={"User-Agent": ARXIV_USER_AGENT, "Accept": "application/atom+xml"})
    return _parse_arxiv_feed(raw)


def _sync_arxiv_items(*, query: str, max_results: int, replace_existing: bool, timeout_seconds: int, use_llm_translation: bool) -> dict:
    entries = _fetch_arxiv_items(query, max_results=max_results, timeout_seconds=timeout_seconds)
    items = [_arxiv_item_to_community(entry, use_llm_translation=use_llm_translation) for entry in entries]
    result = _bulk_insert_by_identity(items, replace_existing=replace_existing)
    return {
        "query": query or ARXIV_DEFAULT_QUERY,
        "fetched": len(entries),
        **result,
    }


def _get_sync_state(conn: sqlite3.Connection, name: str) -> dict[str, str]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            name TEXT PRIMARY KEY,
            last_success_at TEXT NOT NULL DEFAULT '',
            last_attempt_at TEXT NOT NULL DEFAULT '',
            last_status TEXT NOT NULL DEFAULT '',
            last_detail TEXT NOT NULL DEFAULT ''
        )
        """
    )
    row = conn.execute(
        "SELECT name, last_success_at, last_attempt_at, last_status, last_detail FROM sync_state WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        conn.execute("INSERT INTO sync_state (name) VALUES (?)", (name,))
        conn.commit()
        row = conn.execute(
            "SELECT name, last_success_at, last_attempt_at, last_status, last_detail FROM sync_state WHERE name = ?",
            (name,),
        ).fetchone()
    return dict(row)


def _set_sync_state(
    conn: sqlite3.Connection,
    name: str,
    *,
    status: str,
    detail: str = "",
    success_at: str | None = None,
) -> None:
    now = _utc_now()
    if success_at is None:
        conn.execute(
            """
            UPDATE sync_state
            SET last_attempt_at = ?, last_status = ?, last_detail = ?
            WHERE name = ?
            """,
            (now, status, detail[:1000], name),
        )
    else:
        conn.execute(
            """
            UPDATE sync_state
            SET last_attempt_at = ?, last_success_at = ?, last_status = ?, last_detail = ?
            WHERE name = ?
            """,
            (now, success_at, status, detail[:1000], name),
    )
    conn.commit()


def _parse_daily_time(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return 3, 30
    hour = max(0, min(23, int(match.group(1))))
    minute = max(0, min(59, int(match.group(2))))
    return hour, minute


def _next_daily_run(now: datetime, daily_at: str) -> datetime:
    hour, minute = _parse_daily_time(daily_at)
    candidate = now.astimezone(SHANGHAI_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now.astimezone(SHANGHAI_TZ):
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _run_arxiv_auto_sync_once() -> dict:
    with _ARXIV_SYNC_LOCK:
        with _get_conn() as conn:
            _get_sync_state(conn, "arxiv_auto_sync")
            try:
                result = _sync_arxiv_items(
                    query=ARXIV_AUTO_SYNC_QUERY,
                    max_results=ARXIV_AUTO_SYNC_MAX_RESULTS,
                    replace_existing=True,
                    timeout_seconds=30,
                    use_llm_translation=ARXIV_AUTO_SYNC_USE_LLM_TRANSLATION,
                )
                _set_sync_state(
                    conn,
                    "arxiv_auto_sync",
                    status="success",
                    success_at=_utc_now(),
                    detail=json.dumps(result, ensure_ascii=False),
                )
                return result
            except HTTPException as exc:
                detail = str(exc.detail)
                _set_sync_state(conn, "arxiv_auto_sync", status="failed", detail=detail)
                raise


def _arxiv_auto_sync_loop() -> None:
    time.sleep(ARXIV_AUTO_SYNC_INITIAL_DELAY_SECONDS)
    while True:
        try:
            _run_arxiv_auto_sync_once()
            next_run = _next_daily_run(datetime.now(timezone.utc), ARXIV_AUTO_SYNC_DAILY_AT)
            sleep_seconds = max(60, int((next_run - datetime.now(timezone.utc)).total_seconds()))
            time.sleep(sleep_seconds)
        except Exception as exc:
            logger.warning("arXiv auto sync failed: %s", exc)
            time.sleep(ARXIV_AUTO_SYNC_RETRY_SECONDS)


def _community_items_modules_summary() -> dict:
    items = _query_community_items()
    by_module: dict[str, int] = {}
    for item in items:
        by_module[item["module"]] = by_module.get(item["module"], 0) + 1
    return {"total": len(items), "by_module": by_module}


def _community_modules_manifest() -> dict:
    return {
        "version": "1.0",
        "modules": [
            {
                "key": "文献任务榜",
                "label": "文献任务榜",
                "source": "catalog.literature_taskboard",
                "default_grouping": "module",
                "description": "面向论文任务、数据集与基线整理的内容模块。",
            },
            {
                "key": "AI前沿",
                "label": "AI前沿",
                "source": "arXiv + catalog.ai_frontier",
                "default_grouping": "content_category",
                "description": "面向前沿论文、主题分类与中文摘要展示的内容模块。",
            },
            {
                "key": "开源分享",
                "label": "开源分享",
                "source": "catalog.open_source_sharing + blog_posts",
                "default_grouping": "content_category",
                "description": "面向社区分享、博客和项目成果的沉淀模块。",
            },
            {
                "key": "主题论坛",
                "label": "主题论坛",
                "source": "community-service forum_items",
                "default_grouping": "forum_category",
                "description": "面向 GitHub 仓库、议题与讨论串的分类聚合模块。",
            },
            {
                "key": "团队模块",
                "label": "团队模块",
                "source": "manual / extension",
                "default_grouping": "module",
                "description": "面向团队协作、角色和项目状态的扩展模块。",
            },
        ],
    }


def _find_module_template(template_key: str) -> dict | None:
    key = str(template_key or "").strip()
    if not key:
        return None
    for mod in _community_modules_manifest().get("modules", []):
        mod_key = str(mod.get("key") or mod.get("label") or "").strip()
        if mod_key == key:
            return dict(mod)
    return None


def _serialize_module_package(template: dict, *, alias: str | None = None) -> dict:
    label = str(alias or template.get("label") or template.get("key") or "module").strip()
    return {
        "template_key": str(template.get("key") or "").strip(),
        "label": label,
        "base_label": str(template.get("label") or "").strip(),
        "source": str(template.get("source") or "").strip(),
        "default_grouping": str(template.get("default_grouping") or "module").strip(),
        "description": str(template.get("description") or "").strip(),
        "install_mode": str(template.get("install_mode") or "one_click").strip(),
        "installed_at": _utc_now(),
    }


def _module_package_from_row(row: sqlite3.Row) -> dict:
    try:
        package = json.loads(row["package_json"] or "{}")
    except json.JSONDecodeError:
        package = {}
    if not isinstance(package, dict):
        package = {}
    if not package:
        package = {
            "template_key": row["template_key"],
            "label": row["label"],
            "base_label": row["label"],
            "source": row["source"],
            "default_grouping": row["default_grouping"],
            "description": row["description"],
            "install_mode": "one_click",
            "installed_at": row["updated_at"] or row["created_at"] or _utc_now(),
        }
    package.setdefault("template_key", row["template_key"])
    package.setdefault("label", row["label"])
    package.setdefault("base_label", row["label"])
    package.setdefault("source", row["source"])
    package.setdefault("default_grouping", row["default_grouping"])
    package.setdefault("description", row["description"])
    package.setdefault("install_mode", "one_click")
    package["exported_at"] = _utc_now()
    return package


def _coerce_module_package(raw: dict, *, template: dict | None = None, alias: str | None = None) -> dict:
    source_package = raw.get("package") if isinstance(raw.get("package"), dict) else raw
    template_key = str(
        source_package.get("template_key")
        or source_package.get("key")
        or (template.get("key") if template else "")
        or ""
    ).strip()
    label = str(
        alias
        or source_package.get("label")
        or source_package.get("base_label")
        or (template.get("label") if template else "")
        or template_key
        or "module"
    ).strip()
    base_label = str(
        source_package.get("base_label")
        or (template.get("label") if template else "")
        or source_package.get("label")
        or template_key
        or label
    ).strip()
    source = str(source_package.get("source") or (template.get("source") if template else "") or "").strip()
    default_grouping = str(source_package.get("default_grouping") or (template.get("default_grouping") if template else "module") or "module").strip()
    description = str(source_package.get("description") or (template.get("description") if template else "") or "").strip()
    install_mode = str(source_package.get("install_mode") or "one_click").strip()
    exported_at = str(source_package.get("exported_at") or "").strip()
    installed_at = str(source_package.get("installed_at") or exported_at or _utc_now()).strip()
    package = {
        "template_key": template_key,
        "label": label,
        "base_label": base_label,
        "source": source,
        "default_grouping": default_grouping,
        "description": description,
        "install_mode": install_mode,
        "installed_at": installed_at,
    }
    if exported_at:
        package["exported_at"] = exported_at
    return package


def _install_module_package(package: dict, *, replace_existing: bool = True) -> dict:
    now = _utc_now()
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM community_modules WHERE template_key = ? ORDER BY id DESC LIMIT 1",
            (package["template_key"],),
        ).fetchone()
        if existing is not None:
            if replace_existing:
                conn.execute(
                    """
                    UPDATE community_modules
                    SET label = ?, source = ?, default_grouping = ?, description = ?, package_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        package["label"],
                        package["source"],
                        package["default_grouping"],
                        package["description"],
                        json.dumps(package, ensure_ascii=False),
                        now,
                        int(existing["id"]),
                    ),
                )
                conn.commit()
                return {"status": "installed", "mode": "updated", "module": package}
            return {"status": "installed", "mode": "skipped", "module": package}

        conn.execute(
            """
            INSERT INTO community_modules (template_key, label, source, default_grouping, description, package_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                package["template_key"],
                package["label"],
                package["source"],
                package["default_grouping"],
                package["description"],
                json.dumps(package, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
    return {"status": "installed", "mode": "created", "module": package}


def _query_installed_modules() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, template_key, label, source, default_grouping, description, package_json, created_at, updated_at FROM community_modules ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        try:
            package = json.loads(row["package_json"] or "{}")
        except json.JSONDecodeError:
            package = {}
        out.append(
            {
                "id": int(row["id"]),
                "template_key": row["template_key"],
                "label": row["label"],
                "source": row["source"],
                "default_grouping": row["default_grouping"],
                "description": row["description"],
                "package": package,
                "code": json.dumps(package, ensure_ascii=False, indent=2),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return out


def _community_items_quality_report(stale_days: int = 30) -> dict:
    items = _query_community_items()
    invalid_url = 0
    stale = 0
    now = datetime.now(timezone.utc)
    for item in items:
        if not _valid_url(item.get("url", "")):
            invalid_url += 1
        updated_at = str(item.get("updated_at") or "").strip()
        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - dt > timedelta(days=stale_days):
            stale += 1
    return {"summary": {"invalid_url": invalid_url, "stale": stale}}


def _arxiv_sync_status() -> dict:
    with _get_conn() as conn:
        state = _get_sync_state(conn, "arxiv_auto_sync")
    return {
        "enabled": ARXIV_AUTO_SYNC_ENABLED,
        "query": ARXIV_AUTO_SYNC_QUERY,
        "max_results": ARXIV_AUTO_SYNC_MAX_RESULTS,
        "daily_at": ARXIV_AUTO_SYNC_DAILY_AT,
        "last_success_at": state.get("last_success_at", ""),
        "last_attempt_at": state.get("last_attempt_at", ""),
        "last_status": state.get("last_status", ""),
        "last_detail": state.get("last_detail", ""),
    }


@app.on_event("startup")
def on_startup() -> None:
    _ensure_db()
    _seed_from_catalog_if_empty()
    global _ARXIV_SYNC_THREAD_STARTED
    if ARXIV_AUTO_SYNC_ENABLED and not _ARXIV_SYNC_THREAD_STARTED:
        _ARXIV_SYNC_THREAD_STARTED = True
        thread = threading.Thread(target=_arxiv_auto_sync_loop, daemon=True, name="arxiv-auto-sync")
        thread.start()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "resource-service"}


@app.get("/community_items/arxiv_sync_status")
def community_items_arxiv_sync_status() -> dict:
    return _arxiv_sync_status()


@app.get("/catalog")
def catalog() -> dict:
    return load_catalog()


@app.get("/catalog/{section}")
def catalog_section(section: str) -> dict:
    catalog = load_catalog()
    return {section: catalog.get(section, [])}


@app.get("/community_items")
def community_items(module: str | None = None, limit: int = Query(default=500, ge=1, le=2000)) -> dict:
    items = _query_community_items(_validate_module(module) if module else None)
    return {"items": items[:limit]}


@app.post("/community_items")
def create_community_item(payload: CommunityItemCreate) -> dict:
    item = _normalize_item(title=payload.title, url=payload.url, module=payload.module, summary=payload.summary, source=payload.source)
    with _get_conn() as conn:
        status = _insert_item(conn, replace_existing=False, **item)
        conn.commit()
    return {"status": status, "item": item}


@app.patch("/community_items/{item_id}")
def update_community_item(item_id: int, payload: CommunityItemUpdate) -> dict:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM community_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="item not found")
        item = {
            "title": payload.title or row["title"],
            "url": payload.url or row["url"],
            "module": payload.module or row["module"],
            "summary": payload.summary if payload.summary is not None else row["summary"],
            "source": row["source"],
        }
        normalized = _normalize_item(**item)
        conn.execute(
            "UPDATE community_items SET title = ?, url = ?, module = ?, summary = ?, updated_at = ? WHERE id = ?",
            (normalized["title"], normalized["url"], normalized["module"], normalized["summary"], _utc_now(), item_id),
        )
        conn.commit()
    return {"status": "updated"}


@app.delete("/community_items/{item_id}")
def delete_community_item(item_id: int) -> dict:
    with _get_conn() as conn:
        conn.execute("DELETE FROM community_items WHERE id = ?", (item_id,))
        conn.commit()
    return {"status": "deleted"}


@app.get("/blog_posts")
def blog_posts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str = Query(default="published"),
    include_content: bool = Query(default=False),
) -> dict:
    status_norm = _normalize_blog_status(status, allow_all=True)
    sql = "SELECT * FROM blog_posts"
    params: list[object] = []
    if status_norm != "all":
        sql += " WHERE status = ?"
        params.append(status_norm)
    sql += " ORDER BY updated_at DESC, id DESC"
    offset = (page - 1) * page_size
    sql += " LIMIT ? OFFSET ?"
    params.extend([page_size, offset])
    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM blog_posts").fetchone()[0]
        items = [_row_to_blog_post(row, include_content=include_content) for row in rows]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@app.get("/blog_posts/{post_id}")
def blog_post_detail(post_id: int) -> dict:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM blog_posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="post not found")
        return _row_to_blog_post(row, include_content=True)


@app.post("/blog_posts")
def create_blog_post(payload: BlogPostCreate) -> dict:
    status = _normalize_blog_status(payload.status)
    now = _utc_now()
    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO blog_posts (title, author, author_avatar_url, summary, content_markdown, share_url, tags_json, status, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.title.strip(),
                payload.author.strip() or "community-user",
                _normalize_author_avatar_url(payload.author_avatar_url),
                _summary_from_markdown(payload.summary, payload.content_markdown),
                payload.content_markdown,
                _normalize_share_url(payload.share_url),
                json.dumps(_normalize_blog_tags(payload.tags), ensure_ascii=False),
                status,
                "blog_editor",
                now,
                now,
            ),
        )
        conn.commit()
        post_id = int(cursor.lastrowid)
    return {"id": post_id, "status": status}


@app.patch("/blog_posts/{post_id}")
def update_blog_post(post_id: int, payload: BlogPostUpdate) -> dict:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM blog_posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="post not found")
        updated = {
            "title": payload.title or row["title"],
            "author": payload.author or row["author"],
            "author_avatar_url": payload.author_avatar_url if payload.author_avatar_url is not None else row["author_avatar_url"],
            "summary": payload.summary if payload.summary is not None else row["summary"],
            "content_markdown": payload.content_markdown or row["content_markdown"],
            "share_url": payload.share_url if payload.share_url is not None else row["share_url"],
            "tags": payload.tags if payload.tags is not None else json.loads(row["tags_json"] or "[]"),
            "status": _normalize_blog_status(payload.status or row["status"]),
        }
        conn.execute(
            """
            UPDATE blog_posts
            SET title = ?, author = ?, author_avatar_url = ?, summary = ?, content_markdown = ?, share_url = ?, tags_json = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated["title"].strip(),
                updated["author"].strip() or "community-user",
                _normalize_author_avatar_url(updated["author_avatar_url"]),
                _summary_from_markdown(updated["summary"], updated["content_markdown"]),
                updated["content_markdown"],
                _normalize_share_url(updated["share_url"]),
                json.dumps(_normalize_blog_tags(updated["tags"]), ensure_ascii=False),
                updated["status"],
                _utc_now(),
                post_id,
            ),
        )
        conn.commit()
    return {"status": "updated"}


@app.post("/blog_avatars/upload")
def upload_blog_avatar(payload: BlogAvatarUploadRequest) -> dict:
    BLOG_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(payload.data_base64)
    ext = ".png"
    if "jpeg" in payload.content_type:
        ext = ".jpg"
    elif "webp" in payload.content_type:
        ext = ".webp"
    elif "gif" in payload.content_type:
        ext = ".gif"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(payload.filename).stem)[:48] or "avatar"
    filename = f"{name}-{hashlib.sha1(raw).hexdigest()[:12]}{ext}"
    path = BLOG_AVATAR_DIR / filename
    path.write_bytes(raw)
    return {"avatar_url": f"/api/resources/blog_avatars/{filename}"}


@app.get("/blog_avatars/{filename}")
def get_blog_avatar(filename: str) -> FileResponse:
    path = BLOG_AVATAR_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="avatar not found")
    return FileResponse(str(path))


@app.delete("/blog_posts/{post_id}")
def delete_blog_post(post_id: int) -> dict:
    with _get_conn() as conn:
        conn.execute("DELETE FROM blog_posts WHERE id = ?", (post_id,))
        conn.commit()
    return {"status": "deleted"}


@app.get("/auth_users")
def auth_users() -> dict:
    with _get_conn() as conn:
        rows = conn.execute("SELECT username, phone, email, nickname, role, status, created_at, updated_at FROM auth_users ORDER BY id DESC").fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/auth_users")
def create_auth_user(payload: AuthUserCreate) -> dict:
    username = payload.username.strip()
    nickname = payload.nickname.strip()
    role = _normalize_user_role(payload.role)
    phone = _placeholder_phone_for_text(username)
    email = _placeholder_email_for_text(username)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_users (username, phone, email, password_hash, nickname, role, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (username, "", "", _password_hash(payload.password), nickname, role, _utc_now(), _utc_now()),
        )
        conn.commit()
    return {"status": "created", "username": username, "nickname": nickname, "role": role}


@app.post("/auth_users/verify")
def verify_auth_user(payload: AuthUserVerify) -> dict:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT username, nickname, role, password_hash FROM auth_users WHERE username = ?",
            (payload.username.strip(),),
        ).fetchone()
    if not row or row["password_hash"] != _password_hash(payload.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"username": row["username"], "nickname": row["nickname"], "role": row["role"]}


@app.post("/auth_users/register_phone")
def register_phone_user(payload: AuthPhoneRegister) -> dict:
    phone = _normalize_phone(payload.phone)
    email = _placeholder_email_for_phone(phone)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_users (username, phone, email, password_hash, nickname, role, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'member', 'active', ?, ?)
            """,
            (phone, phone, "", _password_hash(payload.password), payload.nickname.strip(), _utc_now(), _utc_now()),
        )
        conn.commit()
    return {"status": "created", "username": phone, "nickname": payload.nickname.strip(), "role": "member"}


@app.post("/auth_users/verify_phone")
def verify_phone_user(payload: AuthPhoneVerify) -> dict:
    phone = _normalize_phone(payload.phone)
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT username, nickname, role, password_hash FROM auth_users WHERE phone = ?",
            (phone,),
        ).fetchone()
    if not row or row["password_hash"] != _password_hash(payload.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"username": row["username"], "nickname": row["nickname"], "role": row["role"]}


@app.post("/auth_users/register_email")
def register_email_user(payload: AuthEmailRegister) -> dict:
    email = _normalize_email(payload.email)
    username = email.split("@", 1)[0]
    phone = _placeholder_phone_for_email(email)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_users (username, phone, email, password_hash, nickname, role, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'member', 'active', ?, ?)
            """,
            (username, phone, email, _password_hash(payload.password), payload.nickname.strip(), _utc_now(), _utc_now()),
        )
        conn.commit()
    return {"status": "created", "username": username, "nickname": payload.nickname.strip(), "role": "member"}


@app.post("/auth_users/verify_email")
def verify_email_user(payload: AuthEmailVerify) -> dict:
    email = _normalize_email(payload.email)
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT username, nickname, role, password_hash FROM auth_users WHERE email = ?",
            (email,),
        ).fetchone()
    if not row or row["password_hash"] != _password_hash(payload.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"username": row["username"], "nickname": row["nickname"], "role": row["role"]}


@app.post("/auth_users/set_password_email")
def set_password_email(payload: AuthSetPasswordByEmail) -> dict:
    email = _normalize_email(payload.email)
    with _get_conn() as conn:
        conn.execute("UPDATE auth_users SET password_hash = ?, updated_at = ? WHERE email = ?", (_password_hash(payload.new_password), _utc_now(), email))
        conn.commit()
    return {"status": "updated", "email": email}


@app.post("/community_items/bulk_import")
def bulk_import_community_items(payload: CommunityItemBulkImportRequest) -> dict:
    items = [
        _normalize_item(
            title=item.title,
            url=item.url,
            module=item.module,
            summary=item.summary,
            source=item.source,
        )
        for item in payload.items
    ]
    return _bulk_insert(items, replace_existing=payload.replace_existing)


@app.post("/community_items/import_niuke")
def import_niuke_items(payload: PresetImportRequest) -> dict:
    items = [dict(item) for item in NIUKE_SITE_ITEMS]
    return _bulk_insert(items, replace_existing=payload.replace_existing)


@app.post("/community_items/import_catalog_seed")
def import_catalog_seed(payload: PresetImportRequest) -> dict:
    return _seed_catalog_items(replace_existing=payload.replace_existing)


@app.post("/community_items/import_forum")
def import_forum_items(payload: ForumImportRequest) -> dict:
    org = str(payload.org or "openKG-field").strip() or "openKG-field"
    try:
        data = _safe_http_json(
            f"{COMMUNITY_SERVICE_URL}/forum_items",
            query={"org": org, "per_page": payload.per_page},
        )
        raw_items = data.get("items", []) if isinstance(data, dict) else []
    except HTTPException:
        catalog = load_catalog()
        raw_items = [
            {
                "title": str(row.get("title") or row.get("topic") or "").strip(),
                "summary": str(row.get("summary") or row.get("goal") or row.get("description") or "").strip(),
                "html_url": str(row.get("discussion_url") or row.get("reference_url") or row.get("github_url") or row.get("detail_url") or row.get("issue_url") or f"https://github.com/{org}").strip(),
                "category": str(row.get("category") or row.get("topic_category") or "主题").strip() or "主题",
                "labels": [],
                "source": "catalog_topic_forum",
                "kind": "topic",
            }
            for row in (catalog.get("topic_forum", []) or [])
            if isinstance(row, dict)
        ]

    items = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("topic") or "").strip()
        url = str(row.get("html_url") or row.get("url") or row.get("discussion_url") or row.get("reference_url") or f"https://github.com/{org}").strip()
        if not title or not url:
            continue
        summary = str(row.get("summary") or row.get("description") or row.get("goal") or "").strip()
        if not summary:
            summary = title
        items.append(
            _normalize_item(
                title=title,
                url=url,
                module="主题论坛",
                summary=summary,
                source=str(row.get("source") or "openkg_field_topic").strip() or "openkg_field_topic",
            )
        )
    return _bulk_insert(items, replace_existing=payload.replace_existing)


@app.post("/community_items/import_arxiv")
def import_arxiv_items(payload: ArxivImportRequest) -> dict:
    query = str(payload.query or "").strip() or ARXIV_DEFAULT_QUERY
    return _sync_arxiv_items(
        query=query,
        max_results=payload.max_results,
        replace_existing=payload.replace_existing,
        timeout_seconds=payload.timeout_seconds,
        use_llm_translation=payload.use_llm_translation,
    )


@app.post("/community_items/import_arxiv_now")
def import_arxiv_now() -> dict:
    return _run_arxiv_auto_sync_once()


@app.get("/community_items/modules_summary")
def community_items_modules_summary() -> dict:
    return _community_items_modules_summary()


@app.get("/community_items/modules_manifest")
def community_items_modules_manifest() -> dict:
    return _community_modules_manifest()


@app.get("/community_modules")
def community_modules() -> dict:
    return {"items": _query_installed_modules()}


@app.post("/community_modules/install")
def community_modules_install(payload: CommunityModuleInstallRequest) -> dict:
    template = _find_module_template(payload.template_key)
    if not template:
        raise HTTPException(status_code=404, detail="module template not found")
    package = _serialize_module_package(template, alias=payload.alias)
    result = _install_module_package(package, replace_existing=payload.replace_existing)
    return {"module": result["module"], "mode": result["mode"]}


@app.post("/community_modules/import")
def community_modules_import(payload: CommunityModuleImportRequest) -> dict:
    installed = 0
    skipped = 0
    for raw in payload.packages:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        template_key = str(
            raw.get("template_key")
            or raw.get("key")
            or (raw.get("package", {}).get("template_key") if isinstance(raw.get("package"), dict) else "")
            or ""
        ).strip()
        if not template_key and not isinstance(raw.get("package"), dict):
            skipped += 1
            continue
        template = _find_module_template(template_key) if template_key else None
        package = _coerce_module_package(
            raw,
            template=template,
            alias=str(raw.get("alias") or raw.get("label") or (raw.get("package", {}).get("label") if isinstance(raw.get("package"), dict) else "") or "").strip() or None,
        )
        if not package.get("template_key"):
            skipped += 1
            continue
        _install_module_package(package, replace_existing=payload.replace_existing)
        installed += 1
    return {"installed": installed, "skipped": skipped, "items": _query_installed_modules()}


@app.get("/community_modules/export")
def community_modules_export(template_key: str | None = None, module_id: int | None = None) -> dict:
    with _get_conn() as conn:
        row = None
        if module_id is not None:
            row = conn.execute(
                "SELECT id, template_key, label, source, default_grouping, description, package_json, created_at, updated_at FROM community_modules WHERE id = ?",
                (module_id,),
            ).fetchone()
        elif template_key:
            row = conn.execute(
                "SELECT id, template_key, label, source, default_grouping, description, package_json, created_at, updated_at FROM community_modules WHERE template_key = ? ORDER BY id DESC LIMIT 1",
                (template_key,),
            ).fetchone()
    if row is not None:
        package = _module_package_from_row(row)
        filename_base = _safe_filename(str(package.get("label") or row["template_key"] or "module"))
        filename_key = _safe_filename(str(row["template_key"] or "module"))
        return {"package": package, "filename": f"{filename_base}-{filename_key}.module.json"}
    if not template_key:
        raise HTTPException(status_code=400, detail="template_key or module_id is required")
    template = _find_module_template(template_key)
    if not template:
        raise HTTPException(status_code=404, detail="module template not found")
    package = _serialize_module_package(template)
    package["exported_at"] = _utc_now()
    filename_base = _safe_filename(str(package.get("label") or template_key or "module"))
    filename_key = _safe_filename(str(template_key or "module"))
    return {"package": package, "filename": f"{filename_base}-{filename_key}.module.json"}


@app.get("/community_items/export_markdown")
def export_community_items_markdown(module: str | None = None) -> dict:
    rows = _query_community_items(_validate_module(module) if module else None)
    lines = ["# 社区条目导出", ""]
    for row in rows:
        lines.append(f"- [{row['module']}] {row['title']} - {row['url']}")
    return {"markdown": "\n".join(lines), "count": len(rows)}


@app.get("/community_items/export_json")
def export_community_items_json(module: str | None = None) -> dict:
    return {"items": _query_community_items(_validate_module(module) if module else None)}


@app.get("/community_items/quality_report")
def community_items_quality_report(stale_days: int = Query(default=30, ge=1, le=365)) -> dict:
    return _community_items_quality_report(stale_days=stale_days)
