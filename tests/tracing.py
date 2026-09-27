#!/usr/bin/env python3
"""Synthetic opt-in traces preserve private snapshot and requester boundaries."""
import argparse
import contextlib
import json
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

APP = Path(__file__).resolve().parents[1].name


@contextlib.contextmanager
def fixture(binary):
    if APP == 'peoplecontext':
        from integration import Server
        with tempfile.TemporaryDirectory(prefix='people-tracing-') as tmp:
            server = Server(binary, Path(tmp) / 'server')
            try:
                yield server.base, server.request, server.admin, 'agents'
            finally:
                server.stop()
                server.log.close()
    else:
        from integration import server
        with server(binary) as request:
            admin = request('POST', '/api/collections/_superusers/auth-with-password',
                            {'identity': 'admin@example.com', 'password': 'SyntheticAdminPassword123!'})['token']
            yield request.base_url, request, admin, 'users'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with fixture(args.binary) as (base, request, admin, collection):
        password = 'SyntheticTracePassword123!'
        tokens, users = [], []
        for name in ('alice', 'bob'):
            email = name + '@example.test'
            users.append(request('POST', '/api/collections/' + collection + '/records',
                                 {'email': email, 'name': name, 'verified': True,
                                  'password': password, 'passwordConfirm': password}, admin))
            tokens.append(request('POST', '/api/collections/' + collection + '/auth-with-password',
                                  {'identity': email, 'password': password})['token'])
        table = {'accountcontext': 'claims', 'chatcontext': 'conversations', 'peoplecontext': 'employees'}[APP]
        sql = 'SELECT id FROM ' + table + ' LIMIT 5'

        def call(method, path, body=None, token=tokens[0], headers=None, expected=200):
            fields = {'Content-Type': 'application/json', 'Authorization': token, **(headers or {})}
            req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(), fields, method=method)
            try:
                response = urllib.request.urlopen(req, timeout=20)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status, raw, fields = response.status, response.read(), response.headers
            assert status == expected, (path, status, expected)
            return json.loads(raw), fields

        # Trace a real ordinary REST write without recording its sensitive body.
        marker = 'Synthetic private tracing evidence'
        if APP == 'accountcontext':
            body = {'owner': users[0]['id'], 'title': marker, 'currency': 'EUR',
                    'currency_exponent': 2, 'amount_minor': 100, 'status': 'draft'}
        elif APP == 'chatcontext':
            body = {'kind': 'support', 'title': marker}
        else:
            request('POST', '/api/collections/hr_members/records', {'account': users[0]['id']}, admin)
            body = {'name': marker}
        created, headers = call('POST', '/api/collections/' + table + '/records', body,
                                headers={'X-Context-Trace': '1'})
        write_trace, _ = call('GET', '/api/context/traces/' + headers['X-Context-Request-Id'])
        assert write_trace['method'] == 'POST' and write_trace['status'] == 200
        assert marker not in json.dumps(write_trace) and created['id'] not in json.dumps(write_trace)
        call('GET', '/api/context/traces/' + headers['X-Context-Request-Id'], token=tokens[1], expected=404)

        baseline, headers = call('POST', '/api/context/query', {'sql': sql})
        assert 'X-Context-Request-Id' not in headers
        for capture_sql in (False, True):
            fields = {'X-Context-Trace': '1'}
            if capture_sql:
                fields['X-Context-Capture-Sql'] = '1'
            result, headers = call('POST', '/api/context/query', {'sql': sql}, headers=fields)
            assert result == baseline
            identifier = headers['X-Context-Request-Id']
            path = '/api/context/traces/' + identifier
            trace, trace_headers = call('GET', path, headers=fields)
            assert trace_headers['Cache-Control'] == 'no-store'
            assert 'X-Context-Request-Id' not in trace_headers
            assert trace['service'] == APP and trace['user_id'] == users[0]['id']
            assert trace['request_id'] == identifier and trace['status'] == 200
            assert trace.get('sql', '') == (sql if capture_sql else '')
            spans = {span['name'] for span in trace['spans']}
            assert {'snapshot.wait', 'snapshot.build', 'snapshot.reader_init', 'sql.prepare', 'sql.execute', 'sql.scan'} <= spans, spans
            encoded = json.dumps(trace)
            assert marker not in encoded and created['id'] not in encoded
            assert password not in encoded and all(token not in encoded for token in tokens)
            call('GET', path, token=tokens[1], expected=404)
            call('GET', path, token=admin, expected=403)
        # An authenticated invalid query remains traceable without recording its SQL by default.
        _, headers = call('POST', '/api/context/query', {'sql': 'SELECT missing FROM ' + table},
                          headers={'X-Context-Trace': '1'}, expected=400)
        trace, _ = call('GET', '/api/context/traces/' + headers['X-Context-Request-Id'])
        assert trace['status'] == 400 and not trace.get('sql')
        # Disabling the account revokes access to previously captured traces.
        request('PATCH', '/api/collections/' + collection + '/records/' + users[0]['id'], {'disabled': True}, admin)
        call('GET', path, expected=401)
    print('PASS opt-out, SQL opt-in, private retrieval, snapshot phases, failure and revocation')


if __name__ == '__main__':
    main()
