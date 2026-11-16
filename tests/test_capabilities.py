import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from feishu_grok_bot.live import Capabilities, NoRedirect, load
from feishu_grok_bot.core import reply_argv
from test_bridge import CFG


class CapabilityTests(unittest.TestCase):
    def cap(self):
        return Capabilities({'live_enabled':True,'cli_path':'/synthetic/never-executed-cli','cli_profile':CFG.cli_profile},True)

    def test_send_transport_stdin_and_timeout(self):
        class Done:
            stdout=json.dumps({'ok':True,'data':{'message_id':'om_SYNTHETIC_OUT','chat_id':CFG.chat}}).encode()
        with patch.dict('os.environ',{'HOME':'/synthetic/home'},clear=True), patch('feishu_grok_bot.live.subprocess.run',return_value=Done()) as mock:
            self.cap().send(reply_argv('om_SYNTHETIC', profile=CFG.cli_profile),'synthetic body')
        a,k=mock.call_args
        self.assertNotIn('synthetic body',a[0]);self.assertEqual(k['input'],b'synthetic body')
        self.assertEqual(k['timeout'],30);self.assertNotIn('FEISHU_ROUTINE_AUTHORIZATION',k['env'])

    def test_stop_transport_exact_scope(self):
        class Done:returncode=0
        with patch.dict('os.environ',{'HOME':'/synthetic/home'},clear=True), patch('feishu_grok_bot.live.subprocess.run',return_value=Done()) as mock:
            self.assertEqual(self.cap().stop_bus(CFG),0)
        argv=mock.call_args.args[0]
        self.assertEqual(argv[argv.index('--app-id')+1],CFG.app)
        self.assertNotIn('--all',argv)

    def test_webhook_mock_no_secret_output(self):
        class Dummy:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
        with patch.dict('os.environ',{'FEISHU_ROUTINE_WEBHOOK_URL':'https://api2.cursor.sh/automations/webhook/SYNTHETIC',
                                     'FEISHU_ROUTINE_AUTHORIZATION':'Bearer SYNTHETIC_ONLY'}):
            with patch('feishu_grok_bot.live.build_opener') as builder:
                builder.return_value.open.return_value=Dummy()
                self.assertEqual(self.cap().post({'text':'synthetic'}),200)
                req=builder.return_value.open.call_args.args[0]
                self.assertEqual(req.method,'POST')
                self.assertEqual(json.loads(req.data),{'text':'synthetic'})
                self.assertEqual(builder.return_value.open.call_count,1)

    def test_webhook_failure_no_retry(self):
        with patch.dict('os.environ',{'FEISHU_ROUTINE_WEBHOOK_URL':'https://api2.cursor.sh/automations/webhook/SYNTHETIC',
                                     'FEISHU_ROUTINE_AUTHORIZATION':'Bearer SYNTHETIC_ONLY'}):
            with patch('feishu_grok_bot.live.build_opener') as builder:
                builder.return_value.open.side_effect=TimeoutError()
                with self.assertRaises(TimeoutError):self.cap().post({})
                self.assertEqual(builder.return_value.open.call_count,1)

    def test_webhook_redirect_disabled(self):self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_webhook_invalid_mapping_never_opens(self):
        cases=[('http://example.invalid/','Bearer synthetic'),
               ('https://example.invalid/','Bearer synthetic'),
               ('https://api2.cursor.sh/automations/webhook/SYNTHETIC?x=1','Bearer synthetic'),
               ('https://api2.cursor.sh/automations/webhook/SYNTHETIC','Bearer synthetic\nInjected:1')]
        for url,auth in cases:
            with patch.dict('os.environ',{'FEISHU_ROUTINE_WEBHOOK_URL':url,'FEISHU_ROUTINE_AUTHORIZATION':auth}):
                with patch('feishu_grok_bot.live.build_opener') as builder:
                    with self.assertRaises(ValueError):self.cap().post({})
                    builder.assert_not_called()

    def test_config_public_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config';p.write_text('{}');p.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'config_must_be_private'):load(p)

    def test_relative_cli_rejected(self):
        with self.assertRaisesRegex(ValueError,'cli_must_be_absolute'):
            Capabilities({'live_enabled':True,'cli_path':'relative'},True)
