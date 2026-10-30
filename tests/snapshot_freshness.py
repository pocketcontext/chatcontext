#!/usr/bin/env python3
"""Synthetic read-after-write checks for reused filtered SQL snapshots.

The pinned server retains each requester's private snapshot while the source
database is unchanged. These checks prove reuse with X-Context-Snapshot-At
(unchanged on a cache hit), then require messages, channel membership, team
membership, internal notes and receipts to be visible or withdrawn on the very
next read, without leakage to non-members, administrators outside private
conversations, or other visitors.
"""
import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from integration import server, operator, account, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--binary', required=True)
    args = ap.parse_args()
    with server(args.binary) as req:
        timings = []

        def sql(query, token, expected=200):
            request = urllib.request.Request(req.base_url + '/api/context/query', data=json.dumps({'sql': query}).encode(),
                                             headers={'Content-Type': 'application/json', 'Authorization': token}, method='POST')
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    status, raw, headers = response.status, response.read(), response.headers
            except urllib.error.HTTPError as error:
                status, raw, headers = error.code, error.read(), error.headers
            elapsed = time.monotonic() - started
            assert status in (expected if isinstance(expected, tuple) else (expected,)), (query, status, raw.decode())
            if status != 200:
                return None, None
            assert headers['X-Context-Scope'] == 'authorized-snapshot'
            result = json.loads(raw)
            assert not result['truncated']
            timings.append((headers['X-Context-Snapshot-At'], elapsed))
            return [dict(zip(result['columns'], row)) for row in result['rows']], headers['X-Context-Snapshot-At']

        def warm(query, token):
            """Read twice: an unchanged capture time proves the second read reused the snapshot."""
            rows, first = sql(query, token)
            again, second = sql(query, token)
            assert rows == again and first == second, 'expected a reused snapshot for an unchanged source'
            return rows, first

        def fresh(query, token, before):
            """The first read after a commit must come from a new capture."""
            rows, at = sql(query, token)
            assert at != before, 'a committed write must invalidate the reused snapshot'
            return rows

        def ids(rows):
            return {r['id'] for r in rows}

        op = operator(req)
        alice, at = account(req, op, 'alice@example.com', True, True)
        bob, bt = account(req, op, 'bob@example.com', True)
        carol, ct = account(req, op, 'carol@example.com', True)
        visitor, vt = account(req, op, 'visitor@example.com')
        other, ot = account(req, op, 'other@example.com')
        create = lambda t, b, tok: req('POST', path(t), b, tok)
        patch = lambda t, r, b, tok: req('PATCH', path(t) + '/' + r['id'], dict(expected_revision=r['revision'], **b), tok)
        schema = req('GET', '/api/context/schema', token=bt)
        assert schema['permissionModel'] == 'filtered-snapshot' and 'snapshot' not in schema
        assert schema['snapshotLimits']['maxConcurrentPerRequester'] == 0, 'per-requester admission must stay disabled'

        conversations = 'SELECT id FROM conversations ORDER BY id'
        messages = 'SELECT id,internal FROM messages ORDER BY id'
        receipts = 'SELECT id,message,account FROM read_receipts ORDER BY id'
        private = create('conversations', {'kind': 'private_channel', 'title': 'Synthetic private', 'participants': [bob['id']]}, at)

        # A private-channel message is visible at once to members, never to a non-member teammate.
        _, bob_at = warm(messages, bt)
        _, carol_at = warm(messages, ct)
        secret = create('messages', {'conversation': private['id'], 'body': 'Synthetic private history'}, at)
        assert ids(fresh(messages, bt, bob_at)) == {secret['id']}
        assert fresh(messages, ct, carol_at) == []

        # Adding a member exposes existing history on the next read; deactivation withdraws it on the next read.
        _, carol_at = warm(conversations, ct)
        membership = create('memberships', {'conversation': private['id'], 'account': carol['id'], 'active': True}, at)
        assert private['id'] in ids(fresh(conversations, ct, carol_at))
        assert secret['id'] in ids(sql(messages, ct)[0])
        _, carol_at = warm(messages, ct)
        _, bob_at = warm(messages, bt)
        patch('memberships', membership, {'active': False}, at)
        assert fresh(messages, ct, carol_at) == []
        assert private['id'] not in ids(sql(conversations, ct)[0])
        assert ids(fresh(messages, bt, bob_at)) == {secret['id']}, 'removing one member changes nothing for another'

        # A DM between two teammates stays hidden from an administrator on every read, before and after messages.
        _, alice_at = warm(conversations, at)
        dm = create('conversations', {'kind': 'dm', 'title': 'Synthetic DM', 'participants': [carol['id']]}, bt)
        assert dm['id'] not in ids(fresh(conversations, at, alice_at))
        _, alice_at = warm(messages, at)
        _, carol_at = warm(messages, ct)
        dm_message = create('messages', {'conversation': dm['id'], 'body': 'Synthetic direct'}, bt)
        assert dm_message['id'] not in ids(fresh(messages, at, alice_at))
        assert ids(fresh(messages, ct, carol_at)) == {dm_message['id']}

        # Support: the visitor's conversation reaches the team at once, never another visitor; internal notes stay team-only.
        _, bob_at = warm(conversations, bt)
        _, other_at = warm(conversations, ot)
        support = create('conversations', {'kind': 'support', 'title': 'Synthetic help'}, vt)
        assert support['id'] in ids(fresh(conversations, bt, bob_at))
        assert fresh(conversations, ot, other_at) == []
        question = create('messages', {'conversation': support['id'], 'body': 'Synthetic question'}, vt)
        _, visitor_at = warm(messages, vt)
        _, bob_at = warm(messages, bt)
        note = create('messages', {'conversation': support['id'], 'body': 'Synthetic internal note', 'internal': True}, at)
        assert note['id'] in ids(fresh(messages, bt, bob_at))
        assert ids(fresh(messages, vt, visitor_at)) == {question['id']}
        assert sql("SELECT id FROM changes WHERE internal = 1", vt)[0] == []
        answer = create('messages', {'conversation': support['id'], 'body': 'Synthetic answer', 'parent': question['id']}, bt)
        visible = sql(messages, vt)[0]
        assert ids(visible) == {question['id'], answer['id']} and not any(r['internal'] for r in visible)
        assert sql(messages, ot)[0] == []

        # SQL reads never acknowledge; an explicit receipt is visible on the next read for the support participant.
        assert sql(receipts, vt)[0] == []
        _, bob_at = warm(receipts, bt)
        receipt = create('read_receipts', {'message': answer['id']}, vt)
        assert ids(fresh(receipts, bt, bob_at)) == {receipt['id']}
        assert sql(receipts, ot)[0] == []

        # Team-membership revocation withdraws public and support access from the next read.
        _, carol_at = warm(conversations, ct)
        assert support['id'] in ids(sql(conversations, ct)[0])
        role = next(r for r in req('GET', path('team_members'), token=op)['items'] if r['account'] == carol['id'])
        req('DELETE', path('team_members') + '/' + role['id'], token=at, expected=204)
        assert fresh(conversations, ct, carol_at) == []
        assert sql(messages, ct)[0] == []

        # Concurrent reads from several tabs of one account are admitted (no per-requester 429).
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: sql(messages, vt)[0], range(8)))
        assert all(ids(result) == {question['id'], answer['id']} for result in results)

        # Disabling an account is enforced before any cached snapshot can be served.
        warm(messages, vt)
        req('PATCH', path('users') + '/' + visitor['id'], {'disabled': True}, op)
        sql(messages, vt, expected=(401, 403))

        seen, cold, hits = set(), [], []
        for captured, elapsed in timings:
            (hits if captured in seen else cold).append(elapsed)
            seen.add(captured)
        print(f'Snapshot reads: {len(cold)} cold median {sorted(cold)[len(cold) // 2] * 1000:.1f} ms, '
              f'{len(hits)} reused median {sorted(hits)[len(hits) // 2] * 1000:.1f} ms')
    print('Snapshot reuse read-after-write, membership, visitor isolation, internal-note and revocation checks passed')


if __name__ == '__main__':
    main()
