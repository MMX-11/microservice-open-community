import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="llm-service", version="0.2.0")

BASE_URL = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").rstrip("/")
API_KEY = os.getenv("OPENAI_COMPATIBLE_API_KEY", "").strip()
DEFAULT_MODEL = os.getenv("OPENAI_COMPATIBLE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
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


def _mock_reply(messages: list[Message]) -> str:
    user_texts = [m.content for m in messages if m.role == "user"]
    latest = user_texts[-1] if user_texts else ""
    if "评测" in latest or "benchmark" in latest.lower():
        return "建议先选择任务、定义参考答案，再用统一格式提交预测结果进行可重复评测。"
    if "数据集" in latest or "dataset" in latest.lower():
        return "建议为每个数据集补齐来源、许可证、版本、切分方式和基线结果。"
    return f"已收到你的请求：{latest[:120]}。这是 mock 响应，配置 API Key 后可切换为真实模型。"


def _call_remote_chat(payload: ChatRequest) -> dict:
    url = f"{BASE_URL}{CHAT_PATH}"
    body = json.dumps(
        {
            "model": payload.model or DEFAULT_MODEL,
            "messages": [m.model_dump() for m in payload.messages],
            "temperature": payload.temperature,
            "max_tokens": payload.max_tokens,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "llm-service",
        "provider": "openai-compatible" if BASE_URL and API_KEY else "mock",
        "configured": bool(BASE_URL and API_KEY),
        "model": DEFAULT_MODEL,
    }


@app.post("/chat")
def chat(payload: ChatRequest) -> dict:
    if BASE_URL and API_KEY:
        try:
            remote = _call_remote_chat(payload)
            text = ""
            choices = remote.get("choices", [])
            if choices and isinstance(choices, list):
                text = choices[0].get("message", {}).get("content", "")
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


