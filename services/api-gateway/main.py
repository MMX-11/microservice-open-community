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


@app.get("/api/resources/community-items", include_in_schema=False)
def resources_community_items(module: str | None = None, limit: int = 200) -> dict:
    query = {"limit": limit}
    if module:
        query["module"] = module
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items", query=query)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.post("/api/resources/community-items", include_in_schema=False)
def resources_create_community_item(payload: dict) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, "/community_items", method="POST", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.patch("/api/resources/community-items/{item_id}", include_in_schema=False)
def resources_update_community_item(item_id: int, payload: dict) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, f"/community_items/{item_id}", method="PATCH", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc


@app.delete("/api/resources/community-items/{item_id}", include_in_schema=False)
def resources_delete_community_item(item_id: int) -> dict:
    try:
        return call_json(RESOURCE_SERVICE_URL, f"/community_items/{item_id}", method="DELETE")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Resource service unavailable: {exc}") from exc

