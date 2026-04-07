import json
import os
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
GITHUB_ORG = os.getenv("GITHUB_ORG", "openKG-field").strip() or "openKG-field"
HF_ORG = os.getenv("HF_ORG", "").strip()


def _github_get(path: str, params: dict | None = None) -> dict | list:
    url = f"{GITHUB_API_BASE}{path}"
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "patent-benchmark-platform",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    req = urllib.request.Request(url=url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def _mock_overview() -> dict:
    return {
        "source": "mock",
        "repository": "your-org/patent-benchmark-community",
        "organization": GITHUB_ORG,
        "stars": 0,
        "forks": 0,
        "open_issues": 0,
        "default_branch": "main",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "html_url": f"https://github.com/{GITHUB_ORG}" if GITHUB_ORG else "",
        "hint": "Set GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN in .env to enable live GitHub data.",
        "hf_org": HF_ORG or "https://huggingface.co/your-org",
    }


def _mock_issues() -> list[dict]:
    return [
        {
            "number": 1,
            "title": "Add benchmark dataset governance rules",
            "state": "open",
            "html_url": "#",
            "labels": ["governance", "documentation"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "number": 2,
            "title": "Integrate patent semantic matching baseline",
            "state": "open",
            "html_url": "#",
            "labels": ["benchmark", "nlp"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    ]


def _mock_org_repositories() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "name": "PatentNLP-Benchmark",
            "full_name": "openKG-field/PatentNLP-Benchmark",
            "description": "Patent NLP benchmark and community profile repository.",
            "language": "Python",
            "stargazers_count": 1,
            "forks_count": 0,
            "open_issues_count": 0,
            "updated_at": now,
            "html_url": "https://github.com/openKG-field/PatentNLP-Benchmark",
        },
        {
            "name": "SciGPT",
            "full_name": "openKG-field/SciGPT",
            "description": "Benchmark baseline and evaluation resources for science-domain tasks.",
            "language": "",
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 0,
            "updated_at": now,
            "html_url": "https://github.com/openKG-field/SciGPT",
        },
        {
            "name": "kgbook-2020",
            "full_name": "openKG-field/kgbook-2020",
            "description": "Knowledge graph engineering demos and materials.",
            "language": "Python",
            "stargazers_count": 13,
            "forks_count": 0,
            "open_issues_count": 0,
            "updated_at": now,
            "html_url": "https://github.com/openKG-field/kgbook-2020",
        },
    ]


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
    if not (GITHUB_OWNER and GITHUB_REPO):
        data = _mock_overview()
        data["repository"] = f"{GITHUB_ORG} (organization)"
        return data

    try:
        repo = _github_get(f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}")
        return {
            "source": "github",
            "repository": repo.get("full_name", f"{GITHUB_OWNER}/{GITHUB_REPO}"),
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
    if not (GITHUB_OWNER and GITHUB_REPO):
        return {"source": "mock", "items": _mock_issues()}

    try:
        raw = _github_get(
            f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues",
            params={"state": state, "per_page": per_page},
        )
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
def org_repositories(
    org: str | None = None,
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict:
    target_org = (org or GITHUB_ORG or "").strip()
    if not target_org:
        return {"source": "mock", "organization": "", "items": _mock_org_repositories()}

    try:
        raw = _github_get(f"/orgs/{target_org}/repos", params={"per_page": per_page, "sort": "updated"})
        items = [_to_repo_brief(item) for item in raw if isinstance(item, dict)]
        return {"source": "github", "organization": target_org, "items": items}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "source": "mock",
            "organization": target_org,
            "error": f"{type(exc).__name__}: {exc}",
            "items": _mock_org_repositories(),
        }
