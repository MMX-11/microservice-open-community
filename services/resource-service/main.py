import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI(title="resource-service", version="0.1.0")

RESOURCE_FILE = Path(os.getenv("RESOURCE_FILE", "/app/resources/catalog.json"))


def _default_catalog() -> dict:
    return {
        "platforms": [],
        "datasets": [],
        "tasks": [],
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "resource-service"}


@app.get("/catalog")
def catalog() -> dict:
    return load_catalog()


@app.get("/catalog/{section}")
def catalog_section(section: str) -> dict:
    data = load_catalog()
    if section not in data:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    return {"section": section, "items": data.get(section)}

