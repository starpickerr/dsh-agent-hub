"""Task contracts run without Core or external accounts."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/agent-hub/backend'))
from domain.service import AgentHubService
from domain.store import AgentHubStore


@pytest.fixture
def hub(tmp_path):
    service = AgentHubService(AgentHubStore(tmp_path / 'hub.db'))
    provider = service.upsert_provider({'providerLocalId': 'codex-cli', 'enabled': True})
    return service, provider


def create(hub, request_id='create-1'):
    service, provider = hub
    return service.create_task(payload={'title': 'Build', 'goal': 'Ship the change', 'participants': [
        {'providerConfigId': provider['providerConfigId'], 'displayName': 'Codex'},
        {'providerConfigId': provider['providerConfigId'], 'displayName': 'Codex'},
    ]}, request_id=request_id)


def test_create_is_idempotent_and_reopens(hub):
    task = create(hub)
    assert create(hub)['taskId'] == task['taskId']
    reopened = AgentHubService(AgentHubStore(hub[0].store.db_path))
    assert reopened.get_task(task['taskId']) == task
    assert len({p['participantId'] for p in task['participants']}) == 2


def test_revision_conflict_preserves_persona(hub):
    svc, _ = hub
    task = create(hub)
    pid = task['participants'][0]['participantId']
    changed = svc.update_participant(task['taskId'], pid, {'persona': 'Review security'}, task['revision'], 'edit')
    with pytest.raises(ValueError, match='revision'):
        svc.update_participant(task['taskId'], pid, {'persona': 'stale'}, task['revision'], 'stale')
    assert changed['participants'][0]['persona'] == 'Review security'


def test_message_and_persona_use_stable_participant_ids(hub):
    svc, _ = hub
    task = create(hub)
    pid = task['participants'][1]['participantId']
    params = dict(task_id=task['taskId'], body='Review edge cases', recipient_ids=[pid], intent='persona',
                  expected_revision=task['revision'], request_id='message')
    updated = svc.post_message(**params)
    assert svc.post_message(**params) == updated
    assert updated['participants'][1]['persona'] == 'Review edge cases'
    assert updated['participants'][0]['persona'] == ''
    assert updated['messages'][-1]['kind'] == 'configuration'
    with pytest.raises(ValueError, match='participant'):
        svc.post_message(task['taskId'], 'hello', ['foreign'], 'message', updated['revision'], 'foreign')


def test_workflow_rejects_cycles_and_foreign_references(hub):
    svc, _ = hub
    task = create(hub)
    pid = task['participants'][0]['participantId']
    for steps in ([{'stepId': 'a', 'title': 'A', 'participantId': pid, 'dependsOn': ['a']}],
                  [{'stepId': 'a', 'title': 'A', 'participantId': 'foreign', 'dependsOn': []}],
                  [{'stepId': 'a', 'title': 'A', 'participantId': pid, 'dependsOn': ['b']},
                   {'stepId': 'b', 'title': 'B', 'participantId': pid, 'dependsOn': ['a']} ]):
        with pytest.raises(ValueError):
            svc.set_workflow(task['taskId'], steps, task['revision'], 'bad')
    assert svc.get_task(task['taskId'])['steps'] == []


def test_claim_waits_for_dependencies_and_keeps_snapshot_and_attempts(hub):
    svc, _ = hub
    task = create(hub)
    pid = task['participants'][0]['participantId']
    task = svc.set_workflow(task['taskId'], [
        {'stepId': 'a', 'title': 'Plan', 'participantId': pid, 'dependsOn': []},
        {'stepId': 'b', 'title': 'Review', 'participantId': pid, 'dependsOn': ['a']}], task['revision'], 'flow')
    with pytest.raises(ValueError, match='depend'):
        svc.claim_step(task['taskId'], 'b')
    claim = svc.claim_step(task['taskId'], 'a')
    with pytest.raises(ValueError):
        svc.claim_step(task['taskId'], 'a')
    task = svc.sync_attempt(task['taskId'], 'a', claim['executionId'], {'status': 'succeeded', 'reply': 'Plan done'})
    task2 = svc.sync_attempt(task['taskId'], 'a', claim['executionId'], {'status': 'succeeded', 'reply': 'Plan done'})
    assert len(task2['messages']) == len(task['messages']) == 1
    claim2 = svc.claim_step(task['taskId'], 'b')
    assert 'Plan done' in claim2['goal']
    svc.sync_attempt(task['taskId'], 'b', claim2['executionId'], {'status': 'failed', 'error': {'message': 'retry'}})
    with pytest.raises(ValueError, match='retry'):
        svc.claim_step(task['taskId'], 'b')
    claim3 = svc.claim_step(task['taskId'], 'b', retry=True)
    assert claim3['executionId'] != claim2['executionId']
    assert len(svc.get_task(task['taskId'])['steps'][1]['attempts']) == 2
    assert claim['snapshot']['persona'] == ''


def test_upgrade_keeps_legacy_records(hub):
    svc, provider = hub
    svc.map_external_run({'executionId': 'old', 'providerConfigId': provider['providerConfigId'], 'status': 'succeeded'})
    create(hub)
    reopened = AgentHubStore(svc.store.db_path)
    assert reopened.get_run('old')['status'] == 'succeeded'
    assert reopened.get_provider(provider['providerConfigId'])['enabled']


def test_cancelled_step_can_be_explicitly_retried(hub):
    svc, _ = hub
    task = create(hub)
    task = svc.set_workflow(task['taskId'], [{'stepId': 'a', 'title': 'Run',
        'participantId': task['participants'][0]['participantId']}], task['revision'], 'flow')
    first = svc.claim_step(task['taskId'], 'a')
    svc.mark_cancelled(task['taskId'])
    svc.sync_attempt(task['taskId'], 'a', first['executionId'], {'status': 'cancelled'})
    with pytest.raises(ValueError):
        svc.claim_step(task['taskId'], 'a')
    second = svc.claim_step(task['taskId'], 'a', retry=True)
    assert second['executionId'] != first['executionId']
    assert not svc.get_task(task['taskId'])['cancelled']


def test_add_participant_and_choose_coordinator(hub):
    svc, provider = hub
    task = create(hub)
    task = svc.add_participant(task['taskId'], {'providerConfigId': provider['providerConfigId']}, task['revision'], 'add')
    pid = task['participants'][-1]['participantId']
    task = svc.set_coordinator(task['taskId'], pid, task['revision'], 'coordinator')
    assert task['coordinatorParticipantId'] == pid
    with pytest.raises(ValueError, match='participant'):
        svc.set_coordinator(task['taskId'], 'foreign', task['revision'], 'foreign')


def test_request_id_is_required_for_mutations(hub):
    with pytest.raises(ValueError, match='request_id'):
        create(hub, request_id='')


def test_invalid_workflow_entry_is_a_validation_error(hub):
    svc, _ = hub
    task = create(hub)
    with pytest.raises(ValueError):
        svc.set_workflow(task['taskId'], [None], task['revision'], 'invalid')
