from __future__ import annotations

from types import SimpleNamespace

from conftest import FakeAuthedClient, _sample_state

from app.intelligence import feedback as feedback_logic
from app.intelligence import service
from app.intelligence.schemas import FeedbackRequest, SuggestionRequest


def _flags():
    return SimpleNamespace(intelligence_enabled=True, learning_enabled=True)


def test_suggestion_returns_up_to_three_results(monkeypatch):
    state = _sample_state()
    state['learning_rules'] = [
        {
            'id': f'rule-{idx}',
            'user_id': 'user-1',
            'normalized_description': f'uber trip {idx}',
            'raw_description_sample': f'UBER TRIP {idx}',
            'transaction_type': 'expense',
            'category_id': 'cat-expense',
            'account_id': 'acc-1',
            'confidence_score': 0.9 - (idx * 0.05),
            'usage_count': 10 - idx,
            'is_active': True,
            'is_auto_apply': False,
        }
        for idx in range(4)
    ]
    client = FakeAuthedClient(state)
    monkeypatch.setattr(service, 'get_settings', _flags)

    result = service.get_transaction_suggestion(client, 'user-1', SuggestionRequest(description='UBER TRIP'))

    assert result['found'] is True
    assert len(result['top_suggestions']) == 3
    assert 'suggestions' in result
    assert 'confidence' in result


def test_suggestion_returns_empty_when_no_rules(monkeypatch):
    state = _sample_state()
    client = FakeAuthedClient(state)
    monkeypatch.setattr(service, 'get_settings', _flags)

    result = service.get_transaction_suggestion(client, 'user-1', SuggestionRequest(description='UBER TRIP'))

    assert result['found'] is False
    assert result['top_suggestions'] == []


def test_feedback_accept_reinforces_rule(monkeypatch):
    state = _sample_state()
    state['learning_rules'].append({
        'id': 'rule-1',
        'user_id': 'user-1',
        'normalized_description': 'uber trip',
        'raw_description_sample': 'UBER TRIP',
        'transaction_type': 'expense',
        'category_id': 'cat-expense',
        'account_id': 'acc-1',
        'confidence_score': 0.5,
        'usage_count': 10,
        'is_active': True,
        'is_auto_apply': False,
    })
    client = FakeAuthedClient(state)
    monkeypatch.setattr(service, 'get_settings', _flags)
    monkeypatch.setattr(service, 'get_user_settings', lambda _client, _user_id: service.DEFAULT_SETTINGS.copy())

    result = service.apply_feedback(
        client,
        'user-1',
        FeedbackRequest(
            input_description='UBER TRIP',
            chosen_category_id='cat-expense',
            chosen_account_id='acc-1',
            chosen_type='expense',
            accepted=True,
        ),
    )

    assert result['success'] is True
    assert result['rule']['confidence_score'] > 0.5
    assert result['rule']['usage_count'] == 11


def test_feedback_corrected_penalizes_previous_rule(monkeypatch):
    state = _sample_state()
    state['learning_rules'].extend([
        {
            'id': 'rule-1',
            'user_id': 'user-1',
            'normalized_description': 'uber trip',
            'raw_description_sample': 'UBER TRIP',
            'transaction_type': 'expense',
            'category_id': 'cat-expense',
            'account_id': 'acc-1',
            'confidence_score': 0.8,
            'usage_count': 12,
            'is_active': True,
            'is_auto_apply': False,
        },
        {
            'id': 'rule-2',
            'user_id': 'user-1',
            'normalized_description': 'taxi',
            'raw_description_sample': 'TAXI',
            'transaction_type': 'expense',
            'category_id': 'cat-expense',
            'account_id': 'acc-1',
            'confidence_score': 0.4,
            'usage_count': 2,
            'is_active': True,
            'is_auto_apply': False,
        },
    ])
    client = FakeAuthedClient(state)
    monkeypatch.setattr(service, 'get_settings', _flags)
    monkeypatch.setattr(service, 'get_user_settings', lambda _client, _user_id: service.DEFAULT_SETTINGS.copy())

    result = service.apply_feedback(
        client,
        'user-1',
        FeedbackRequest(
            input_description='TAXI',
            suggested_rule_id='rule-1',
            suggested_category_id='cat-expense',
            suggested_account_id='acc-1',
            suggested_type='expense',
            chosen_category_id='cat-expense',
            chosen_account_id='acc-1',
            chosen_type='expense',
            accepted=False,
        ),
    )

    penalized = next(rule for rule in state['learning_rules'] if rule['id'] == 'rule-1')
    assert result['success'] is True
    assert penalized['confidence_score'] < 0.8


def test_confidence_never_exceeds_maximum():
    updated = feedback_logic.apply_feedback({'confidence_score': 0.99, 'usage_count': 99}, accepted=True)
    assert updated['confidence_score'] <= 0.99


def test_confidence_never_goes_below_minimum():
    updated = feedback_logic.apply_feedback({'confidence_score': 0.10, 'usage_count': 99}, accepted=False, corrected=True)
    assert updated['confidence_score'] >= 0.10


def test_sql_contains_cluster_key_and_rls_policies():
    sql = open('supabase/intelligence_v1.sql', 'r', encoding='utf-8').read()

    assert 'cluster_key text' in sql
    assert 'enable row level security' in sql.lower()
    assert 'for select using (auth.uid() = user_id)' in sql.lower()
    assert 'for insert with check (auth.uid() = user_id)' in sql.lower()
    assert 'for update using (auth.uid() = user_id) with check (auth.uid() = user_id)' in sql.lower()
    assert 'for delete using (auth.uid() = user_id)' in sql.lower()


def test_intelligence_template_has_governance_actions():
    template = open('templates/pages/intelligence.html', 'r', encoding='utf-8').read()

    assert '/api/intelligence/rules/${ruleId}' in template
    assert '/api/intelligence/rules/${ruleId}/toggle' in template
    assert 'Ainda não há regras aprendidas' in template
