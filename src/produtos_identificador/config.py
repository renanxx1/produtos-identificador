from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path

from .models import CostConfig


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def cost_config_from_env() -> CostConfig:
    values: dict[str, float] = {}
    env_map = {
        "brl_per_vnd": "BRL_PER_VND",
        "import_tax_rate": "IMPORT_TAX_RATE",
        "icms_rate": "ICMS_RATE",
        "ml_fee_rate": "ML_FEE_RATE",
        "payment_fee_rate": "PAYMENT_FEE_RATE",
        "fixed_cost_brl": "FIXED_COST_BRL",
        "target_margin_rate": "TARGET_MARGIN_RATE",
    }
    valid_names = {field.name for field in fields(CostConfig)}
    for name, env_name in env_map.items():
        if name in valid_names and os.getenv(env_name):
            values[name] = float(os.environ[env_name])
    return CostConfig(**values)

