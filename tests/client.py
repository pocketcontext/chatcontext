#!/usr/bin/env python3
"""Portable client invariants without network or private data."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cc', Path(__file__).resolve().parents[1] / 'skills/chatcontext/scripts/cc.py')
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {'url': 'https://chat.example.com', 'email': 'visitor@example.net', 'password': None}

    def test_origin_and_credentials(self):
        for url in ('http://remote.example.com', 'https://user:password@example.com', 'https://chat.example.com?token=x', 'https://chat.example.com#x'):
            with patch.dict(os.environ, {'CHATCONTEXT_URL': url, 'CHATCONTEXT_USER_EMAIL': 'a@example.com'}):
                with self.assertRaises(cc.Fail):
                    cc.config()

    def test_password_identity_is_checked(self):
        with patch.object(cc, 'send', return_value=(200, {'token': 'secret', 'record': {'id': 'useraccount0001', 'collectionName': 'users', 'email': 'wrong@example.com'}})), patch.object(cc, 'save_session') as save:
            with self.assertRaises(cc.Fail):
                cc.login({**self.cfg, 'password': 'password'})
            save.assert_not_called()

    def test_email_request_and_exchange(self):
        with patch.object(cc, 'oauth_send', return_value=(200, {'otpId': 'challenge'})) as send, patch.object(cc, 'say'):
            self.assertIsNone(cc.email_login(self.cfg))
            self.assertEqual(send.call_args.args[2:], ('/api/collections/users/request-otp', {'email': self.cfg['email']}))
        auth = {'token': 'app-token', 'record': {'id': 'useraccount0001', 'collectionName': 'users', 'email': self.cfg['email']}}
        with patch.object(cc, 'oauth_send', return_value=(200, auth)) as send, patch('getpass.getpass', return_value='12345678'), patch.object(cc, 'save_session'):
            session = cc.email_login(self.cfg, 'challenge')
            self.assertEqual(session['method'], 'email')
            self.assertEqual(send.call_args.args[3], {'otpId': 'challenge', 'password': '12345678'})

    def test_sync_never_writes_or_acknowledges(self):
        with patch.object(cc, 'must', return_value={'columns': ['seq', 'action'], 'rows': [[8, 'create'], [12, 'update']], 'truncated': False}) as call:
            result = cc.sync(self.cfg, 4, 2)
            self.assertEqual(result['next_cursor'], 12)
            self.assertTrue(result['page_full'])
            self.assertEqual(len(call.call_args_list), 1)
            self.assertEqual(call.call_args.args[2], '/api/context/query')
        with patch.object(cc, 'must', return_value={'truncated': True}):
            with self.assertRaises(cc.Fail):
                cc.sync(self.cfg, 4, 2)

    def test_invalid_sync_never_contacts_server(self):
        with patch.object(cc, 'must') as call:
            for after, limit in ((-1, 1), (0, 101), (0, 0)):
                with self.assertRaises(cc.Fail):
                    cc.sync(self.cfg, after, limit)
            call.assert_not_called()

    def test_ack_is_explicit_and_skips_existing(self):
        one, two = 'message00000001', 'message00000002'
        with patch.object(cc, 'self_id', return_value='useraccount0001'), patch.object(cc, 'sql_rows', return_value=[{'message': one}]), patch.object(cc, 'must') as call:
            cc.acknowledge(self.cfg, [one, two, one])
            requests = call.call_args.args[3]['requests']
            self.assertEqual(requests, [{'method': 'POST', 'url': '/api/collections/read_receipts/records', 'body': {'message': two}}])

    def test_download_never_overwrites_or_accepts_wrong_hash(self):
        row = {'id': 'attachment00001', 'original': 'file.txt', 'sha256': cc.hashlib.sha256(b'original').hexdigest()}
        with tempfile.TemporaryDirectory() as tmp, patch.object(cc, 'sql_rows', return_value=[row]), patch.object(cc, 'must', return_value={'token': 'protected-token'}), patch.object(cc, 'binary_request', return_value=b'original'):
            target = Path(tmp) / 'file'
            cc.download(self.cfg, row['id'], target)
            self.assertEqual(target.read_bytes(), b'original')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                cc.download(self.cfg, row['id'], target)
            with patch.object(cc, 'binary_request', return_value=b'corrupted'):
                with self.assertRaises(cc.Fail):
                    cc.download(self.cfg, row['id'], Path(tmp) / 'bad')
                self.assertFalse((Path(tmp) / 'bad').exists())

    def test_protected_download_uses_only_file_token(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'original'
        with patch.object(cc, 'must'), patch.object(cc, 'load_session', return_value={'token': 'ordinary-token'}), patch.object(cc.opener, 'open', return_value=Response()) as opened:
            cc.binary_request(self.cfg, 'GET', '/api/files/attachments/a/file?token=file-token')
            request = opened.call_args.args[0]
            self.assertFalse(request.has_header('Authorization'))
            self.assertIn('token=file-token', request.full_url)

    def test_revision_and_batch_reject_before_network(self):
        with patch.dict(os.environ, {'CHATCONTEXT_URL': 'https://chat.example.com', 'CHATCONTEXT_USER_EMAIL': 'a@example.com'}), patch.object(cc, 'call') as call:
            for args in (['update', 'messages', 'message00000001', '{"body":"bad"}'], ['create', 'users', '{}'], ['batch', '[{"method":"POST","url":"/api/collections/users/records","body":{}}]']):
                with self.assertRaises(cc.Fail):
                    cc.run(cc.parse(args))
            call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
