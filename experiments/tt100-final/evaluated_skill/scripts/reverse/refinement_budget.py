"""Durable, output-bound refinement limits; reserve before expensive work."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

DEFAULT_POLICY = {'max_proposals': 2, 'refinement_seconds': 120.0, 'max_non_improvements': 2}
SCHEMA = 'checkpoint-refinement-budget/v1'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def budget_path(output: Path) -> Path:
    # A caller changing --state-dir cannot change the output's budget identity.
    return output.parent / ('.' + output.name + '.refinement.json')


def initial_policy(args) -> dict:
    policy = {
        'max_proposals': getattr(args, 'max_cost_proposals', None),
        'refinement_seconds': getattr(args, 'refinement_seconds', None),
        'max_non_improvements': getattr(args, 'max_non_improvements', None),
    }
    policy = {key: DEFAULT_POLICY[key] if value is None else value for key, value in policy.items()}
    if (not isinstance(policy['max_proposals'], int) or isinstance(policy['max_proposals'], bool)
            or not 0 <= policy['max_proposals'] <= 2
            or not isinstance(policy['max_non_improvements'], int)
            or isinstance(policy['max_non_improvements'], bool)
            or not 1 <= policy['max_non_improvements'] <= 2
            or not isinstance(policy['refinement_seconds'], (int, float))
            or isinstance(policy['refinement_seconds'], bool)
            or not math.isfinite(policy['refinement_seconds'])
            or not 0 <= policy['refinement_seconds'] <= 120):
        raise ValueError('Refinement limits may only reduce defaults: two proposals, 120 seconds, two non-improvements')
    return policy


def explicit_policy_matches(args, policy: dict) -> bool:
    return all(getattr(args, argument, None) is None or getattr(args, argument) == policy[key]
               for argument, key in (('max_cost_proposals', 'max_proposals'),
                                     ('refinement_seconds', 'refinement_seconds'),
                                     ('max_non_improvements', 'max_non_improvements')))


class RefinementBudget:
    def __init__(self, path: Path, anchor: dict, writer, args):
        self.path, self.anchor, self.writer, self.args = path, anchor, writer, args
        self.data = None

    @staticmethod
    def anchor_for(output: Path, receipt: dict, first_path: Path) -> dict:
        return {'output': str(output), 'truth_sha256': receipt['truth_sha256'],
                'first_receipt_path': str(first_path), 'first_receipt_sha256': digest(first_path),
                'first_candidate_sha256': receipt['candidate_sha256'],
                'refinement_policy': receipt['refinement_policy'],
                'refinement_published_wall_ns': receipt['refinement_published_wall_ns']}

    def create(self, policy: dict, published_wall_ns: int) -> dict:
        if self.path.exists():
            return self.load()
        self.data = {'schema': SCHEMA, 'anchor': self.anchor, 'policy': policy,
                     'published_wall_ns': published_wall_ns,
                     'refinement_deadline_wall_ns': published_wall_ns + round(policy['refinement_seconds'] * 1_000_000_000),
                     'last_seen_wall_ns': published_wall_ns, 'proposals_started': 0,
                     'consecutive_non_improvements': 0, 'inflight': None, 'events': []}
        self.writer(self.path, self.data)
        return self.data

    def load(self) -> dict:
        if not self.path.is_file():
            raise ValueError('Existing checkpoint refinement budget is missing; it cannot be reset by another CLI call')
        value = json.loads(self.path.read_text())
        if not isinstance(value, dict) or value.get('schema') != SCHEMA or value.get('anchor') != self.anchor:
            raise ValueError('Refinement budget identity does not match the first checkpoint')
        policy = value.get('policy', {})
        if (policy != self.anchor['refinement_policy']
                or value.get('published_wall_ns') != self.anchor['refinement_published_wall_ns']):
            raise ValueError('Refinement budget policy or publication time contradicts the first checkpoint')
        # Reuse policy validation without allowing bool-as-int or nonfinite time.
        class Saved:
            max_cost_proposals = policy.get('max_proposals')
            refinement_seconds = policy.get('refinement_seconds')
            max_non_improvements = policy.get('max_non_improvements')
        if set(policy) != set(DEFAULT_POLICY) or initial_policy(Saved()) != policy:
            raise ValueError('Refinement budget policy is malformed')
        if not explicit_policy_matches(self.args, policy):
            raise ValueError('An established refinement policy cannot be changed or reset')
        keys = ('published_wall_ns', 'refinement_deadline_wall_ns', 'last_seen_wall_ns',
                'proposals_started', 'consecutive_non_improvements')
        if any(not isinstance(value.get(key), int) or isinstance(value[key], bool) or value[key] < 0 for key in keys):
            raise ValueError('Refinement budget counters are malformed')
        if (value['refinement_deadline_wall_ns'] != value['published_wall_ns'] + round(policy['refinement_seconds'] * 1_000_000_000)
                or value['last_seen_wall_ns'] < value['published_wall_ns']
                or value['proposals_started'] > policy['max_proposals']
                or value['consecutive_non_improvements'] > value['proposals_started']
                or not isinstance(value.get('events'), list)):
            raise ValueError('Refinement budget counters contradict the frozen policy')
        active = value.get('inflight')
        if active is not None and (not isinstance(active, dict)
                                   or active.get('proposal_id') != value['proposals_started']
                                   or not isinstance(active.get('started_wall_ns'), int)):
            raise ValueError('Refinement budget reservation is malformed')
        if len(value['events']) + int(active is not None) != value['proposals_started']:
            raise ValueError('Refinement budget history is incomplete')
        failures = 0
        for index, event in enumerate(value['events'], 1):
            if (not isinstance(event, dict) or event.get('proposal_id') != index
                    or type(event.get('improved')) is not bool
                    or not isinstance(event.get('status'), str)
                    or type(event.get('started_wall_ns')) is not int
                    or type(event.get('finished_wall_ns')) is not int
                    or event['started_wall_ns'] < value['published_wall_ns']
                    or not isinstance(event.get('incumbent_sha256'), str)
                    or len(event['incumbent_sha256']) != 64):
                raise ValueError('Refinement budget event history is malformed')
            failures = 0 if event['improved'] else failures + 1
        if failures != value['consecutive_non_improvements']:
            raise ValueError('Refinement budget failures contradict its event history')
        if active is not None and (active['started_wall_ns'] < value['published_wall_ns']
                or not isinstance(active.get('incumbent_sha256'), str)
                or len(active['incumbent_sha256']) != 64):
            raise ValueError('Refinement budget reservation is malformed')
        self.data = value
        return value

    def reconcile(self, receipt: dict) -> None:
        active = self.data['inflight']
        if active is None:
            return
        # A completed promotion can survive a crash before budget accounting.
        # Other interrupted reservations count as failed/non-improving attempts.
        promoted = (receipt.get('refinement_proposal_id') == active['proposal_id']
                    and receipt.get('candidate_sha256') != active['incumbent_sha256']
                    and receipt.get('cost') is not None and active['incumbent_cost'] is not None
                    and receipt['cost'] < active['incumbent_cost'])
        self.finish('promoted_recovered' if promoted else 'interrupted', promoted)

    def reserve(self, incumbent: dict, deadline: float) -> tuple[float, str | None]:
        now_ns = time.time_ns()
        data = self.data
        if now_ns < data['last_seen_wall_ns']:
            return deadline, 'wall_clock_regressed'
        if data['inflight'] is not None:
            raise ValueError('Previous refinement reservation was not reconciled')
        if data['proposals_started'] >= data['policy']['max_proposals']:
            return deadline, 'proposal_limit'
        if data['consecutive_non_improvements'] >= data['policy']['max_non_improvements']:
            return deadline, 'non_improvement_limit'
        remaining = (data['refinement_deadline_wall_ns'] - now_ns) / 1_000_000_000
        if remaining <= 0:
            return deadline, 'refinement_time_limit'
        proposal_id = data['proposals_started'] + 1
        data.update(proposals_started=proposal_id, last_seen_wall_ns=now_ns,
                    inflight={'proposal_id': proposal_id, 'started_wall_ns': now_ns,
                              'incumbent_sha256': incumbent['candidate_sha256'],
                              'incumbent_cost': incumbent.get('cost')})
        self.writer(self.path, data)
        return min(deadline, time.monotonic() + remaining), None

    def finish(self, status: str, improved: bool) -> None:
        active = self.data['inflight']
        if active is None:
            return
        now_ns = time.time_ns()
        self.data['events'].append({**active, 'status': status, 'improved': bool(improved),
                                    'finished_wall_ns': now_ns,
                                    'seconds': max(0, now_ns - active['started_wall_ns']) / 1_000_000_000})
        self.data.update(inflight=None, last_seen_wall_ns=max(now_ns, self.data['last_seen_wall_ns']),
                         consecutive_non_improvements=0 if improved else self.data['consecutive_non_improvements'] + 1)
        self.writer(self.path, self.data)

    def report(self) -> dict:
        now_ns = time.time_ns()
        return {'path': str(self.path), 'policy': self.data['policy'],
                'proposals_started': self.data['proposals_started'],
                'consecutive_non_improvements': self.data['consecutive_non_improvements'],
                'refinement_seconds_remaining': max(0, (self.data['refinement_deadline_wall_ns'] - now_ns) / 1_000_000_000),
                'refinement_deadline_wall_ns': self.data['refinement_deadline_wall_ns'],
                'inflight': self.data['inflight'], 'events': self.data['events']}
