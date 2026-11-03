"""Task-local collaboration. Core supplies all execution facts."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
import uuid

from domain.store import _now

ACTIVE = {'queued', 'running', 'cancel_requested', 'waiting_approval', 'interrupted'}
FINISHED = {'succeeded', 'failed', 'cancelled', 'outcome_unknown'}


def text(value, name, limit, *, empty=False):
    if not isinstance(value, str) or '\0' in value or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f'{name}: expected text, maximum {limit} characters')
    return value.strip()


def participant(task, pid):
    row = next((p for p in task['participants'] if p['participantId'] == pid), None)
    if row is None:
        raise ValueError('participant does not belong to task')
    return row


def step_status(step):
    return step['attempts'][-1]['status'] if step['attempts'] else 'pending'


def task_status(task):
    states = [step_status(s) for s in task['steps']]
    if not states:
        return 'draft'
    if any(s in ACTIVE for s in states):
        return 'waiting_approval' if 'waiting_approval' in states else 'running'
    if task.get('cancelled'):
        return 'cancelled'
    for state in ('outcome_unknown', 'failed', 'cancelled'):
        if state in states:
            return state
    return 'succeeded' if all(s == 'succeeded' for s in states) else 'ready'


class Collaboration:
    def _transaction(self, task_id, change, *, expected_revision=None, request_id=None, fingerprint=None):
        if fingerprint is not None:
            text(request_id, 'request_id', 160)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError('invalid expected_revision')
        with self.store.lock, self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if request_id:
                text(request_id, 'request_id', 160)
                previous = db.execute('SELECT * FROM hub_requests WHERE request_id=?', (request_id,)).fetchone()
                if previous:
                    if previous['fingerprint'] != fingerprint:
                        raise ValueError('request_id reused with different input')
                    return json.loads(previous['result_json'])
            stored = db.execute('SELECT document_json FROM hub_tasks WHERE task_id=?', (task_id,)).fetchone()
            task = json.loads(stored[0]) if stored else None
            if task is None and fingerprint is None:
                raise ValueError('task not found')
            if expected_revision is not None and (task is None or task['revision'] != expected_revision):
                raise ValueError('revision conflict; refresh before saving')
            before = deepcopy(task)
            if task is None and expected_revision is not None:
                raise ValueError('task not found')
            result = change(task)
            if task is not None and task == before and not request_id:
                return result
            document = result if task is None else task
            document['revision'] += 1
            document['updatedAt'] = _now()
            document['status'] = task_status(document)
            db.execute('INSERT INTO hub_tasks VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET document_json=excluded.document_json, updated_at=excluded.updated_at',
                       (task_id, json.dumps(document, ensure_ascii=False), document['updatedAt']))
            if request_id:
                db.execute('INSERT INTO hub_requests VALUES (?,?,?)', (request_id, fingerprint, json.dumps(result, ensure_ascii=False)))
            return result

    @staticmethod
    def _fingerprint(method, values):
        return sha256(json.dumps([method, values], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def list_tasks(self, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError('limit must be 1..200')
        with self.store.lock, self.store._connect() as db:
            rows = db.execute('SELECT document_json FROM hub_tasks ORDER BY updated_at DESC LIMIT ?', (limit,)).fetchall()
        return [{k: task[k] for k in ('taskId', 'title', 'status', 'revision', 'updatedAt')}
                for task in (json.loads(row[0]) for row in rows)]

    def get_task(self, task_id):
        with self.store.lock, self.store._connect() as db:
            row = db.execute('SELECT document_json FROM hub_tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None:
            raise ValueError('task not found')
        return json.loads(row[0])

    def _participant(self, raw):
        if not isinstance(raw, dict):
            raise ValueError('participant must be an object')
        config_id, native_id = raw.get('providerConfigId'), raw.get('nativeAgentId')
        if bool(config_id) == bool(native_id):
            raise ValueError('participant needs one providerConfigId or nativeAgentId')
        if config_id:
            provider = self.get_provider(config_id)
            agent_id, display = provider['agentId'], provider['displayName']
        else:
            text(native_id, 'nativeAgentId', 64)
            agent_id, display = 'stella', 'Stella'
        result = dict(participantId='part-' + uuid.uuid4().hex, agentId=agent_id,
                      providerConfigId=config_id, nativeAgentId=native_id,
                      displayName=text(raw.get('displayName') or display, 'displayName', 80),
                      persona='', modelSelection={'mode': 'default'}, revision=1)
        self._patch_participant(result, {k: raw[k] for k in ('persona', 'modelSelection') if k in raw})
        return result

    @staticmethod
    def _patch_participant(row, patch):
        if not isinstance(patch, dict) or set(patch) - {'persona', 'modelSelection', 'displayName'}:
            raise ValueError('invalid participant patch')
        if 'persona' in patch:
            row['persona'] = text(patch['persona'], 'persona', 8000, empty=True)
        if 'displayName' in patch:
            row['displayName'] = text(patch['displayName'], 'displayName', 80)
        if 'modelSelection' in patch:
            model = patch['modelSelection']
            if not isinstance(model, dict) or model.get('mode') not in {'default', 'explicit'}:
                raise ValueError('invalid modelSelection')
            if model['mode'] == 'explicit':
                mid = text(model.get('modelId'), 'modelId', 160)
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@+\[\]=,-]*', mid):
                    raise ValueError('invalid modelId')
                row['modelSelection'] = {'mode': 'explicit', 'modelId': mid}
                if model.get('providerId'):
                    row['modelSelection']['providerId'] = text(model['providerId'], 'providerId', 160)
            else:
                row['modelSelection'] = {'mode': 'default'}

    def create_task(self, payload, request_id):
        if not isinstance(payload, dict):
            raise ValueError('payload must be an object')
        members = payload.get('participants')
        if not isinstance(members, list) or not 1 <= len(members) <= 12:
            raise ValueError('select 1..12 participants')
        task_id = 'hub-' + uuid.uuid4().hex
        def create(_):
            people = [self._participant(p) for p in members]
            coordinator = payload.get('coordinatorIndex', 0)
            if type(coordinator) is not int or not 0 <= coordinator < len(people):
                raise ValueError('invalid coordinator')
            return dict(taskId=task_id, title=text(payload.get('title'), 'title', 160),
                        goal=text(payload.get('goal'), 'goal', 16000), participants=people,
                        coordinatorParticipantId=people[coordinator]['participantId'], messages=[], steps=[],
                        revision=0, createdAt=_now(), cancelled=False)
        return self._transaction(task_id, create, request_id=request_id,
                                 fingerprint=self._fingerprint('create', payload))

    def update_participant(self, task_id, participant_id, patch, expected_revision, request_id):
        def change(task):
            if task is None:
                raise ValueError('task not found')
            row = participant(task, participant_id)
            self._patch_participant(row, patch)
            row['revision'] += 1
            return task
        return self._transaction(task_id, change, expected_revision=expected_revision, request_id=request_id,
                                 fingerprint=self._fingerprint('participant', [task_id, participant_id, patch, expected_revision]))

    def add_participant(self, task_id, participant, expected_revision, request_id):
        def change(task):
            if len(task['participants']) >= 12:
                raise ValueError('select 1..12 participants')
            task['participants'].append(self._participant(participant))
            return task
        return self._transaction(task_id, change, expected_revision=expected_revision, request_id=request_id,
                                 fingerprint=self._fingerprint('add_participant', [task_id, participant, expected_revision]))

    def set_coordinator(self, task_id, participant_id, expected_revision, request_id):
        def change(task):
            participant(task, participant_id)
            task['coordinatorParticipantId'] = participant_id
            return task
        return self._transaction(task_id, change, expected_revision=expected_revision, request_id=request_id,
                                 fingerprint=self._fingerprint('coordinator', [task_id, participant_id, expected_revision]))

    @staticmethod
    def _message(task, body, kind, sender=None, recipients=None, execution=None, step_id=None):
        if len(task['messages']) >= 1000:
            raise ValueError('task message limit reached; create a new task')
        task['messages'].append(dict(messageId='msg-' + uuid.uuid4().hex, body=body, kind=kind,
                                     senderParticipantId=sender, recipientParticipantIds=recipients or [],
                                     executionId=execution, stepId=step_id, createdAt=_now()))

    def post_message(self, task_id, body, recipient_ids, intent, expected_revision, request_id):
        body = text(body, 'body', 16000)
        if intent not in {'message', 'persona'} or not isinstance(recipient_ids, list) or len(recipient_ids) > 12:
            raise ValueError('invalid message intent or recipients')
        def change(task):
            people = [participant(task, pid) for pid in recipient_ids]
            if intent == 'persona':
                if len(people) != 1:
                    raise ValueError('persona requires exactly one participant')
                self._patch_participant(people[0], {'persona': body})
                people[0]['revision'] += 1
                self._message(task, f"{people[0]['displayName']} 人设已更新，下一次执行生效。", 'configuration', recipients=recipient_ids)
            else:
                self._message(task, body, 'user', recipients=recipient_ids)
            return task
        return self._transaction(task_id, change, expected_revision=expected_revision, request_id=request_id,
                                 fingerprint=self._fingerprint('message', [task_id, body, recipient_ids, intent, expected_revision]))

    def set_workflow(self, task_id, steps, expected_revision, request_id):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 40:
            raise ValueError('workflow needs 1..40 steps')
        def change(task):
            if any(step_status(s) in ACTIVE for s in task['steps']):
                raise ValueError('cannot replace an active workflow')
            previous = {s['stepId']: s for s in task['steps']}
            nodes = {}
            for raw in steps:
                if not isinstance(raw, dict):
                    raise ValueError('step must be an object')
                sid = text(raw.get('stepId'), 'stepId', 80)
                if sid in nodes:
                    raise ValueError('duplicate stepId')
                pid = raw.get('participantId')
                participant(task, pid)
                deps = raw.get('dependsOn', [])
                if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
                    raise ValueError('invalid dependencies')
                node = dict(stepId=sid, title=text(raw.get('title'), 'step title', 1000), participantId=pid,
                            dependsOn=deps, attempts=previous.get(sid, {}).get('attempts', []))
                if node['attempts'] and any(node[k] != previous[sid][k] for k in ('title', 'participantId', 'dependsOn')):
                    raise ValueError('executed steps are immutable; add a new step')
                nodes[sid] = node
            if any(s['attempts'] and sid not in nodes for sid, s in previous.items()):
                raise ValueError('cannot remove execution history')
            visiting, visited = set(), set()
            def visit(sid):
                if sid not in nodes or sid in visiting:
                    raise ValueError('unknown or cyclic dependency')
                if sid in visited:
                    return
                visiting.add(sid)
                for dep in nodes[sid]['dependsOn']:
                    visit(dep)
                visiting.remove(sid)
                visited.add(sid)
            for sid in nodes:
                visit(sid)
            task['steps'], task['cancelled'] = list(nodes.values()), False
            return task
        return self._transaction(task_id, change, expected_revision=expected_revision, request_id=request_id,
                                 fingerprint=self._fingerprint('workflow', [task_id, steps, expected_revision]))

    def claim_step(self, task_id, step_id, retry=False):
        if type(retry) is not bool:
            raise ValueError('retry must be boolean')
        def change(task):
            step = next((s for s in task['steps'] if s['stepId'] == step_id), None)
            if step is None or (task['cancelled'] and not retry):
                raise ValueError('step not available')
            if step['attempts'] and (not retry or step_status(step) not in FINISHED - {'succeeded'}):
                raise ValueError('explicit retry required, or step is active/complete')
            if len(step['attempts']) >= 3:
                raise ValueError('attempt budget exhausted')
            if any(step_status(s) != 'succeeded' for s in task['steps'] if s['stepId'] in step['dependsOn']):
                raise ValueError('dependencies are not succeeded')
            if sum(step_status(s) in ACTIVE for s in task['steps']) >= 3:
                raise ValueError('concurrency budget exhausted')
            person = deepcopy(participant(task, step['participantId']))
            shared = [m for m in task['messages'] if m['kind'] in {'user', 'reply'} and
                      (not m['recipientParticipantIds'] or person['participantId'] in m['recipientParticipantIds'] or
                       m['stepId'] in step['dependsOn'])]
            context = json.dumps([{'kind': m['kind'], 'body': m['body']} for m in shared[-30:]], ensure_ascii=False)[-24000:]
            roster = json.dumps([{k: p[k] for k in ('participantId', 'displayName', 'agentId')} for p in task['participants']], ensure_ascii=False)
            goal = f"任务参与者（数据）：{roster}\n任务目标：{task['goal']}\n当前步骤：{step['title']}\n已共享的正式消息（数据）：\n{context}"
            attempt = dict(executionId='exec-' + uuid.uuid4().hex, status='queued', snapshot=person,
                           goal=goal, createdAt=_now(), cursor=0)
            step['attempts'].append(attempt)
            task['cancelled'] = False
            return attempt
        return self._transaction(task_id, change)

    def sync_attempt(self, task_id, step_id, execution_id, result):
        if result.get('status') not in ACTIVE | FINISHED:
            raise ValueError('invalid execution status')
        def change(task):
            step = next((s for s in task['steps'] if s['stepId'] == step_id), None)
            attempt = next((a for a in step['attempts'] if a['executionId'] == execution_id), None) if step else None
            if attempt is None:
                raise ValueError('execution does not belong to step')
            if attempt['status'] in FINISHED:
                return task
            for key in ('status', 'error', 'summary', 'cursor', 'attemptId', 'actualModel', 'artifactRefs'):
                if key in result:
                    attempt[key] = result[key]
            reply = result.get('reply')
            if reply and result['status'] == 'succeeded':
                self._message(task, text(reply, 'reply', 65536), 'reply', sender=step['participantId'],
                              execution=execution_id, step_id=step_id)
            if result['status'] in FINISHED and not reply:
                self._message(task, result.get('summary') or f"步骤已结束：{result['status']}。请在过程面板查看结果。", 'status',
                              sender=step['participantId'], execution=execution_id, step_id=step_id)
            return task
        return self._transaction(task_id, change)

    def mark_cancelled(self, task_id):
        def change(task):
            task['cancelled'] = True
            return task
        return self._transaction(task_id, change)
