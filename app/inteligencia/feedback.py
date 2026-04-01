from __future__ import annotations


def reinforce_rule(rule: dict, boost: float = 0.03) -> dict:
    updated = dict(rule)
    updated["usage_count"] = min(int(updated.get("usage_count") or 0) + 1, 999999)
    updated["confidence_score"] = round(
        min(float(updated.get("confidence_score") or 0.50) + boost, 0.99),
        2,
    )
    return updated


def weaken_rule(rule: dict, penalty: float = 0.05) -> dict:
    updated = dict(rule)
    updated["confidence_score"] = round(
        max(float(updated.get("confidence_score") or 0.50) - penalty, 0.10),
        2,
    )
    return updated


def apply_feedback(existing_rule: dict | None, accepted: bool, corrected: bool = False) -> dict | None:
    if not existing_rule:
        return None

    # Anti-learning stupidity: limit confidence boost based on feedback volume
    feedback_count = int(existing_rule.get("usage_count") or 0)
    if feedback_count < 3:
        weight = 0.3  # Low confidence for new rules
    elif feedback_count < 10:
        weight = 0.6  # Medium confidence
    else:
        weight = 1.0  # Full confidence for established rules

    if accepted:
        boost = 0.03 * weight
        return reinforce_rule(existing_rule, boost=boost)

    if corrected:
        penalty = 0.12 * weight  # Increased penalty for corrections
        return weaken_rule(existing_rule, penalty=penalty)

    penalty = 0.05 * weight  # Increased penalty for rejections
    return weaken_rule(existing_rule, penalty=penalty)
