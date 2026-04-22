import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="llm-service", version="0.2.0")

# Preferred shortcut variables for CLOW (fallback to LOBSTER_* then OPENAI_COMPATIBLE_*).
CLOW_BASE_URL = os.getenv("CLOW_BASE_URL", "").strip().rstrip("/")
CLOW_API_KEY = os.getenv("CLOW_API_KEY", "").strip()
CLOW_MODEL = os.getenv("CLOW_MODEL", "").strip()

# Backward-compatible Lobster shortcut variables.
LOBSTER_BASE_URL = os.getenv("LOBSTER_BASE_URL", "").strip().rstrip("/")
LOBSTER_API_KEY = os.getenv("LOBSTER_API_KEY", "").strip()
LOBSTER_MODEL = os.getenv("LOBSTER_MODEL", "").strip()

OPENAI_BASE_URL = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").strip().rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_COMPATIBLE_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_COMPATIBLE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

BASE_URL = CLOW_BASE_URL or LOBSTER_BASE_URL or OPENAI_BASE_URL
API_KEY = CLOW_API_KEY or LOBSTER_API_KEY or OPENAI_API_KEY
DEFAULT_MODEL = CLOW_MODEL or LOBSTER_MODEL or OPENAI_MODEL
if CLOW_BASE_URL or CLOW_API_KEY or CLOW_MODEL:
    PROVIDER_NAME = "clow"
elif LOBSTER_BASE_URL or LOBSTER_API_KEY or LOBSTER_MODEL:
    PROVIDER_NAME = "lobster"
else:
    PROVIDER_NAME = "openai-compatible"
CHAT_PATH = os.getenv("OPENAI_COMPATIBLE_CHAT_PATH", "/v1/chat/completions").strip() or "/v1/chat/completions"
TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    max_tokens: int = 512


class CommunityGenerateRequest(BaseModel):
    requirements: str = Field(..., min_length=1, description="用户输入的社区生成需求")
    modules_summary: dict = Field(default_factory=dict, description="模块统计信息")
    seed_items: list[dict] = Field(default_factory=list, max_length=200, description="已有社区条目")
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    max_tokens: int = 1400


class CommunityMaintenanceRequest(BaseModel):
    focus: str = Field(default="日常维护巡检", min_length=1, max_length=500)
    modules_summary: dict = Field(default_factory=dict, description="社区模块统计")
    recent_items: list[dict] = Field(default_factory=list, max_length=260, description="最近社区条目")
    recent_blogs: list[dict] = Field(default_factory=list, max_length=120, description="最近博客条目")
    open_issues: list[dict] = Field(default_factory=list, max_length=120, description="Open Issues 快照")
    model: str = DEFAULT_MODEL
    temperature: float = 0.15
    max_tokens: int = 1500


def _mock_reply(messages: list[Message]) -> str:
    user_texts = [m.content for m in messages if m.role == "user"]
    latest = user_texts[-1] if user_texts else ""
    if "评测" in latest or "benchmark" in latest.lower():
        return "建议先选择任务、定义参考答案，再用统一格式提交预测结果进行可重复评测。"
    if "数据集" in latest or "dataset" in latest.lower():
        return "建议为每个数据集补齐来源、许可证、版本、切分方式和基线结果。"
    return f"已收到你的请求：{latest[:120]}。这是 mock 响应，配置 API Key 后可切换为真实模型。"


def _call_remote_chat(model: str, messages: list[dict], temperature: float, max_tokens: int) -> dict:
    url = f"{BASE_URL}{CHAT_PATH}"
    body = json.dumps(
        {
            "model": model or DEFAULT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_chat_text(remote: dict) -> str:
    choices = remote.get("choices", [])
    if choices and isinstance(choices, list):
        return choices[0].get("message", {}).get("content", "") or ""
    return ""


def _seed_items_markdown(seed_items: list[dict]) -> str:
    if not seed_items:
        return "- 暂无现有条目，可先生成基础框架。"
    rows: list[str] = []
    for item in seed_items[:24]:
        title = str(item.get("title", "")).strip() or "未命名"
        module = str(item.get("module", "")).strip() or "未分类"
        summary = str(item.get("summary", "")).strip()
        url = str(item.get("url", "")).strip()
        row = f"- [{module}] {title}"
        if summary:
            row += f"：{summary}"
        if url:
            row += f"（{url}）"
        rows.append(row)
    return "\n".join(rows)


def _mock_community_response(payload: CommunityGenerateRequest) -> str:
    modules = payload.modules_summary.get("by_module", {}) if isinstance(payload.modules_summary, dict) else {}
    lines = [
        "# 文献协作社区草稿",
        "",
        "## 社区标题",
        "文献任务协作社区",
        "",
        "## 社区定位",
        "聚焦文献任务榜、AI 前沿、开源分享、主题论坛四大模块，支持团队持续共建。",
        "",
        "## 模块规划",
    ]
    for key in ["文献任务榜", "AI前沿", "开源分享", "主题论坛"]:
        lines.append(f"- {key}：当前条目 {int(modules.get(key, 0))} 条，建议每周更新。")
    lines.extend(
        [
            "",
            "## 你输入的需求",
            payload.requirements.strip(),
            "",
            "## 下一步建议",
            "1. 先补齐团队主页项目与成果的链接条目。",
            "2. 用 Benchmark Tool 跑一轮基线，更新任务榜。",
            "3. 用 AI 共创助手生成论坛周报与分享草稿。",
        ]
    )
    return "\n".join(lines)


def _build_generate_messages(payload: CommunityGenerateRequest) -> list[dict]:
    modules_summary = json.dumps(payload.modules_summary, ensure_ascii=False, indent=2)
    seed_markdown = _seed_items_markdown(payload.seed_items)
    system_prompt = (
        "你是开源社区建设助手。你要根据已有模块与条目，输出可直接发布的中文社区草稿。"
        "输出使用 Markdown，结构必须包含：社区标题、定位、四大模块（文献任务榜/AI前沿/开源分享/主题论坛）"
        "、团队模块、工具模块、一周更新节奏、下一步行动清单。"
        "要求：内容具体、可执行，不要空话。"
    )
    user_prompt = (
        f"【用户需求】\n{payload.requirements.strip()}\n\n"
        f"【模块统计】\n{modules_summary}\n\n"
        f"【已有条目样例】\n{seed_markdown}\n\n"
        "请据此生成一版“文献领域团队开源社区”首页与运营草稿。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _mock_maintenance_response(payload: CommunityMaintenanceRequest) -> str:
    by_module = payload.modules_summary.get("by_module", {}) if isinstance(payload.modules_summary, dict) else {}
    total_items = int(payload.modules_summary.get("total", 0)) if isinstance(payload.modules_summary, dict) else 0
    open_issues = len(payload.open_issues or [])
    recent_blogs = len(payload.recent_blogs or [])
    lines = [
        "# 社区维护智能体报告",
        "",
        "## 巡检结论",
        f"- 当前社区条目总数：{total_items}",
        f"- 最近博客条目：{recent_blogs}",
        f"- Open Issues：{open_issues}",
        "",
        "## 模块状态",
    ]
    for key in ["文献任务榜", "AI前沿", "开源分享", "主题论坛", "团队模块"]:
        lines.append(f"- {key}：{int(by_module.get(key, 0))} 条")
    lines.extend(
        [
            "",
            "## 建议待办（本周）",
            "1. 清理低质量条目：优先处理摘要过短与失效链接。",
            "2. 补齐团队模块：按“研究方向/项目/成果/动态/合作”更新入口。",
            "3. 发布周报：从本周新增博客中提炼 3 条重点发布到分享栏目。",
            "4. 跟进 Issues：对高优先级 open issue 先给出负责人和截止时间。",
            "",
            f"## 本次关注点\n{payload.focus.strip()}",
        ]
    )
    return "\n".join(lines)


def _build_maintenance_messages(payload: CommunityMaintenanceRequest) -> list[dict]:
    modules_summary = payload.modules_summary if isinstance(payload.modules_summary, dict) else {}
    item_rows = []
    for item in (payload.recent_items or [])[:40]:
        if not isinstance(item, dict):
            continue
        item_rows.append(
            {
                "id": item.get("id"),
                "module": item.get("module"),
                "title": item.get("title"),
                "source": item.get("source"),
                "updated_at": item.get("updated_at"),
                "url": item.get("url"),
            }
        )
    blog_rows = []
    for blog in (payload.recent_blogs or [])[:30]:
        if not isinstance(blog, dict):
            continue
        blog_rows.append(
            {
                "id": blog.get("id"),
                "title": blog.get("title"),
                "author": blog.get("author"),
                "status": blog.get("status"),
                "updated_at": blog.get("updated_at"),
            }
        )
    issue_rows = []
    for issue in (payload.open_issues or [])[:20]:
        if not isinstance(issue, dict):
            continue
        issue_rows.append(
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "updated_at": issue.get("updated_at"),
                "html_url": issue.get("html_url"),
            }
        )

    system_prompt = (
        "你是“开源社区维护智能体”。请根据输入快照输出可直接执行的中文维护报告。"
        "必须包含以下标题："
        "1) 今日巡检结论 "
        "2) 风险告警（按 P0/P1/P2） "
        "3) 维护待办清单（至少 6 条，需给出负责人角色与优先级） "
        "4) 自动化建议 "
        "5) 给管理员的 3 条一句话提醒。"
        "输出使用 Markdown，结论务必具体，不要空话。"
    )
    user_prompt = (
        f"【维护目标】\n{payload.focus.strip()}\n\n"
        f"【模块统计】\n{json.dumps(modules_summary, ensure_ascii=False, indent=2)}\n\n"
        f"【最近社区条目（节选）】\n{json.dumps(item_rows, ensure_ascii=False, indent=2)}\n\n"
        f"【最近博客（节选）】\n{json.dumps(blog_rows, ensure_ascii=False, indent=2)}\n\n"
        f"【Open Issues（节选）】\n{json.dumps(issue_rows, ensure_ascii=False, indent=2)}\n\n"
        "请生成“社区日常维护报告”，并且每条待办尽量可在本周内完成。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "llm-service",
        "provider": PROVIDER_NAME if BASE_URL and API_KEY else "mock",
        "configured": bool(BASE_URL and API_KEY),
        "model": DEFAULT_MODEL,
    }


@app.post("/chat")
def chat(payload: ChatRequest) -> dict:
    if BASE_URL and API_KEY:
        try:
            remote = _call_remote_chat(
                model=payload.model,
                messages=[m.model_dump() for m in payload.messages],
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            )
            text = _extract_chat_text(remote)
            return {
                "source": "remote",
                "model": payload.model,
                "response": text,
                "raw": remote,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {
                "source": "mock",
                "model": payload.model,
                "response": _mock_reply(payload.messages),
                "error": f"{type(exc).__name__}: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    return {
        "source": "mock",
        "model": payload.model,
        "response": _mock_reply(payload.messages),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/generate_community")
def generate_community(payload: CommunityGenerateRequest) -> dict:
    if BASE_URL and API_KEY:
        try:
            remote = _call_remote_chat(
                model=payload.model,
                messages=_build_generate_messages(payload),
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            )
            text = _extract_chat_text(remote).strip()
            if not text:
                text = _mock_community_response(payload)
            return {
                "source": "remote",
                "model": payload.model,
                "community_markdown": text,
                "raw": remote,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {
                "source": "mock",
                "model": payload.model,
                "community_markdown": _mock_community_response(payload),
                "error": f"{type(exc).__name__}: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    return {
        "source": "mock",
        "model": payload.model,
        "community_markdown": _mock_community_response(payload),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/maintain_community")
def maintain_community(payload: CommunityMaintenanceRequest) -> dict:
    if BASE_URL and API_KEY:
        try:
            remote = _call_remote_chat(
                model=payload.model,
                messages=_build_maintenance_messages(payload),
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            )
            text = _extract_chat_text(remote).strip()
            if not text:
                text = _mock_maintenance_response(payload)
            return {
                "source": "remote",
                "model": payload.model,
                "maintenance_markdown": text,
                "raw": remote,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {
                "source": "mock",
                "model": payload.model,
                "maintenance_markdown": _mock_maintenance_response(payload),
                "error": f"{type(exc).__name__}: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    return {
        "source": "mock",
        "model": payload.model,
        "maintenance_markdown": _mock_maintenance_response(payload),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


