import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import FastAPI, Query

app = FastAPI(title="community-service", version="0.1.0")

GITHUB_API_BASE = os.getenv("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_ORG = os.getenv("GITHUB_ORG", "MMX-11").strip() or "MMX-11"
GITHUB_FORUM_ORG = os.getenv("GITHUB_FORUM_ORG", "openKG-field").strip() or "openKG-field"
HF_ORG = os.getenv("HF_ORG", "").strip()

DEFAULT_OWNER = GITHUB_OWNER or "MMX-11"
DEFAULT_REPO = GITHUB_REPO or "microservice-open-community"
DEFAULT_REPO_FULLNAME = f"{DEFAULT_OWNER}/{DEFAULT_REPO}"


def _github_get(path: str, params: dict | None = None) -> dict | list:
    url = f"{GITHUB_API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "openkg-literature-community",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url=url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _mock_overview() -> dict:
    return {
        "source": "mock",
        "repository": DEFAULT_REPO_FULLNAME,
        "organization": GITHUB_ORG,
        "stars": 0,
        "forks": 0,
        "open_issues": 0,
        "default_branch": "main",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "html_url": f"https://github.com/{DEFAULT_REPO_FULLNAME}",
        "hint": "Set GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN in .env to enable live GitHub data.",
        "hf_org": HF_ORG or "https://huggingface.co/your-org",
    }


def _mock_issues() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "number": 1,
            "title": "完善文献任务榜的数据治理规范",
            "state": "open",
            "html_url": f"https://github.com/{DEFAULT_REPO_FULLNAME}/issues/1",
            "labels": ["governance", "documentation"],
            "updated_at": now,
        },
        {
            "number": 2,
            "title": "补充文献语义匹配基线与评测说明",
            "state": "open",
            "html_url": f"https://github.com/{DEFAULT_REPO_FULLNAME}/issues/2",
            "labels": ["benchmark", "nlp"],
            "updated_at": now,
        },
    ]


def _mock_org_repositories() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "name": "microservice-open-community",
            "full_name": DEFAULT_REPO_FULLNAME,
            "description": "文献领域开源社区平台源码与部署仓库。",
            "language": "Python",
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 2,
            "updated_at": now,
            "html_url": f"https://github.com/{DEFAULT_REPO_FULLNAME}",
        },
        {
            "name": "SciGPT",
            "full_name": DEFAULT_REPO_FULLNAME,
            "description": "文献任务榜与评测入口，统一收敛到社区主仓库。",
            "language": "",
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 0,
            "updated_at": now,
            "html_url": f"https://github.com/{DEFAULT_REPO_FULLNAME}/tree/main/benchmarks",
        },
        {
            "name": "kgbook-2020",
            "full_name": DEFAULT_REPO_FULLNAME,
            "description": "部署与文档入口（统一收敛到社区主仓库）。",
            "language": "Python",
            "stargazers_count": 13,
            "forks_count": 0,
            "open_issues_count": 0,
            "updated_at": now,
            "html_url": f"https://github.com/{DEFAULT_REPO_FULLNAME}/tree/main/docs",
        },
    ]


def _mock_forum_items() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "title": "SciGPT",
            "summary": "科技文献任务评测与资料整理入口。",
            "html_url": "https://github.com/openKG-field/SciGPT",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "资料资源",
            "labels": ["benchmark", "paper"],
            "repo": "SciGPT",
            "kind": "repo",
        },
        {
            "title": "kgbook-2020",
            "summary": "知识图谱章节、文档和教程整理。",
            "html_url": "https://github.com/openKG-field/kgbook-2020",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "资料资源",
            "labels": ["doc", "tutorial"],
            "repo": "kgbook-2020",
            "kind": "repo",
        },
        {
            "title": "Yuanchuang_Platform",
            "summary": "基于 Vue3 + TypeScript + Node.js 的智能工作流管理平台。",
            "html_url": "https://github.com/openKG-field/Yuanchuang_Platform",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "工具链",
            "labels": ["workflow", "platform"],
            "repo": "Yuanchuang_Platform",
            "kind": "repo",
        },
        {
            "title": "PaokuGame",
            "summary": "基于 Unity 平台的动作捕捉提取系统的跑酷游戏设计与实现。",
            "html_url": "https://github.com/openKG-field/PaokuGame",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "项目协作",
            "labels": ["unity", "game"],
            "repo": "PaokuGame",
            "kind": "repo",
        },
        {
            "title": "lmz-project",
            "summary": "知识图谱相关研究与项目协作条目。",
            "html_url": "https://github.com/openKG-field/lmz-project",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "项目协作",
            "labels": ["project"],
            "repo": "lmz-project",
            "kind": "repo",
        },
        {
            "title": "PatentNLP-Benchmark",
            "summary": "面向专利文档各类任务的基准集合。",
            "html_url": "https://github.com/openKG-field/PatentNLP-Benchmark",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "资料资源",
            "labels": ["benchmark", "nlp"],
            "repo": "PatentNLP-Benchmark",
            "kind": "repo",
        },
        {
            "title": "LII_INTJ",
            "summary": "基于“智能创新”与文本处理的协作型项目。",
            "html_url": "https://github.com/openKG-field/LII_INTJ",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "项目协作",
            "labels": ["project", "community"],
            "repo": "LII_INTJ",
            "kind": "repo",
        },
        {
            "title": "Semantic-Text-Similarity-STS-with-functional-semantic-knowledge-FOP-in-patents",
            "summary": "专利语义相似度任务与功能语义知识相关研究。",
            "html_url": "https://github.com/openKG-field/Semantic-Text-Similarity-STS-with-functional-semantic-knowledge-FOP-in-patents",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "资料资源",
            "labels": ["benchmark", "similarity"],
            "repo": "Semantic-Text-Similarity-STS-with-functional-semantic-knowledge-FOP-in-patents",
            "kind": "repo",
        },
        {
            "title": "Search-element-based-on-Knowledge-Map",
            "summary": "基于知识图谱的检索与搜索元素项目。",
            "html_url": "https://github.com/openKG-field/Search-element-based-on-Knowledge-Map",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "工具链",
            "labels": ["search", "knowledge-map"],
            "repo": "Search-element-based-on-Knowledge-Map",
            "kind": "repo",
        },
        {
            "title": "PatentGLUE_MT",
            "summary": "专利语言理解评测基准，含机器翻译任务。",
            "html_url": "https://github.com/openKG-field/PatentGLUE_MT",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "资料资源",
            "labels": ["benchmark", "mt"],
            "repo": "PatentGLUE_MT",
            "kind": "repo",
        },
        {
            "title": "Knowledge-of-Patents",
            "summary": "专利知识图谱与相关研究条目集合。",
            "html_url": "https://github.com/openKG-field/Knowledge-of-Patents",
            "updated_at": now,
            "source": "openkg_field_repo",
            "category": "资料资源",
            "labels": ["patent", "knowledge"],
            "repo": "Knowledge-of-Patents",
            "kind": "repo",
        },
    ]


def _strip_issue_title_prefix(text: str) -> str:
    value = re.sub(r"^\s*\[[^\]]+\]\s*", "", str(text or "").strip())
    value = re.sub(r"^\s*(issue|discussion|question|proposal|qa|q&a)\s*[:：-]\s*", "", value, flags=re.IGNORECASE)
    return value.strip()


def _repo_category(name: str, description: str = "") -> str:
    text = f"{name} {description}".lower()
    keyword_groups = [
        ("活动讨论", ["event", "meetup", "workshop", "seminar", "活动", "会议", "论坛", "讨论"]),
        ("资料资源", ["dataset", "doc", "paper", "book", "benchmark", "resource", "tutorial", "guide", "资料", "文档", "教程"]),
        ("工具链", ["tool", "cli", "plugin", "framework", "api", "sdk", "platform", "pipeline", "工具", "框架", "接口"]),
        ("项目协作", ["project", "roadmap", "plan", "coordinator", "team", "协作", "项目", "路线图"]),
    ]
    for category, keywords in keyword_groups:
        if any(keyword in text for keyword in keywords):
            return category
    return "综合讨论"


def _issue_category(title: str, body: str = "", labels: list[str] | None = None, repo_name: str = "") -> str:
    text = f"{title} {body} {repo_name} {' '.join(labels or [])}".lower()
    if any(keyword in text for keyword in ["event", "meetup", "workshop", "seminar", "活动", "分享会", "论坛"]):
        return "活动讨论"
    if any(keyword in text for keyword in ["doc", "paper", "dataset", "book", "benchmark", "resource", "tutorial", "资料", "文档", "教程"]):
        return "资料资源"
    if any(keyword in text for keyword in ["tool", "cli", "plugin", "framework", "api", "sdk", "工具", "框架", "接口", "部署"]):
        return "工具链"
    if any(keyword in text for keyword in ["bug", "issue", "error", "fail", "question", "q&a", "qa", "problem", "报错", "问题", "无法", "配置"]):
        return "问题反馈"
    if any(keyword in text for keyword in ["project", "roadmap", "plan", "proposal", "协作", "项目", "建议"]):
        return "项目协作"
    return "综合讨论"


def _github_search_issues(org: str, per_page: int) -> list[dict]:
    raw = _github_get(
        "/search/issues",
        params={
            "q": f"org:{org} is:issue state:open",
            "sort": "updated",
            "order": "desc",
            "per_page": per_page,
        },
    )
    items = []
    for item in raw.get("items", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict) or "pull_request" in item:
            continue
        repo_url = str(item.get("repository_url", "")).rstrip("/")
        repo_name = repo_url.rsplit("/", 1)[-1] if repo_url else ""
        labels = [label.get("name", "") for label in item.get("labels", []) if isinstance(label, dict)]
        title = _strip_issue_title_prefix(item.get("title", ""))
        body = str(item.get("body", "") or "").strip()
        items.append(
            {
                "title": title or item.get("title", ""),
                "summary": body[:280].replace("\r", " ").replace("\n", " "),
                "html_url": item.get("html_url", ""),
                "updated_at": item.get("updated_at"),
                "source": "openkg_field_issue",
                "category": _issue_category(title or item.get("title", ""), body, labels, repo_name),
                "labels": labels,
                "repo": repo_name,
                "kind": "issue",
            }
        )
    return items


def _github_org_forum_items(org: str, per_page: int) -> list[dict]:
    repos_resp = _github_get(f"/orgs/{org}/repos", params={"per_page": min(100, per_page), "sort": "updated"})
    repos = repos_resp if isinstance(repos_resp, list) else []
    repo_items = []
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        name = str(repo.get("name", "")).strip()
        description = str(repo.get("description", "")).strip()
        repo_items.append(
            {
                "title": name or str(repo.get("full_name", "")).rsplit("/", 1)[-1],
                "summary": description,
                "html_url": repo.get("html_url", ""),
                "updated_at": repo.get("updated_at"),
                "source": "openkg_field_repo",
                "category": _repo_category(name, description),
                "labels": [repo.get("language", "")] if repo.get("language") else [],
                "repo": name,
                "kind": "repo",
            }
        )
    items = repo_items + _github_search_issues(org, per_page=per_page)
    items.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return items[:per_page]


def _to_repo_brief(item: dict) -> dict:
    return {
        "name": item.get("name", ""),
        "full_name": item.get("full_name", ""),
        "description": item.get("description", ""),
        "language": item.get("language", ""),
        "stars": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "open_issues": item.get("open_issues_count", 0),
        "updated_at": item.get("updated_at"),
        "html_url": item.get("html_url", ""),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "community-service"}


@app.get("/overview")
def overview() -> dict:
    owner = DEFAULT_OWNER
    repo_name = DEFAULT_REPO
    try:
        repo = _github_get(f"/repos/{owner}/{repo_name}")
        return {
            "source": "github",
            "repository": repo.get("full_name", f"{owner}/{repo_name}"),
            "organization": GITHUB_ORG,
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "open_issues": repo.get("open_issues_count", 0),
            "default_branch": repo.get("default_branch", "main"),
            "updated_at": repo.get("updated_at"),
            "html_url": repo.get("html_url"),
            "hf_org": HF_ORG or "https://huggingface.co/your-org",
        }
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        data = _mock_overview()
        data["error"] = f"{type(exc).__name__}: {exc}"
        return data


@app.get("/issues")
def issues(
    state: str = Query(default="open", pattern="^(open|closed|all)$"),
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict:
    owner = DEFAULT_OWNER
    repo_name = DEFAULT_REPO
    try:
        raw = _github_get(f"/repos/{owner}/{repo_name}/issues", params={"state": state, "per_page": per_page})
        items = []
        for item in raw:
            if "pull_request" in item:
                continue
            items.append(
                {
                    "number": item.get("number"),
                    "title": item.get("title"),
                    "state": item.get("state"),
                    "html_url": item.get("html_url"),
                    "labels": [label.get("name", "") for label in item.get("labels", [])],
                    "updated_at": item.get("updated_at"),
                }
            )
        return {"source": "github", "items": items}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"source": "mock", "error": f"{type(exc).__name__}: {exc}", "items": _mock_issues()}


@app.get("/org_repositories")
def org_repositories(org: str | None = None, per_page: int = Query(default=20, ge=1, le=100)) -> dict:
    target_org = (org or GITHUB_ORG or "").strip()
    if not target_org:
        return {"source": "mock", "organization": "", "items": _mock_org_repositories()}
    try:
        account_type = "org"
        try:
            raw = _github_get(f"/orgs/{target_org}/repos", params={"per_page": per_page, "sort": "updated"})
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", None) == 404:
                account_type = "user"
                raw = _github_get(f"/users/{target_org}/repos", params={"per_page": per_page, "sort": "updated"})
            else:
                raise
        items = [_to_repo_brief(item) for item in raw if isinstance(item, dict)]
        return {"source": "github", "organization": target_org, "account_type": account_type, "items": items}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "source": "mock",
            "organization": target_org,
            "error": f"{type(exc).__name__}: {exc}",
            "items": _mock_org_repositories(),
        }


@app.get("/forum_items")
def forum_items(org: str | None = None, per_page: int = Query(default=30, ge=1, le=100)) -> dict:
    target_org = (org or GITHUB_FORUM_ORG or "").strip()
    if not target_org:
        return {"source": "mock", "organization": "", "items": _mock_forum_items()}
    try:
        items = _github_org_forum_items(target_org, per_page=per_page)
        return {"source": "github", "organization": target_org, "items": items}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "source": "mock",
            "organization": target_org,
            "error": f"{type(exc).__name__}: {exc}",
            "items": _mock_forum_items(),
        }
