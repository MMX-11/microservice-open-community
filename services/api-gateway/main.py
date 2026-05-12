import base64
import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "false").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(
    title="api-gateway",
    version="0.3.0",
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
AUTH_SECRET = os.getenv("AUTH_SECRET", "change-this-secret").strip() or "change-this-secret"
AUTH_TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "2592000"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123").strip() or "admin123"
ADMIN_NICKNAME = os.getenv("ADMIN_NICKNAME", "管理员").strip() or "管理员"
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "18403437231").strip() or "18403437231"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "970595759@qq.com").strip().lower() or "970595759@qq.com"
USER_USERNAME = os.getenv("USER_USERNAME", "member").strip() or "member"
USER_PASSWORD = os.getenv("USER_PASSWORD", "member123").strip() or "member123"
USER_NICKNAME = os.getenv("USER_NICKNAME", "社区用户").strip() or "社区用户"
RUNTIME_SETTINGS: dict[str, bool] = {
    "moderation_enabled": os.getenv("MODERATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
}

FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", "/app/frontend")).resolve()
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def _auth_sign(raw: str) -> str:
    return hmac.new(AUTH_SECRET.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    return f"{body}.{_auth_sign(body)}"


def _decode_token(token: str) -> dict | None:
    text = str(token or "").strip()
    if "." not in text:
        return None
    body, sig = text.rsplit(".", 1)
    if not hmac.compare_digest(sig, _auth_sign(body)):
        return None
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
        )
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = int(payload.get("exp", 0) or 0)
    if exp <= int(datetime.now(timezone.utc).timestamp()):
        return None
    return payload


def _current_user(authorization: str | None) -> dict | None:
    text = str(authorization or "").strip()
    if not text:
        return None
    parts = text.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    payload = _decode_token(parts[1].strip())
    if not payload:
        return None
    return {
        "username": str(payload.get("username", "")).strip(),
        "nickname": str(payload.get("nickname", "")).strip() or "社区用户",
        "role": str(payload.get("role", "member")).strip() or "member",
    }


def _require_user(authorization: str | None) -> dict:
    user = _current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效。")
    return user


def _require_admin(authorization: str | None) -> dict:
    user = _require_user(authorization)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可执行该操作。")
    return user


def _request_bytes(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    query: dict | None = None,
    payload: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[bytes, str, int]:
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
    req = urllib.request.Request(
        url=url,
        data=payload,
        method=method,
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", "application/json"), int(resp.status)
    except urllib.error.HTTPError as exc:
        return exc.read(), exc.headers.get("Content-Type", "application/json"), int(exc.code)


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    query: dict | None = None,
    payload: dict | None = None,
    timeout: int = 30,
    headers: dict[str, str] | None = None,
) -> dict | list:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    merged_headers = {"Content-Type": "application/json", **(headers or {})}
    raw, _content_type, status = _request_bytes(
        base_url,
        path,
        method=method,
        query=query,
        payload=body,
        headers=merged_headers,
        timeout=timeout,
    )
    if status >= 400:
        text = raw.decode("utf-8", errors="ignore")
        raise HTTPException(status_code=status, detail=text or "Upstream request failed")
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _proxy_path(path: str) -> str:
    segments = [seg.replace("-", "_") for seg in str(path or "").split("/") if seg]
    return "/" + "/".join(segments)


def _resource_proxy(path: str, request: Request, *, timeout: int = 30) -> Response:
    upstream_path = _proxy_path(path)
    query = list(request.query_params.multi_items())
    query_dict: dict[str, list[str] | str] = {}
    for key, value in query:
        query_dict.setdefault(key, [])
        if isinstance(query_dict[key], list):
            query_dict[key].append(value)
    payload = None
    if request.method not in {"GET", "HEAD"}:
        payload = request._body if hasattr(request, "_body") else None
    if payload is None and request.method not in {"GET", "HEAD"}:
        payload = b""
    headers = {}
    content_type = request.headers.get("content-type")
    if content_type:
      headers["Content-Type"] = content_type
    raw, media_type, status = _request_bytes(
        RESOURCE_SERVICE_URL,
        upstream_path,
        method=request.method,
        query=query_dict,
        payload=payload,
        headers=headers or None,
        timeout=timeout,
    )
    return Response(content=raw, status_code=status, media_type=media_type)


def _safe_query_int(value: str | None, default: int, *, min_value: int = 1, max_value: int = 1000) -> int:
    try:
        number = int(str(value or "").strip() or default)
    except ValueError:
        return default
    return max(min_value, min(max_value, number))


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
    return _request_json(COMMUNITY_SERVICE_URL, "/overview")


@app.get("/api/community/issues")
def community_issues(state: str = "open", per_page: int = 20) -> dict:
    return _request_json(COMMUNITY_SERVICE_URL, "/issues", query={"state": state, "per_page": per_page})


@app.get("/api/community/org-repositories")
def community_org_repositories(org: str | None = None, per_page: int = 20) -> dict:
    query = {"per_page": per_page}
    if org:
        query["org"] = org
    return _request_json(COMMUNITY_SERVICE_URL, "/org_repositories", query=query)


@app.get("/api/community/forum-items")
def community_forum_items(org: str | None = None, per_page: int = 30) -> dict:
    query = {"per_page": per_page}
    if org:
        query["org"] = org
    return _request_json(COMMUNITY_SERVICE_URL, "/forum_items", query=query)


@app.api_route("/api/benchmarks/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
async def benchmark_proxy(path: str, request: Request) -> Response:
    return await _proxy_upstream(BENCHMARK_SERVICE_URL, path, request)


@app.api_route("/api/llm/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
async def llm_proxy(path: str, request: Request) -> Response:
    return await _proxy_upstream(LLM_SERVICE_URL, path, request)


@app.api_route("/api/resources/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
async def resources_proxy(path: str, request: Request) -> Response:
    return await _proxy_upstream(RESOURCE_SERVICE_URL, path, request)


async def _proxy_upstream(base_url: str, path: str, request: Request) -> Response:
    body = await request.body()
    headers = {}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    raw, media_type, status = _request_bytes(
        base_url,
        _proxy_path(path),
        method=request.method,
        query=dict(request.query_params),
        payload=body if body else None,
        headers=headers or None,
        timeout=60 if base_url == LLM_SERVICE_URL else 30,
    )
    return Response(content=raw, status_code=status, media_type=media_type)


@app.post("/api/auth/login")
def auth_login(payload: dict) -> dict:
    principal_input = str((payload or {}).get("principal", "")).strip()
    username = str((payload or {}).get("username", "")).strip()
    phone = str((payload or {}).get("phone", "")).strip()
    email = str((payload or {}).get("email", "")).strip().lower()
    password = str((payload or {}).get("password", "")).strip()
    if not password or not (principal_input or username or phone or email):
        raise HTTPException(status_code=400, detail="账号和密码不能为空。")

    principal = principal_input or phone or email or username
    if principal in {ADMIN_USERNAME, ADMIN_PHONE, ADMIN_EMAIL} and password == ADMIN_PASSWORD:
        role = "admin"
        account = ADMIN_USERNAME
        nickname = ADMIN_NICKNAME
    elif principal == USER_USERNAME and password == USER_PASSWORD:
        role = "member"
        account = USER_USERNAME
        nickname = USER_NICKNAME
    else:
        if "@" in principal and not email:
            email = principal
        elif principal.isdigit() and len(principal) == 11 and not phone:
            phone = principal
        endpoint = "/auth_users/verify_email" if email else "/auth_users/verify_phone" if phone else "/auth_users/verify"
        verify_payload = {
            "email": email,
            "phone": phone,
            "username": username or principal,
            "password": password,
        }
        try:
            verified = _request_json(RESOURCE_SERVICE_URL, endpoint, method="POST", payload=verify_payload)
        except HTTPException:
            raise HTTPException(status_code=401, detail="账号或密码错误。")
        role = str(verified.get("role", "member")).strip() or "member"
        account = str(verified.get("username", principal)).strip() or principal
        nickname = str(verified.get("nickname", "")).strip() or USER_NICKNAME

    now = int(datetime.now(timezone.utc).timestamp())
    token = _make_token(
        {
            "username": account,
            "nickname": nickname,
            "role": role,
            "iat": now,
            "exp": now + max(3600, AUTH_TOKEN_TTL_SECONDS),
        }
    )
    return {"token": token, "user": {"username": account, "nickname": nickname, "role": role}}


@app.post("/api/auth/register")
def auth_register(payload: dict) -> dict:
    phone = str((payload or {}).get("phone", "")).strip()
    email = str((payload or {}).get("email", "")).strip().lower()
    password = str((payload or {}).get("password", "")).strip()
    nickname = str((payload or {}).get("nickname", "")).strip()
    if phone:
        return _request_json(
            RESOURCE_SERVICE_URL,
            "/auth_users/register_phone",
            method="POST",
            payload={"phone": phone, "password": password, "nickname": nickname},
        )
    if email:
        return _request_json(
            RESOURCE_SERVICE_URL,
            "/auth_users/register_email",
            method="POST",
            payload={"email": email, "password": password, "nickname": nickname},
        )
    raise HTTPException(status_code=400, detail="请提供手机号或邮箱。")


@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(default=None)) -> dict:
    user = _current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效。")
    return {"user": user}


@app.get("/api/auth/settings")
def auth_settings(authorization: str | None = Header(default=None)) -> dict:
    user = _require_user(authorization)
    return {
        "moderation_enabled": bool(RUNTIME_SETTINGS.get("moderation_enabled", True)),
        "can_manage_users": user.get("role") == "admin",
    }


@app.patch("/api/auth/settings")
def auth_update_settings(payload: dict, authorization: str | None = Header(default=None)) -> dict:
    _require_admin(authorization)
    if "moderation_enabled" in payload:
        RUNTIME_SETTINGS["moderation_enabled"] = bool(payload.get("moderation_enabled"))
    return {"moderation_enabled": bool(RUNTIME_SETTINGS.get("moderation_enabled", True))}


@app.get("/api/auth/users")
def auth_users(authorization: str | None = Header(default=None)) -> dict:
    _require_admin(authorization)
    return _request_json(RESOURCE_SERVICE_URL, "/auth_users")


@app.post("/api/auth/users")
def auth_create_user(payload: dict, authorization: str | None = Header(default=None)) -> dict:
    _require_admin(authorization)
    safe_payload = {
        "username": str((payload or {}).get("username", "")).strip(),
        "password": str((payload or {}).get("password", "")).strip(),
        "nickname": str((payload or {}).get("nickname", "")).strip(),
        "role": "member",
    }
    return _request_json(RESOURCE_SERVICE_URL, "/auth_users", method="POST", payload=safe_payload)


@app.post("/api/assistant/generate-community")
def assistant_generate_community(payload: dict) -> dict:
    requirements = str(payload.get("requirements", "")).strip()
    if not requirements:
        raise HTTPException(status_code=400, detail="requirements is required")
    try:
        modules_summary = _request_json(RESOURCE_SERVICE_URL, "/community_items/modules_summary")
        seed_items_resp = _request_json(RESOURCE_SERVICE_URL, "/community_items", query={"limit": 120})
        seed_items = seed_items_resp.get("items", []) if isinstance(seed_items_resp, dict) else []
    except HTTPException:
        modules_summary = {"total": 0, "by_module": {}}
        seed_items = []
    return _request_json(
        LLM_SERVICE_URL,
        "/generate_community",
        method="POST",
        payload={
            "requirements": requirements,
            "modules_summary": modules_summary,
            "seed_items": seed_items,
            "model": payload.get("model"),
            "temperature": payload.get("temperature", 0.2),
            "max_tokens": payload.get("max_tokens", 1400),
        },
        timeout=60,
    )


@app.post("/api/assistant/maintain-community")
def assistant_maintain_community(payload: dict | None = None) -> dict:
    req = payload or {}
    focus = str(req.get("focus", "")).strip() or "请按社区日常维护标准做一次巡检并给出本周待办。"
    try:
        modules_summary = _request_json(RESOURCE_SERVICE_URL, "/community_items/modules_summary")
    except HTTPException:
        modules_summary = {"total": 0, "by_module": {}}
    try:
        recent_items_resp = _request_json(RESOURCE_SERVICE_URL, "/community_items", query={"limit": 180})
        recent_items = recent_items_resp.get("items", []) if isinstance(recent_items_resp, dict) else []
    except HTTPException:
        recent_items = []
    try:
        recent_blogs_resp = _request_json(
            RESOURCE_SERVICE_URL,
            "/blog_posts",
            query={"page": 1, "page_size": 30, "status": "all", "include_content": "false"},
        )
        recent_blogs = recent_blogs_resp.get("items", []) if isinstance(recent_blogs_resp, dict) else []
    except HTTPException:
        recent_blogs = []
    try:
        open_issues_resp = _request_json(COMMUNITY_SERVICE_URL, "/issues", query={"state": "open", "per_page": 20})
        open_issues = open_issues_resp.get("items", []) if isinstance(open_issues_resp, dict) else []
    except HTTPException:
        open_issues = []
    return _request_json(
        LLM_SERVICE_URL,
        "/maintain_community",
        method="POST",
        payload={
            "focus": focus,
            "modules_summary": modules_summary,
            "recent_items": recent_items,
            "recent_blogs": recent_blogs,
            "open_issues": open_issues,
            "model": req.get("model"),
            "temperature": req.get("temperature", 0.15),
            "max_tokens": req.get("max_tokens", 1600),
        },
        timeout=60,
    )


@app.post("/api/assistant/agent-manage")
async def assistant_agent_manage(payload: dict) -> dict:
    mode = str(payload.get("mode", "maintain")).strip()
    goal = str(payload.get("goal", "")).strip()
    execute_actions = bool(payload.get("execute_actions"))
    action_budget = max(1, min(3, int(payload.get("action_budget", 2) or 2)))
    model = payload.get("model")
    temperature = float(payload.get("temperature", 0.2) or 0.2)
    max_tokens = int(payload.get("max_tokens", 1200) or 1200)

    snapshot = await _assistant_snapshot()
    llm_path = "/maintain_community" if mode == "maintain" else "/open_source_community"
    llm_payload = {
        "focus": goal or "请给出社区巡检建议。",
        "goal": goal or "请给出开源社区建设建议。",
        "modules_summary": snapshot["modules_summary"],
        "recent_items": snapshot["recent_items"],
        "recent_blogs": snapshot["recent_blogs"],
        "open_issues": snapshot["open_issues"],
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    plan = _request_json(LLM_SERVICE_URL, llm_path, method="POST", payload=llm_payload, timeout=90)
    plan_markdown = str(
        plan.get("maintenance_markdown")
        or plan.get("open_source_markdown")
        or plan.get("community_markdown")
        or plan.get("response")
        or ""
    ).strip()

    executed_actions: list[dict] = []
    if execute_actions and action_budget > 0:
        executed_actions.append(await _assistant_import_starter_items())
    if execute_actions and action_budget > 1:
        executed_actions.append(await _assistant_create_draft(goal, plan_markdown, mode))

    return {
        "mode": mode,
        "source": str(plan.get("source", "mock")),
        "model": str(plan.get("model") or model or ""),
        "plan_markdown": plan_markdown,
        "executed_actions": executed_actions[:action_budget],
        "snapshot": snapshot,
    }


async def _assistant_snapshot() -> dict:
    try:
        modules_summary = _request_json(RESOURCE_SERVICE_URL, "/community_items/modules_summary")
    except HTTPException:
        modules_summary = {"total": 0, "by_module": {}}
    try:
        recent_items_resp = _request_json(RESOURCE_SERVICE_URL, "/community_items", query={"limit": 80})
        recent_items = recent_items_resp.get("items", []) if isinstance(recent_items_resp, dict) else []
    except HTTPException:
        recent_items = []
    try:
        recent_blogs_resp = _request_json(
            RESOURCE_SERVICE_URL,
            "/blog_posts",
            query={"page": 1, "page_size": 20, "status": "all", "include_content": "false"},
        )
        recent_blogs = recent_blogs_resp.get("items", []) if isinstance(recent_blogs_resp, dict) else []
    except HTTPException:
        recent_blogs = []
    try:
        open_issues_resp = _request_json(COMMUNITY_SERVICE_URL, "/issues", query={"state": "open", "per_page": 20})
        open_issues = open_issues_resp.get("items", []) if isinstance(open_issues_resp, dict) else []
    except HTTPException:
        open_issues = []
    return {
        "modules_summary": modules_summary,
        "recent_items": recent_items,
        "recent_blogs": recent_blogs,
        "open_issues": open_issues,
    }


async def _assistant_import_starter_items() -> dict:
    try:
        result = _request_json(
            RESOURCE_SERVICE_URL,
            "/community_items/import_niuke",
            method="POST",
            payload={"replace_existing": False, "scrape": False, "timeout_seconds": 10},
        )
        return {
            "id": "import_niuke",
            "name": "导入启动条目",
            "status": "done",
            "detail": f"created={result.get('created', 0)}, upserted={result.get('upserted', 0)}, skipped={result.get('skipped', 0)}",
        }
    except HTTPException as exc:
        return {"id": "import_niuke", "name": "导入启动条目", "status": "failed", "detail": str(exc.detail)}


async def _assistant_create_draft(goal: str, plan_markdown: str, mode: str) -> dict:
    title = (goal or "社区执行草稿").strip()[:40] or "社区执行草稿"
    if mode == "open_source":
        title = f"开源社区建设草稿：{title}"
    elif mode == "similar_community":
        title = f"同类社区方案草稿：{title}"
    else:
        title = f"社区巡检草稿：{title}"
    payload = {
        "title": title,
        "author": "社区助手",
        "summary": (goal or "自动生成的执行草稿").strip()[:120],
        "content_markdown": plan_markdown or "# 执行草稿\n\n暂无内容。",
        "share_url": None,
        "tags": ["社区助手", "执行草稿"],
        "status": "draft",
    }
    try:
        result = _request_json(RESOURCE_SERVICE_URL, "/blog_posts", method="POST", payload=payload)
        return {
            "id": "create_execution_draft",
            "name": "生成执行草稿",
            "status": "done",
            "detail": f"blog_id={result.get('id')}",
        }
    except HTTPException as exc:
        return {"id": "create_execution_draft", "name": "生成执行草稿", "status": "failed", "detail": str(exc.detail)}


@app.post("/api/resources/import-arxiv")
def resources_import_arxiv(payload: dict) -> dict:
    safe_payload = {
        "query": str((payload or {}).get("query", "")).strip() or None,
        "max_results": int((payload or {}).get("max_results", 12) or 12),
        "replace_existing": bool((payload or {}).get("replace_existing", False)),
        "timeout_seconds": int((payload or {}).get("timeout_seconds", 20) or 20),
        "use_llm_translation": bool((payload or {}).get("use_llm_translation", True)),
    }
    return _request_json(
        RESOURCE_SERVICE_URL,
        "/community_items/import_arxiv",
        method="POST",
        payload=safe_payload,
        timeout=90,
    )


@app.get("/api/llm/health")
def llm_health() -> dict:
    return _request_json(LLM_SERVICE_URL, "/health")


@app.post("/api/llm/chat")
def llm_chat(payload: dict) -> dict:
    return _request_json(LLM_SERVICE_URL, "/chat", method="POST", payload=payload, timeout=90)


@app.get("/api/benchmarks/tasks")
def benchmark_tasks() -> dict:
    return _request_json(BENCHMARK_SERVICE_URL, "/tasks")


@app.get("/api/benchmarks/leaderboard")
def benchmark_leaderboard() -> dict:
    return _request_json(BENCHMARK_SERVICE_URL, "/leaderboard")


@app.post("/api/benchmarks/run", include_in_schema=False)
def benchmark_run(payload: dict) -> dict:
    return _request_json(BENCHMARK_SERVICE_URL, "/run", method="POST", payload=payload)
