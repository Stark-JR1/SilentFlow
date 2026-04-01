from __future__ import annotations

import math
from datetime import datetime, timezone


def recency_score(last_used_at) -> float:
    if not last_used_at:
        return 0.20

    if isinstance(last_used_at, str):
        try:
            last_used_at = datetime.fromisoformat(last_used_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.20

    now = datetime.now(timezone.utc)
    days = max((now - last_used_at).days, 0)

    # Exponential decay: score = base_score * exp(-days / 30)
    base_score = 1.0
    decay_factor = math.exp(-days / 30.0)  # Half-life of 30 days
    return round(base_score * decay_factor, 2)


def usage_score(usage_count: int | None) -> float:
    usage_count = usage_count or 0
    if usage_count >= 20:
        return 1.00
    if usage_count >= 10:
        return 0.85
    if usage_count >= 5:
        return 0.65
    if usage_count >= 3:
        return 0.50
    return 0.30


def consistency_score(rule: dict) -> float:
    return float(rule.get("confidence_score") or 0.50)


def calculate_rule_score(rule: dict, similarity: float) -> float:
    consistency = consistency_score(rule)
    recency = recency_score(rule.get("last_used_at"))
    usage = usage_score(int(rule.get("usage_count") or 0))
    auto_bonus = 0.05 if rule.get("is_auto_apply") else 0.0

    score = (
        (0.40 * similarity)
        + (0.25 * consistency)
        + (0.20 * recency)
        + (0.15 * usage)
        + auto_bonus
    )
    return round(min(score, 0.99), 4)
