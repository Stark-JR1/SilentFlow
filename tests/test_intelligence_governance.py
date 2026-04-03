from __future__ import annotations

from types import SimpleNamespace

from conftest import FakeAuthedClient, _sample_state
from postgrest.exceptions import APIError

from app.intelligence import service
from app.intelligence.schemas import FeedbackRequest


def _flags():
    return SimpleNamespace(intelligence_enabled=True, learning_enabled=True)


def test_apply_feedback_respects_learn_from_manual_edits_false(monkeypatch):
    state = _sample_state()
    client = FakeAuthedClient(state)
    monkeypatch.setattr(service, 'get_settings', _flags)
    monkeypatch.setattr(
        service,
        'get_user_settings',
        lambda _client, _user_id: {**service.DEFAULT_SETTINGS, 'learn_from_manual_edits': False},
    )

    result = service.apply_feedback(
        client,
        'user-1',
        FeedbackRequest(
            input_description='UBER TRIP',
            chosen_category_id='cat-expense',
            chosen_account_id='acc-1',
            chosen_type='expense',
            accepted=False,
        ),
    )

    assert result['success'] is False
    assert state['learning_feedback'] == []
    assert state['learning_rules'] == []


def test_update_rule_existing():
    state = _sample_state()
    state['learning_rules'].append({
        'id': 'rule-1',
        'user_id': 'user-1',
        'normalized_description': 'uber trip',
        'transaction_type': 'expense',
        'confidence_score': 0.7,
        'usage_count': 3,
        'is_active': True,
        'is_auto_apply': False,
    })
    client = FakeAuthedClient(state)

    result = service.update_rule(client, 'user-1', 'rule-1', {'transaction_type': 'income', 'is_auto_apply': True})

    assert result['success'] is True
    assert result['rule']['transaction_type'] == 'income'
    assert result['rule']['is_auto_apply'] is True


def test_delete_rule_missing_returns_safe_result():
    state = _sample_state()
    client = FakeAuthedClient(state)

    result = service.delete_rule(client, 'user-1', 'missing-rule')

    assert result == {'success': False}


def test_toggle_rule_active_disables_rule():
    state = _sample_state()
    state['learning_rules'].append({
        'id': 'rule-1',
        'user_id': 'user-1',
        'normalized_description': 'uber trip',
        'transaction_type': 'expense',
        'confidence_score': 0.7,
        'usage_count': 3,
        'is_active': True,
        'is_auto_apply': False,
    })
    client = FakeAuthedClient(state)

    result = service.toggle_rule_active(client, 'user-1', 'rule-1')

    assert result['success'] is True
    assert result['rule']['is_active'] is False


def test_safe_select_list_logs_warning(caplog):
    caplog.set_level('WARNING')

    def query_factory():
        raise APIError({'code': 'PGRST205', 'message': 'not found'})

    result = service._safe_select_list(query_factory)

    assert result == []
    assert 'Intelligence fallback: non-fatal error in select list' in caplog.text


def test_safe_maybe_single_logs_warning(caplog):
    caplog.set_level('WARNING')

    def query_factory():
        raise APIError({'code': 'PGRST205', 'message': 'not found'})

    result = service._safe_maybe_single(query_factory)

    assert result is None
    assert 'Intelligence fallback: non-fatal error in maybe single' in caplog.text


def test_save_user_settings_logs_warning(monkeypatch, caplog):
    caplog.set_level('WARNING')

    class FailingTable:
        def upsert(self, _payload):
            raise APIError({'code': 'PGRST205', 'message': 'not found'})

    class FailingClient:
        def table(self, _name):
            return FailingTable()

    payload = service.IntelligenceSettingsPayload(enable_auto_fill=True)
    result = service.save_user_settings(FailingClient(), 'user-1', payload)

    assert result['enable_auto_fill'] is True
    assert 'Intelligence fallback: failed to save settings' in caplog.text
