#!/usr/bin/env python3
"""Real SSE connections verify locked domain reads and session revocation."""
import argparse
import json
import queue
import threading
import urllib.request
from integration import server, operator, account, path, PASSWORD


def subscriber(request, token, topics):
    events = queue.Queue()
    def listen():
        try:
            with urllib.request.urlopen(request.base_url+'/api/realtime', timeout=20) as response:
                event, data = '', ''
                for raw in response:
                    line = raw.decode().strip()
                    if line.startswith('event:'): event = line[6:].strip()
                    elif line.startswith('data:'): data = line[5:].strip()
                    elif not line and event:
                        events.put((event, json.loads(data)))
                        event, data = '', ''
        except Exception as error:
            events.put(('error', str(error)))
    threading.Thread(target=listen, daemon=True).start()
    event, data = events.get(timeout=5)
    assert event == 'PB_CONNECT', (event, data)
    subscription = {'clientId': data['clientId'], 'subscriptions': topics}
    request('POST', '/api/realtime', subscription, token, expected=204)
    return events, subscription


def empty(events):
    try: raise AssertionError(('Forbidden realtime delivery', events.get(timeout=.5)))
    except queue.Empty: pass


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--binary', required=True); args = parser.parse_args()
    with server(args.binary) as request:
        op = operator(request)
        team, tt = account(request, op, 'subscriber@example.test', True)
        author, at = account(request, op, 'author@example.test', True)
        peer, pt = account(request, op, 'peer@example.test', True)
        visitor, vt = account(request, op, 'visitor@example.test')
        create = lambda table, body, token: request('POST', path(table), body, token)
        support = create('conversations', {'kind':'support', 'title':'Support'}, vt)
        private = create('conversations', {'kind':'private_channel', 'title':'Private', 'participants':[peer['id']]}, at)
        dm = create('conversations', {'kind':'dm', 'title':'DM', 'participants':[peer['id']]}, at)
        # Explicit record subscriptions test viewRule; wildcards test listRule.
        topics = [name+'/*' for name in ['conversations','messages','memberships','attachments','reactions','read_receipts','inbox','changes','audit_log','user_directory']]
        topics += ['conversations/'+support['id'], 'conversations/'+private['id'], 'conversations/'+dm['id']]
        team_events, team_sub = subscriber(request, tt, topics+['users/'+team['id']])
        visitor_events, visitor_sub = subscriber(request, vt, topics+['users/'+visitor['id']])
        control, _ = subscriber(request, op, ['messages/*'])
        # A user-specific positive control proves both ordinary subscriptions work.
        for user, events in [(team, team_events), (visitor, visitor_events)]:
            request('PATCH', path('users')+'/'+user['id'], {'name':'Connected subscriber'}, op)
            event, data = events.get(timeout=5)
            assert event.startswith('users/') and data['record']['id']==user['id'], (event,data)
        messages = []
        for conversation, internal, token in [(support,False,at),(support,True,at),(private,False,at),(dm,False,at)]:
            messages.append(create('messages', {'conversation':conversation['id'], 'body':'Synthetic live content', 'internal':internal}, token))
        seen = set()
        for _ in messages:
            event, data = control.get(timeout=5)
            assert event.startswith('messages/'), (event,data)
            seen.add(data['record']['id'])
        assert seen == {message['id'] for message in messages}
        empty(team_events); empty(visitor_events)
        # Even subscriptions to known message IDs cannot bypass locked REST reads.
        team_sub['subscriptions'] += ['messages/'+message['id'] for message in messages]
        visitor_sub['subscriptions'] += ['messages/'+message['id'] for message in messages]
        request('POST','/api/realtime',team_sub,tt,expected=204)
        request('POST','/api/realtime',visitor_sub,vt,expected=204)
        for message in messages:
            request('PATCH',path('messages')+'/'+message['id'],{'expected_revision':message['revision'],'body':'Updated live content'},at)
            event, data = control.get(timeout=5)
            assert event.startswith('messages/') and data['record']['id']==message['id']
        empty(team_events); empty(visitor_events)
        # Existing subscriptions stop delivering on disable, including after
        # re-enabling. Refresh requires a new authenticated session too.
        for disabled in (True, False):
            request('PATCH',path('users')+'/'+team['id'],{'disabled':disabled},op)
            request('PATCH',path('users')+'/'+team['id'],{'name':'Revoked subscriber'},op)
            empty(team_events)
            request('POST','/api/realtime',team_sub,tt,expected=(401,403))
        fresh=request('POST','/api/collections/users/auth-with-password',{'identity':'subscriber@example.test','password':PASSWORD})['token']
        request('POST','/api/realtime',team_sub,fresh,expected=204)
        request('PATCH',path('users')+'/'+team['id'],{'name':'Fresh session'},op)
        event,data=team_events.get(timeout=5)
        assert event.startswith('users/') and data['record']['name']=='Fresh session',(event,data)
    print('PASS: real SSE positive controls, locked domain/private/note events, explicit subscriptions and disabled session revocation')


if __name__ == '__main__': main()
