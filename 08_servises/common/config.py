from __future__ import annotations
from pathlib import Path
import yaml


def load_yaml(path: str | Path) -> dict:
    p = Path(path)
    with p.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f'{p} must contain a YAML mapping')
    return data
