def test_intelligence_page_renders(logged_client):
    response = logged_client.client.get("/settings/intelligence")
    assert response.status_code == 200
    assert "Configurações & Aprendizado" in response.text
    assert "Regras aprendidas" in response.text


def test_intelligence_settings_defaults_and_save(logged_client):
    client = logged_client.client

    defaults = client.get("/api/intelligence/settings")
    assert defaults.status_code == 200
    assert defaults.json()["enable_suggestions"] is True
    assert defaults.json()["enable_auto_fill"] is False

    update = client.put(
        "/api/intelligence/settings",
        json={
            "enable_suggestions": True,
            "enable_auto_fill": True,
            "enable_recurrence_detection": True,
            "learn_from_manual_edits": True,
            "learn_from_imported_transactions": False,
            "show_explanations": True,
            "min_confidence_to_suggest": 0.55,
            "min_confidence_to_autofill": 0.88,
            "description_similarity_threshold": 0.7,
            "min_repetitions_for_pattern": 4,
        },
    )
    assert update.status_code == 200
    assert update.json()["enable_auto_fill"] is True
    assert update.json()["min_repetitions_for_pattern"] == 4


def test_intelligence_feedback_creates_rule_and_suggestion(logged_client):
    client = logged_client.client

    feedback = client.post(
        "/api/intelligence/feedback",
        json={
            "input_description": "UBER *TRIP",
            "chosen_category_id": "cat-expense",
            "chosen_account_id": "acc-1",
            "chosen_type": "expense",
            "accepted": False,
        },
    )
    assert feedback.status_code == 201

    suggestion = client.post(
        "/api/intelligence/suggestions/transaction",
        json={"description": "Uber Trip"},
    )
    assert suggestion.status_code == 200
    payload = suggestion.json()
    assert payload["found"] is True
    assert payload["suggestions"]["category_id"] == "cat-expense"
    assert payload["suggestions"]["account_id"] == "acc-1"
    assert payload["suggestions"]["transaction_type"] == "expense"


def test_intelligence_rules_listing_returns_learned_rule(logged_client):
    client = logged_client.client
    client.post(
        "/api/intelligence/feedback",
        json={
            "input_description": "NETFLIX.COM",
            "chosen_category_id": "cat-expense",
            "chosen_account_id": "acc-1",
            "chosen_type": "expense",
            "accepted": True,
        },
    )

    response = client.get("/api/intelligence/rules")
    assert response.status_code == 200
    rules = response.json()
    assert len(rules) >= 1
    assert any(rule["normalized_description"] == "netflix com" for rule in rules)
