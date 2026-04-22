import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "false").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(
    title="api-gateway",
    version="0.2.0",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COMMUNITY_SERVICE_URL = os.getenv("COMMUNITY_SERVICE_URL", "http://community-service:8001").rstrip("/")
BENCHMARK_SERVICE_URL = os.getenv("BENCHMARK_SERVICE_URL", "http://benchmark-service:8002").rstrip("/")
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm-service:8003").rstrip("/")
RESOURCE_SERVICE_URL = os.getenv("RESOURCE_SERVICE_URL", "http://resource-service:8004").rstrip("/")

FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", "/app/frontend")).resolve()
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def call_json(
    base_url: str,
    path: str,
    method: str = "GET",
    query: dict | None = None,
    payload: dict | None = None,
) -> dict:
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"

    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

    req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


@app.get("/")
def index() -> FileResponse:
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(str(index_path))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.get("/api/community/overview")
def community_overview() -> dict:
    try:
        return call_json(COMMUNITY_SERVICE_URL, "/overview")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Community service unavailable: {exc}") from exc


@app.get("/api/community/issues")
def community_issues(state: str = "open", per_page: int = 20) -> dict:
    try:
        return call_json(COMMUNITY_SERVICE_URL, "/issues", query={"state": state, "per_page": per_page})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Community service unavailable: {exc}") from exc


@app.get("/api/community/org-repositories")
def community_org_repositories(org: str | None = None, per_page: int = 20) -> dict:
    query = {"per_page": per_page}
    if org:
        query["org"] = org
    try:
        return call_json(COMMUNITY_SERVICE_URL, "/org_repositories", query=query)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Community service unavailable: {exc}") from exc


@app.get("/api/benchmarks/tasks")
def benchmark_tasks() -> dict:
    try:
        return call_json(BENCHMARK_SERVICE_URL, "/tasks")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Benchmark service unavailable: {exc}") from exc


@app.get("/api/benchmarks/leaderboard")
def benchmark_leaderboard() -> dict:
    try:
        return call_json(BENCHMARK_SERVICE_URL, "/leaderboard")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Benchmark service unavailable: {exc}") from exc


@app.post("/api/benchmarks/run", include_in_schema=False)
def benchmark_run(payload: dict) -> dict:
    try:
        return call_json(BENCHMARK_SERVICE_URL, "/run", method="POST", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Benchmark service unavailable: {exc}") from exc


@app.post("/api/assistant/chat")
def assistant_chat(payload: dict) -> dict:
    try:
        return call_json(LLM_SERVICE_URL, "/chat", method="POST", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM service unavailable: {exc}") from exc


@app.post("/api/assistant/generate-community")
def assistant_generate_community(payload: dict) -> dict:
    requirements = str(payload.get("requirements", "")).strip()
    if not requirements:
        raise HTTPException(status_code=400, detail="requirements is required")

    try:
        modules_summary = call_json(RESOURCE_SERVICE_URL, "/community_items/modules_summary")
        seed_items_resp = call_json(RESOURCE_SERVICE_URL, "/community_items", query={"limit": 120})
        seed_items = seed_items_resp.get("items", []) if isinstance(seed_items_resp, dict) else []
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        modules_summary = {"total": 0, "by_module": {}}
        seed_items = []

    llm_payload = {
        "requirements": requirements,
        "modules_summary": modules_summary,
        "seed_items": seed_items,
        "model": payload.get("model"),
        "temperature": payload.get("temperature", 0.2),
        "max_tokens": payload.get("max_tokens", 1400),
    }

    try:
        return call_json(LLM_SERVICE_URL, "/generate_community", method="POST", payload=llm_payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM service unavailable: {exc}") from exc


@app.post("/api/assistant/maintain-community")
def assistant_maintain_community(payload: dict | None = None) -> dict:
    req = payload or {}
    focus = str(req.get("focus", "")).strip() or "请按社区日常维护标准做一次巡检并给出本周待办。"

    modules_summary: dict = {"total": 0, "by_module": {}}
    recent_items: list[dict] = []
    recent_blogs: list[dict] = []
    open_issues: list[dict] = []

    try:
        modules_summary = call_json(RESOURCE_SERVICE_URL, "/community_items/modules_summary")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        modules_summary = {"total": 0, "by_module": {}, "unavailable": True}

    try:
        items_resp = call_json(RESOURCE_SERVICE_URL, "/community_items", query={"limit": 180})
        recent_items = items_resp.get("items", []) if isinstance(items_resp, dict) else []
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        recent_items = []

    try:
        blogs_resp = call_json(
            RESOURCE_SERVICE_URL,
            "/blog_posts",
            query={"page": 1, "page_size": 30, "status": "all", "include_content": "false"},
        )
        recent_blogs = blogs_resp.get("items", []) if isinstance(blogs_resp, dict) else []
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        recent_blogs = []

    try:
        issues_resp = call_json(COMMUNITY_SERVICE_URL, "/issues", query={"state": "open", "per_page": 20})
        open_issues = issues_resp.get("items", []) if isinstance(issues_resp, dict) else []
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        open_issues = []

    llm_payload = {
        "focus": focus,
        "modules_summary": modules_summary,
        "recent_items": recent_items,
        "recent_blogs": recent_blogs,
        "open_issues": open_issues,
        "model": req.get("model"),
        "temperature": req.get("temperature", 0.15),
        "max_tokens": req.get("max_tokens", 1600),
    }

    try:
        return call_json(LLM_SERVICE_URL, "/maintain_community", method="POST", payload=llm_payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM service unavailable: {exc}") from exc


@app.post("/api/llm/chat", include_in_schema=False)
def llm_chat(payload: dict) -> dict:
    try:
        return call_json(LLM_SERVICE_URL, "/chat", method="POST", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM service unavailable: {exc}") from exc


@app.get("/api/resources/catalog")
def resources_catalog() -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, "/catalog")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.get("/api/resources/community-items")
def resources_community_items(module: str | None = None, limit: int = 200) -> dict:
    query = {"limit": limit}
    if module:
        query["module"] = module
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items", query=query)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.post("/api/resources/community-items")
def resources_create_community_item(payload: dict) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items", method="POST", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.patch("/api/resources/community-items/{item_id}")
def resources_update_community_item(item_id: int, payload: dict) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, f"/community_items/{item_id}", method="PATCH", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.delete("/api/resources/community-items/{item_id}")
def resources_delete_community_item(item_id: int) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, f"/community_items/{item_id}", method="DELETE")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.post("/api/resources/community-items/bulk-import")
def resources_bulk_import_community_items(payload: dict) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items/bulk_import", method="POST", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.post("/api/resources/community-items/import-niuke")
def resources_import_niuke_items(payload: dict | None = None) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items/import_niuke", method="POST", payload=payload or {})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.get("/api/resources/community-items/modules-summary")
def resources_community_items_modules_summary() -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items/modules_summary")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.get("/api/resources/community-items/export-markdown")
def resources_export_community_items_markdown(module: str | None = None) -> dict:
    query: dict[str, str] = {}
    if module:
        query["module"] = module
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items/export_markdown", query=query if query else None)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.get("/api/resources/community-items/export-json")
def resources_export_community_items_json(module: str | None = None) -> dict:
    query: dict[str, str] = {}
    if module:
        query["module"] = module
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items/export_json", query=query if query else None)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.get("/api/resources/community-items/quality-report")
def resources_community_items_quality_report(module: str | None = None, stale_days: int = 90) -> dict:
    query: dict[str, str] = {"stale_days": str(stale_days)}
    if module:
        query["module"] = module
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items/quality_report", query=query)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.get("/api/resources/blog-posts")
def resources_blog_posts(
    page: int = 1,
    page_size: int = 10,
    limit: int | None = None,
    keyword: str | None = None,
    tag: str | None = None,
    status: str = "published",
    include_content: bool = False,
) -> dict:
    query: dict[str, str] = {
        "page": str(page),
        "page_size": str(page_size),
        "status": status,
        "include_content": str(bool(include_content)).lower(),
    }
    if limit is not None:
        query["limit"] = str(limit)
    if keyword:
        query["keyword"] = keyword
    if tag:
        query["tag"] = tag
    try:
        return call_json(RESOURCE_SERVICE_URL, "/blog_posts", query=query)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.get("/api/resources/blog-posts/{post_id}")
def resources_blog_post_detail(post_id: int) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, f"/blog_posts/{post_id}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=404, detail=f"Blog post not found: {post_id}") from exc
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.post("/api/resources/blog-posts")
def resources_create_blog_post(payload: dict) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, "/blog_posts", method="POST", payload=payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=exc.code, detail=body or str(exc)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.patch("/api/resources/blog-posts/{post_id}")
def resources_update_blog_post(post_id: int, payload: dict) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, f"/blog_posts/{post_id}", method="PATCH", payload=payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=exc.code, detail=body or str(exc)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.delete("/api/resources/blog-posts/{post_id}")
def resources_delete_blog_post(post_id: int) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, f"/blog_posts/{post_id}", method="DELETE")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=exc.code, detail=body or str(exc)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc

