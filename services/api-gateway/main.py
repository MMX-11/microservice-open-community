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

app = FastAPI(title="api-gateway", version="0.1.0")

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


@app.post("/api/benchmarks/run")
def benchmark_run(payload: dict) -> dict:
    try:
        return call_json(BENCHMARK_SERVICE_URL, "/run", method="POST", payload=payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Benchmark service unavailable: {exc}") from exc


@app.post("/api/llm/chat")
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

