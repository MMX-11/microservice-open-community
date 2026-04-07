import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(title="resource-service", version="0.1.0")

RESOURCE_FILE = Path(os.getenv("RESOURCE_FILE", "/app/resources/catalog.json"))
RESOURCE_DB_FILE = Path(os.getenv("RESOURCE_DB_FILE", "/app/data/community.db"))
ALLOWED_MODULES = {"文献任务榜", "AI前沿", "开源分享", "主题论坛"}
MODULE_ALIASES = {
    "文献任务榜": "文献任务榜",
    "AI前沿": "AI前沿",
    "开源分享": "开源分享",
    "主题论坛": "主题论坛",
    "literature_taskboard": "文献任务榜",
    "ai_frontier": "AI前沿",
    "open_source_sharing": "开源分享",
    "topic_forum": "主题论坛",
}


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
        "manager_taxonomy": {"main_modules": [], "task_axes": [], "ingest_flow": []},
        "contribution_spec": {
            "dataset_required_fields": ["name", "version", "license", "language", "download_url", "split"],
            "benchmark_required_fields": ["task_id", "metric", "baseline_name", "run_script"],
        },
    }


def load_catalog() -> dict:
    if RESOURCE_FILE.exists():
        with RESOURCE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return _default_catalog()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_module(module: str) -> str:
    name = module.strip()
    normalized = MODULE_ALIASES.get(name, "")
    if not normalized or normalized not in ALLOWED_MODULES:
        raise HTTPException(status_code=400, detail=f"Invalid module: {module}")
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
        conn.commit()


def _seed_from_catalog_if_empty() -> None:
    catalog = load_catalog()
    highlights = catalog.get("pdf_research_highlights", [])
    if not isinstance(highlights, list) or not highlights:
        return

    with _get_conn() as conn:
        count = conn.execute("SELECT COUNT(1) AS c FROM community_items").fetchone()["c"]
        if count > 0:
            return
        now = _utc_now()
        for item in highlights:
            title = str(item.get("title", "")).strip()
            url = str(item.get("reference_url", "")).strip()
            module = str(item.get("module", "")).strip() or "开源分享"
            summary = str(item.get("summary", "")).strip()
            if not title or not _valid_url(url) or module not in ALLOWED_MODULES:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO community_items
                (title, url, module, summary, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, url, module, summary, "pdf_extract", now, now),
            )
        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    _ensure_db()
    _seed_from_catalog_if_empty()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "resource-service", "db_file": str(RESOURCE_DB_FILE)}


@app.get("/catalog")
def catalog() -> dict:
    return load_catalog()


@app.get("/catalog/{section}")
def catalog_section(section: str) -> dict:
    data = load_catalog()
    if section not in data:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    return {"section": section, "items": data.get(section)}


@app.get("/community_items")
def community_items(
    module: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    sql = """
        SELECT id, title, url, module, summary, source, created_at, updated_at
        FROM community_items
    """
    params: list[object] = []
    if module:
        module_name = _validate_module(module)
        sql += " WHERE module = ?"
        params.append(module_name)
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    params.append(limit)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = [dict(row) for row in rows]
    return {"items": items}


@app.post("/community_items")
def create_community_item(payload: CommunityItemCreate) -> dict:
    module_name = _validate_module(payload.module)
    if not _valid_url(payload.url):
        raise HTTPException(status_code=400, detail="url must be a valid http/https URL")
    now = _utc_now()

    with _get_conn() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO community_items
                (title, url, module, summary, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.title.strip(),
                    payload.url.strip(),
                    module_name,
                    payload.summary.strip(),
                    payload.source.strip() or "manager",
                    now,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="item already exists") from exc

    return {"id": cursor.lastrowid, "status": "created"}


@app.patch("/community_items/{item_id}")
def update_community_item(item_id: int, payload: CommunityItemUpdate) -> dict:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM community_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")
        current = dict(row)

        title = payload.title.strip() if payload.title is not None else current["title"]
        url = payload.url.strip() if payload.url is not None else current["url"]
        module = _validate_module(payload.module) if payload.module is not None else current["module"]
        summary = payload.summary.strip() if payload.summary is not None else current["summary"]

        if not _valid_url(url):
            raise HTTPException(status_code=400, detail="url must be a valid http/https URL")

        try:
            conn.execute(
                """
                UPDATE community_items
                SET title = ?, url = ?, module = ?, summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, url, module, summary, _utc_now(), item_id),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="item already exists") from exc

    return {"id": item_id, "status": "updated"}


@app.delete("/community_items/{item_id}")
def delete_community_item(item_id: int) -> dict:
    with _get_conn() as conn:
        cursor = conn.execute("DELETE FROM community_items WHERE id = ?", (item_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")
    return {"id": item_id, "status": "deleted"}
