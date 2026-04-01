from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError

from app.core.config import get_settings
from app.inteligencia import feedback as feedback_logic
from app.inteligencia.matcher import build_cluster_key, normalize_description, rank_rules
from app.inteligencia.schemas import (
    FeedbackRequest,
    IntelligenceSettingsPayload,
    SuggestionRequest,
)

DEFAULT_SETTINGS = IntelligenceSettingsPayload().model_dump()
MISSING_TABLE_CODES = {"42P01", "PGRST205"}
PROFILE_STALE_AFTER = timedelta(hours=24)
PLANNED_SETTINGS_FIELDS = {"learn_from_imported_transactions"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _setting(settings, name: str, default):
    if isinstance(settings, dict):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _extract_api_error_payload(exc: APIError) -> dict:
    payload = getattr(exc, "args", [None])[0]
    return payload if isinstance(payload, dict) else {}


def _is_missing_relation(exc: APIError) -> bool:
    payload = _extract_api_error_payload(exc)
    if payload.get("code") in MISSING_TABLE_CODES:
        return True
    text = str(exc).lower()
    return "does not exist" in text or "could not find the table" in text


def _is_nonfatal_intelligence_error(exc: APIError) -> bool:
    if _is_missing_relation(exc):
        return True

    payload = _extract_api_error_payload(exc)
    code = str(payload.get("code") or "").upper()
    message = str(payload.get("message") or "").lower()
    details = str(payload.get("details") or "").lower()
    hint = str(payload.get("hint") or "").lower()
    text = str(exc).lower()

    if "schema cache" in message or "schema cache" in details or "schema cache" in hint:
        return True
    if "could not find" in message or "could not find" in details:
        return True
    if "not found" in message or "not found" in details:
        return True
    if code.startswith("PGRST20"):
        return True
    return "schema cache" in text or "not found" in text


def _safe_select_list(query_factory):
    try:
        resp = query_factory().execute()
        return resp.data or []
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            logging.warning(f"Intelligence fallback: non-fatal error in select list - {exc}")
            return []
        raise


def _safe_maybe_single(query_factory):
    try:
        resp = query_factory().maybe_single().execute()
        return resp.data if resp else None
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            logging.warning(f"Intelligence fallback: non-fatal error in maybe single - {exc}")
            return None
        raise


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _normalize_reference_month(value: str | datetime | None) -> str | None:
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        source_date = value.date()
    else:
        raw_value = str(value).strip()
        if not raw_value:
            return None
        if len(raw_value) == 7:
            raw_value = f"{raw_value}-01"
        try:
            source_date = datetime.fromisoformat(raw_value.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    return source_date.replace(day=1).isoformat()


def _month_start(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _is_missing_column_error(exc: APIError, column_name: str) -> bool:
    payload = _extract_api_error_payload(exc)
    combined = " ".join([
        str(payload.get("message") or ""),
        str(payload.get("details") or ""),
        str(payload.get("hint") or ""),
        str(exc),
    ]).lower()
    column_name = column_name.lower()
    return column_name in combined and (
        "schema cache" in combined or "could not find" in combined or "column" in combined or "not found" in combined
    )


def _update_alert_flags(client, user_id: str, alert_id: str, flags: dict) -> dict:
    update_with_timestamp = {**flags, "updated_at": _utcnow_iso()}

    try:
        resp = (
            client.table("intelligence_alerts")
            .update(update_with_timestamp)
            .eq("id", alert_id)
            .eq("user_id", user_id)
            .execute()
        )
    except APIError as exc:
        if _is_missing_column_error(exc, "updated_at"):
            logging.warning(
                "Intelligence alerts fallback: updated_at column unavailable; updating alert %s without timestamp",
                alert_id,
            )
            try:
                resp = (
                    client.table("intelligence_alerts")
                    .update(flags)
                    .eq("id", alert_id)
                    .eq("user_id", user_id)
                    .execute()
                )
            except APIError as retry_exc:
                if _is_nonfatal_intelligence_error(retry_exc):
                    return {"success": False}
                raise
        elif _is_nonfatal_intelligence_error(exc):
            return {"success": False}
        else:
            raise

    updated = len(resp.data or []) > 0
    return {"success": updated}


def _is_profile_stale(profile: dict | None) -> bool:
    if not profile:
        return True
    updated_at = _parse_datetime(profile.get("updated_at"))
    if not updated_at:
        return True
    return datetime.now(timezone.utc) - updated_at > PROFILE_STALE_AFTER


def _hydrate_rule(rule: dict) -> dict:
    hydrated = dict(rule)
    source = hydrated.get("raw_description_sample") or hydrated.get("normalized_description") or ""
    hydrated["normalized_description"] = normalize_description(
        hydrated.get("normalized_description") or source
    )
    hydrated["cluster_key"] = hydrated.get("cluster_key") or build_cluster_key(source)
    return hydrated


def _apply_rule_update(client, rule_id: str, user_id: str, update: dict) -> dict | None:
    try:
        resp = (
            client.table("transaction_learning_rules")
            .update(update)
            .eq("id", rule_id)
            .eq("user_id", user_id)
            .select("*")
            .execute()
        )
        data = resp.data or []
        return _hydrate_rule(data[0]) if data else None
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            return None
        raise


def _fetch_rule_by_id(client, user_id: str, rule_id: str | None) -> dict | None:
    if not rule_id:
        return None
    return _safe_maybe_single(
        lambda: client.table("transaction_learning_rules")
        .select("*")
        .eq("id", rule_id)
        .eq("user_id", user_id)
    )


def get_user_settings(client, user_id: str) -> dict:
    record = _safe_maybe_single(
        lambda: client.table("intelligence_settings").select("*").eq("user_id", user_id)
    )
    return {**DEFAULT_SETTINGS, **(record or {})}


def save_user_settings(client, user_id: str, payload: IntelligenceSettingsPayload) -> dict:
    data = payload.model_dump()
    for field_name in PLANNED_SETTINGS_FIELDS:
        if field_name in data:
            logging.warning(
                "Intelligence settings notice: %s is stored for forward compatibility but has no backend effect yet",
                field_name,
            )
    record = {
        **data,
        "user_id": user_id,
        "updated_at": _utcnow_iso(),
    }
    try:
        resp = client.table("intelligence_settings").upsert(record).execute()
        saved = (resp.data or [{}])[0]
        return {**DEFAULT_SETTINGS, **saved}
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            logging.warning(f"Intelligence fallback: failed to save settings - {exc}")
            return {**DEFAULT_SETTINGS, **data}
        raise


def list_rules(client, user_id: str) -> list[dict]:
    rows = _safe_select_list(
        lambda: client.table("transaction_learning_rules")
        .select("*")
        .eq("user_id", user_id)
        .order("confidence_score", desc=True)
    )
    return [_hydrate_rule(row) for row in rows]


def _generate_explanation(_client, _user_id: str, rule: dict, _normalized_desc: str) -> list[str]:
    explanations = []
    usage = int(rule.get("usage_count") or 0)
    if usage > 0:
        explanations.append(f"Baseado em {usage} lancamentos semelhantes")

    last_used = rule.get("last_used_at")
    if last_used:
        try:
            last_dt = datetime.fromisoformat(str(last_used).replace("Z", "+00:00"))
            days_since = max((datetime.now(timezone.utc) - last_dt).days, 0)
            if days_since == 0:
                explanations.append("Usado hoje")
            elif days_since == 1:
                explanations.append("Usado ontem")
            elif days_since < 7:
                explanations.append(f"Usado ha {days_since} dias")
        except ValueError:
            pass

    cluster_key = rule.get("cluster_key")
    if cluster_key and cluster_key != "unknown":
        explanations.append(f"Grupo {cluster_key}")

    return explanations or ["Baseado em historico de uso"]


def _select_candidate_rules(normalized: str, cluster_key: str, rules: list[dict], threshold: float) -> list[dict]:
    exact_matches = []
    cluster_matches = []
    fallback_rules = []

    for rule in rules:
        if not rule.get("is_active", True):
            continue
        hydrated = _hydrate_rule(rule)
        rule_cluster = hydrated.get("cluster_key") or "unknown"

        if hydrated.get("normalized_description") == normalized:
            exact_matches.append(hydrated)
        elif cluster_key != "unknown" and rule_cluster == cluster_key:
            cluster_matches.append(hydrated)
        else:
            fallback_rules.append(hydrated)

    ranked = rank_rules(normalized, exact_matches + cluster_matches + fallback_rules, min_similarity=threshold)
    return ranked[:3]


def get_transaction_suggestion(client, user_id: str, payload: SuggestionRequest) -> dict:
    settings = get_settings()
    normalized = normalize_description(payload.description)
    cluster_key = build_cluster_key(payload.description)

    if not _setting(settings, "intelligence_enabled", True):
        return {
            "found": False,
            "disabled": True,
            "reason": "Intelligence features are globally disabled",
            "normalized_description": normalized,
            "cluster_key": cluster_key,
            "top_suggestions": [],
        }

    user_settings = get_user_settings(client, user_id)
    if not _setting(user_settings, "enable_suggestions", True) or len(normalized) < 3:
        return {
            "found": False,
            "settings": user_settings,
            "normalized_description": normalized,
            "cluster_key": cluster_key,
            "top_suggestions": [],
        }

    threshold = float(_setting(user_settings, "description_similarity_threshold", 0.50) or 0.50)
    ranked = _select_candidate_rules(normalized, cluster_key, list_rules(client, user_id), threshold)
    top_suggestions = []
    for item in ranked[:3]:
        rule = _hydrate_rule(item["rule"])
        explanations = _generate_explanation(client, user_id, rule, normalized)
        top_suggestions.append({
            "rule_id": rule.get("id"),
            "confidence": item["score"],
            "similarity": item["similarity"],
            "category_id": rule.get("category_id"),
            "account_id": rule.get("account_id"),
            "card_id": rule.get("card_id"),
            "transaction_type": rule.get("transaction_type"),
            "cluster_key": rule.get("cluster_key"),
            "explanation": "; ".join(explanations),
            "based_on": explanations,
        })

    min_suggest = float(_setting(user_settings, "min_confidence_to_suggest", 0.60) or 0.60)
    best = top_suggestions[0] if top_suggestions else None
    if not best or float(best["confidence"]) < min_suggest:
        return {
            "found": False,
            "settings": user_settings,
            "normalized_description": normalized,
            "cluster_key": cluster_key,
            "top_suggestions": top_suggestions,
        }

    best_confidence = float(best["confidence"])
    return {
        "found": True,
        "confidence": round(best_confidence, 2),
        "auto_fill": bool(
            _setting(user_settings, "enable_auto_fill", False)
            and best_confidence >= float(_setting(user_settings, "min_confidence_to_autofill", 0.90) or 0.90)
        ),
        "suggestions": {
            "category_id": best.get("category_id"),
            "account_id": best.get("account_id"),
            "card_id": best.get("card_id"),
            "transaction_type": best.get("transaction_type"),
            "rule_id": best.get("rule_id"),
        },
        "explanation": best.get("explanation"),
        "rule": best,
        "settings": user_settings,
        "normalized_description": normalized,
        "cluster_key": cluster_key,
        "top_suggestions": top_suggestions,
    }


def _build_rule_record(user_id: str, payload: FeedbackRequest, confidence_score: float) -> dict:
    return {
        "user_id": user_id,
        "normalized_description": normalize_description(payload.input_description),
        "raw_description_sample": payload.input_description,
        "cluster_key": build_cluster_key(payload.input_description),
        "category_id": payload.chosen_category_id,
        "account_id": payload.chosen_account_id,
        "card_id": payload.chosen_card_id,
        "transaction_type": payload.chosen_type,
        "source_type": "manual",
        "confidence_score": round(confidence_score, 2),
        "usage_count": 1,
        "is_active": True,
        "is_auto_apply": False,
        "last_used_at": _utcnow_iso(),
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
    }


def _upsert_rule_from_feedback(client, user_id: str, payload: FeedbackRequest) -> dict | None:
    normalized = normalize_description(payload.input_description)
    if len(normalized) < 3:
        return None

    existing = _safe_maybe_single(
        lambda: client.table("transaction_learning_rules")
        .select("*")
        .eq("user_id", user_id)
        .eq("normalized_description", normalized)
    )

    if existing:
        corrected = bool(payload.suggested_rule_id and not payload.accepted)
        hydrated_existing = _hydrate_rule(existing)
        if corrected and payload.suggested_rule_id == existing.get("id"):
            updated = dict(hydrated_existing)
            updated["usage_count"] = int(updated.get("usage_count") or 0) + 1
        else:
            updated = feedback_logic.reinforce_rule(
                hydrated_existing,
                boost=0.03 if payload.accepted else 0.02,
            )
        update = {
            "raw_description_sample": payload.input_description,
            "cluster_key": build_cluster_key(payload.input_description),
            "category_id": payload.chosen_category_id,
            "account_id": payload.chosen_account_id,
            "card_id": payload.chosen_card_id,
            "transaction_type": payload.chosen_type,
            "usage_count": updated["usage_count"],
            "confidence_score": updated["confidence_score"],
            "last_used_at": _utcnow_iso(),
            "updated_at": _utcnow_iso(),
            "is_active": True,
        }
        return _apply_rule_update(client, existing["id"], user_id, update)

    record = _build_rule_record(
        user_id,
        payload,
        confidence_score=0.65 if payload.accepted else 0.58,
    )
    try:
        resp = client.table("transaction_learning_rules").insert(record).execute()
        data = resp.data or []
        return _hydrate_rule(data[0]) if data else None
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            return None
        raise


def _penalize_suggested_rule(client, user_id: str, payload: FeedbackRequest) -> dict | None:
    if payload.accepted or not payload.suggested_rule_id:
        return None

    existing = _fetch_rule_by_id(client, user_id, payload.suggested_rule_id)
    if not existing:
        return None

    corrected = any([
        payload.suggested_category_id != payload.chosen_category_id,
        payload.suggested_account_id != payload.chosen_account_id,
        payload.suggested_card_id != payload.chosen_card_id,
        payload.suggested_type != payload.chosen_type,
    ])
    penalized = feedback_logic.apply_feedback(_hydrate_rule(existing), accepted=False, corrected=corrected)
    if not penalized:
        return None

    update = {
        "confidence_score": penalized["confidence_score"],
        "updated_at": _utcnow_iso(),
    }
    return _apply_rule_update(client, existing["id"], user_id, update)


def apply_feedback(client, user_id: str, payload: FeedbackRequest) -> dict:
    settings = get_settings()
    if not _setting(settings, "learning_enabled", True):
        return {
            "success": False,
            "reason": "Learning features are globally disabled",
        }

    user_settings = get_user_settings(client, user_id)
    if not _setting(user_settings, "learn_from_manual_edits", True):
        return {
            "success": False,
            "reason": "Learning from manual edits is disabled",
            "normalized_description": normalize_description(payload.input_description),
            "cluster_key": build_cluster_key(payload.input_description),
        }

    normalized = normalize_description(payload.input_description)
    record = {
        "user_id": user_id,
        "transaction_id": payload.transaction_id,
        "input_description": payload.input_description,
        "normalized_description": normalized,
        "suggested_category_id": payload.suggested_category_id,
        "chosen_category_id": payload.chosen_category_id,
        "suggested_account_id": payload.suggested_account_id,
        "chosen_account_id": payload.chosen_account_id,
        "suggested_card_id": payload.suggested_card_id,
        "chosen_card_id": payload.chosen_card_id,
        "suggested_type": payload.suggested_type,
        "chosen_type": payload.chosen_type,
        "accepted": payload.accepted,
        "confidence_at_time": payload.confidence_at_time,
        "created_at": _utcnow_iso(),
    }
    try:
        client.table("transaction_learning_feedback").insert(record).execute()
    except APIError as exc:
        if not _is_nonfatal_intelligence_error(exc):
            raise

    penalized_rule = _penalize_suggested_rule(client, user_id, payload)
    chosen_rule = _upsert_rule_from_feedback(client, user_id, payload)
    return {
        "success": True,
        "rule": chosen_rule,
        "penalized_rule": penalized_rule,
        "normalized_description": normalized,
        "cluster_key": build_cluster_key(payload.input_description),
    }


def update_rule(client, user_id: str, rule_id: str, payload: dict) -> dict:
    allowed_fields = {
        "category_id", "account_id", "card_id", "transaction_type",
        "is_active", "is_auto_apply", "normalized_description"
    }
    update_data = {k: v for k, v in payload.items() if k in allowed_fields}
    if not update_data:
        return {"success": False, "reason": "No valid fields to update"}

    if "normalized_description" in update_data:
        update_data["normalized_description"] = normalize_description(update_data["normalized_description"])
        update_data["cluster_key"] = build_cluster_key(update_data["normalized_description"])

    update_data["updated_at"] = _utcnow_iso()
    rule = _apply_rule_update(client, rule_id, user_id, update_data)
    return {"success": bool(rule), "rule": rule}


def delete_rule(client, user_id: str, rule_id: str) -> dict:
    try:
        resp = (
            client.table("transaction_learning_rules")
            .delete()
            .eq("id", rule_id)
            .eq("user_id", user_id)
            .execute()
        )
        deleted = len(resp.data or []) > 0
        return {"success": deleted}
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            logging.warning(f"Intelligence fallback: failed to delete rule - {exc}")
            return {"success": False}
        raise


def toggle_rule_active(client, user_id: str, rule_id: str) -> dict:
    rule = _fetch_rule_by_id(client, user_id, rule_id)
    if not rule:
        return {"success": False, "reason": "Rule not found"}

    new_active = not rule.get("is_active", True)
    update_data = {"is_active": new_active, "updated_at": _utcnow_iso()}
    updated_rule = _apply_rule_update(client, rule_id, user_id, update_data)
    return {"success": bool(updated_rule), "rule": updated_rule}


# User Profile + Alert Engine functions

def get_user_profile(client, user_id: str) -> dict | None:
    """Get user's consolidated behavior profile."""
    profile = _safe_maybe_single(
        lambda: client.table("user_behavior_profile")
        .select("*")
        .eq("user_id", user_id)
    )
    if profile and not _is_profile_stale(profile):
        return profile

    if profile:
        logging.warning("Intelligence profile rebuild: stale profile detected for user %s", user_id)

    try:
        rebuilt = build_and_store_user_profile(client, user_id)
        return rebuilt or profile
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            logging.warning(f"Intelligence fallback: user profile not available - {exc}")
            return profile
        raise


def build_and_store_user_profile(client, user_id: str) -> dict | None:
    """Build user behavior profile from transaction history and store it."""
    from app.intelligence.profile import build_user_behavior_profile

    transactions = _safe_select_list(
        lambda: client.table("transactions")
        .select("date, amount, type, category_id, account_id, card_id")
        .eq("user_id", user_id)
        .order("date", desc=True)
    )

    if not transactions:
        return None

    profile_data = build_user_behavior_profile(transactions)
    record = {
        **profile_data,
        "user_id": user_id,
        "updated_at": _utcnow_iso(),
    }

    try:
        resp = client.table("user_behavior_profile").upsert(record).execute()
        return (resp.data or [None])[0]
    except APIError as exc:
        if _is_nonfatal_intelligence_error(exc):
            logging.warning(f"Intelligence fallback: failed to store user profile - {exc}")
            return profile_data
        raise


def generate_and_store_alerts(client, user_id: str) -> list[dict]:
    """Generate intelligent alerts based on user behavior and store them."""
    from app.intelligence.alerts import generate_intelligence_alerts

    current_month_dt = _month_start()
    current_month = current_month_dt.date().isoformat()

    current_month_transactions = _safe_select_list(
        lambda: client.table("transactions")
        .select("id, date, amount, type, category_id, account_id, card_id, description")
        .eq("user_id", user_id)
        .gte("date", current_month)
        .order("date", desc=True)
    )

    prev_month_date = current_month_dt
    if prev_month_date.month == 1:
        prev_month_date = prev_month_date.replace(year=prev_month_date.year - 1, month=12)
    else:
        prev_month_date = prev_month_date.replace(month=prev_month_date.month - 1)
    prev_month = prev_month_date.date().isoformat()
    previous_month_transactions = _safe_select_list(
        lambda: client.table("transactions")
        .select("id, date, amount, type, category_id, account_id, card_id, description")
        .eq("user_id", user_id)
        .gte("date", prev_month)
        .lt("date", current_month)
        .order("date", desc=True)
    )

    user_profile = get_user_profile(client, user_id)
    cards = _safe_select_list(
        lambda: client.table("cards")
        .select("id, name, limit_amount, credit_limit")
        .eq("user_id", user_id)
    )
    card_usage_totals: dict[str, float] = {}
    for tx in current_month_transactions:
        card_id = tx.get("card_id")
        if not card_id or tx.get("type") != "expense":
            continue
        card_usage_totals[card_id] = card_usage_totals.get(card_id, 0.0) + abs(float(tx.get("amount") or 0))

    cards_usage = []
    for card in cards:
        limit_value = float(card.get("limit_amount") or card.get("credit_limit") or 0)
        cards_usage.append({
            "card_id": card.get("id"),
            "used": round(card_usage_totals.get(card.get("id"), 0.0), 2),
            "limit": round(limit_value, 2),
            "name": card.get("name"),
        })

    alerts_data = generate_intelligence_alerts(
        current_month_transactions=current_month_transactions,
        previous_month_transactions=previous_month_transactions,
        user_profile=user_profile,
        cards_usage=cards_usage,
        reference_month=current_month,
    )

    stored_alerts = []
    for alert in alerts_data:
        reference_month = _normalize_reference_month(alert.get("reference_month") or current_month)
        dedupe_query = (
            client.table("intelligence_alerts")
            .select("id")
            .eq("user_id", user_id)
            .eq("alert_type", alert["alert_type"])
            .eq("reference_month", reference_month)
        )
        if alert.get("category_id"):
            dedupe_query = dedupe_query.eq("category_id", alert["category_id"])
        if alert.get("transaction_id"):
            dedupe_query = dedupe_query.eq("transaction_id", alert["transaction_id"])
        if alert.get("card_id"):
            dedupe_query = dedupe_query.eq("card_id", alert["card_id"])

        existing = _safe_select_list(
            lambda: dedupe_query
        )

        if existing:
            continue

        record = {
            **alert,
            "user_id": user_id,
            "reference_month": reference_month,
            "created_at": _utcnow_iso(),
        }

        try:
            resp = client.table("intelligence_alerts").insert(record).execute()
            stored = (resp.data or [None])[0]
            if stored:
                stored_alerts.append(stored)
        except APIError as exc:
            if not _is_nonfatal_intelligence_error(exc):
                raise

    return stored_alerts


def list_user_alerts(client, user_id: str, include_read: bool = True, limit: int = 50) -> dict:
    """Get user's intelligence alerts with summary."""
    query = (
        client.table("intelligence_alerts")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
    )

    if not include_read:
        query = query.eq("is_read", False)

    alerts = _safe_select_list(lambda: query)
    total = len(alerts)
    unread = len([a for a in alerts if not a.get("is_read", False)])
    critical = len([a for a in alerts if a.get("severity") == "critical"])

    return {
        "total": total,
        "unread": unread,
        "critical": critical,
        "items": alerts,
    }


def mark_alert_read(client, user_id: str, alert_id: str) -> dict:
    """Mark an alert as read."""
    return _update_alert_flags(client, user_id, alert_id, {"is_read": True})


def mark_alert_as_read(client, user_id: str, alert_id: str) -> dict:
    """Backward-compatible alias for marking an alert as read."""
    return mark_alert_read(client, user_id, alert_id)


def dismiss_alert(client, user_id: str, alert_id: str) -> dict:
    """Dismiss an alert."""
    return _update_alert_flags(client, user_id, alert_id, {"is_dismissed": True})


def cleanup_expired_alerts(client) -> dict:
    """Delete dismissed alerts whose real expires_at timestamp has already passed."""
    try:
        resp = (
            client.table("intelligence_alerts")
            .delete()
            .eq("is_dismissed", True)
            .lt("expires_at", _utcnow_iso())
            .execute()
        )
        deleted_count = len(resp.data or [])
        return {"success": True, "deleted_count": deleted_count}
    except APIError as exc:
        if _is_missing_column_error(exc, "expires_at"):
            logging.warning(
                "Intelligence alerts fallback: cleanup_expired_alerts skipped because expires_at column is unavailable"
            )
            return {"success": False, "deleted_count": 0, "reason": "expires_at_unavailable"}
        if _is_nonfatal_intelligence_error(exc):
            return {"success": False, "deleted_count": 0, "error": str(exc)}
        raise
