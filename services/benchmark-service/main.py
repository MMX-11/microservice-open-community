import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="benchmark-service", version="0.1.0")

TASK_FILE = Path(os.getenv("TASK_FILE", "/app/benchmarks/tasks.json"))


class EvaluationRequest(BaseModel):
    task_id: str = Field(..., description="Task identifier from tasks.json")
    predictions: list[str]
    references: list[str]
    model_name: str = "custom-model"
    run_name: str = "manual-run"


def _default_tasks() -> dict:
    return {
        "tasks": [
            {
                "id": "patent_classification_zh",
                "name": "Patent Classification",
                "type": "classification",
                "metric": "accuracy",
                "description": "Classify patents into technical categories.",
            },
            {
                "id": "patent_semantic_matching_zh",
                "name": "Patent Semantic Matching",
                "type": "similarity",
                "metric": "token_f1",
                "description": "Measure semantic alignment for patent query-response pairs.",
            },
        ]
    }


def load_tasks() -> dict:
    if TASK_FILE.exists():
        with TASK_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return _default_tasks()


def _tokenize(text: str) -> list[str]:
    return [tok for tok in text.replace(",", " ").split() if tok.strip()]


def _accuracy(predictions: list[str], references: list[str]) -> float:
    if not references:
        return 0.0
    correct = sum(1 for p, r in zip(predictions, references) if p.strip() == r.strip())
    return round(correct / len(references), 4)


def _token_f1(predictions: list[str], references: list[str]) -> float:
    if not references:
        return 0.0
    total = 0.0
    for pred, ref in zip(predictions, references):
        pred_tokens = _tokenize(pred)
        ref_tokens = _tokenize(ref)
        if not pred_tokens and not ref_tokens:
            total += 1.0
            continue
        if not pred_tokens or not ref_tokens:
            continue
        pred_set = set(pred_tokens)
        ref_set = set(ref_tokens)
        inter = len(pred_set & ref_set)
        precision = inter / len(pred_set) if pred_set else 0.0
        recall = inter / len(ref_set) if ref_set else 0.0
        if precision + recall == 0:
            continue
        total += (2 * precision * recall) / (precision + recall)
    return round(total / len(references), 4)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "benchmark-service"}


@app.get("/tasks")
def tasks() -> dict:
    return load_tasks()


@app.post("/run")
def run_eval(payload: EvaluationRequest) -> dict:
    tasks_data = load_tasks()
    task = next((item for item in tasks_data.get("tasks", []) if item.get("id") == payload.task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail=f"Unknown task_id: {payload.task_id}")

    if len(payload.predictions) != len(payload.references):
        raise HTTPException(status_code=400, detail="predictions and references must have the same length")

    task_type = task.get("type")
    if task_type == "classification":
        score = _accuracy(payload.predictions, payload.references)
        metric_name = "accuracy"
    else:
        score = _token_f1(payload.predictions, payload.references)
        metric_name = "token_f1"

    return {
        "task_id": payload.task_id,
        "task_name": task.get("name"),
        "model_name": payload.model_name,
        "run_name": payload.run_name,
        "metric": metric_name,
        "score": score,
        "sample_count": len(payload.references),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/leaderboard")
def leaderboard() -> dict:
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": [
            {"task_id": "patent_classification_zh", "model_name": "baseline-tfidf", "metric": "accuracy", "score": 0.7621},
            {"task_id": "patent_semantic_matching_zh", "model_name": "baseline-sbert", "metric": "token_f1", "score": 0.6834},
        ],
    }

