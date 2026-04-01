from __future__ import annotations


def test_put_rule_requires_auth(app_client):
    response = app_client.client.put('/api/intelligence/rules/rule-1', json={'transaction_type': 'expense'})
    assert response.status_code == 401


def test_delete_rule_requires_auth(app_client):
    response = app_client.client.delete('/api/intelligence/rules/rule-1')
    assert response.status_code == 401


def test_toggle_rule_requires_auth(app_client):
    response = app_client.client.patch('/api/intelligence/rules/rule-1/toggle')
    assert response.status_code == 401


def test_put_rule_success(logged_client):
    logged_client.state['learning_rules'].append({
        'id': 'rule-1',
        'user_id': 'user-1',
        'normalized_description': 'uber trip',
        'transaction_type': 'expense',
        'confidence_score': 0.8,
        'usage_count': 5,
        'is_active': True,
        'is_auto_apply': False,
    })

    response = logged_client.client.put('/api/intelligence/rules/rule-1', json={'transaction_type': 'income'})

    assert response.status_code == 200
    assert response.json()['success'] is True
    assert response.json()['rule']['transaction_type'] == 'income'


def test_delete_rule_success(logged_client):
    logged_client.state['learning_rules'].append({
        'id': 'rule-1',
        'user_id': 'user-1',
        'normalized_description': 'uber trip',
        'transaction_type': 'expense',
        'confidence_score': 0.8,
        'usage_count': 5,
        'is_active': True,
        'is_auto_apply': False,
    })

    response = logged_client.client.delete('/api/intelligence/rules/rule-1')

    assert response.status_code == 200
    assert response.json() == {'success': True}


def test_toggle_rule_invalid_id(logged_client):
    response = logged_client.client.patch('/api/intelligence/rules/missing/toggle')

    assert response.status_code == 200
    assert response.json()['success'] is False


def test_cannot_operate_other_users_rule(logged_client):
    logged_client.state['learning_rules'].append({
        'id': 'rule-foreign',
        'user_id': 'user-2',
        'normalized_description': 'uber trip',
        'transaction_type': 'expense',
        'confidence_score': 0.8,
        'usage_count': 5,
        'is_active': True,
        'is_auto_apply': False,
    })

    response = logged_client.client.put('/api/intelligence/rules/rule-foreign', json={'transaction_type': 'income'})

    assert response.status_code == 200
    assert response.json()['success'] is False
