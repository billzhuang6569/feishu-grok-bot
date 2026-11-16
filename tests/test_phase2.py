import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from feishu_grok_bot.live import cli_environment, Capabilities
from feishu_grok_bot.core import Bridge, classify
from feishu_grok_bot.__main__ import main
from test_bridge import CFG, event, response


class RevisionTests(unittest.TestCase):
    def test_env_allowlist(self):
        locators=dict(HOME='/synthetic/home',LARKSUITE_CLI_CONFIG_DIR='/synthetic/config',LARKSUITE_CLI_DATA_DIR='/synthetic/data')
        with patch.dict(os.environ,dict(locators,FEISHU_ROUTINE_AUTHORIZATION='synthetic',OTHER_TOKEN='synthetic',OTHER_SECRET='synthetic',XDG_DATA_HOME='/irrelevant',PATH='/untrusted'),clear=True):
            self.assertEqual(cli_environment(),dict(locators,PATH='/usr/bin:/bin'))

    def test_missing_home_never_launches(self):
        with patch.dict(os.environ,{},clear=True), patch('feishu_grok_bot.live.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'home_required'):
                Capabilities(dict(live_enabled=True,cli_path='/synthetic/cli',cli_profile=CFG.cli_profile),True).send([], 'body')
            run.assert_not_called()

    def test_invalid_locator(self):
        for value in ('relative','/synthetic\npath'):
            with patch.dict(os.environ,{'HOME':value},clear=True):
                with self.assertRaises(ValueError):cli_environment()

    def test_preview_never_sent(self):
        for key in ('dry_run','dry-run','preview','request'):
            for location in ('top','data','meta'):
                obj=response()
                (obj if location=='top' else obj.setdefault(location,{}))[key]=True
                self.assertEqual(classify(obj,CFG.chat)[0],'unknown')

    def test_nested_success_and_id_conflict(self):
        for envelope in ({'ok':True},{'code':'0'}):
            self.assertEqual(classify(dict(envelope,data={'message':response()['data']}),CFG.chat)[0],'sent')
        obj=response();obj['data']['id']='om_OTHER'
        self.assertEqual(classify(obj,CFG.chat)[0],'unknown')

    def test_cutover_persistent_and_no_replay(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'state'
            b=Bridge(path,CFG,lambda:1000)
            with self.assertRaises(ValueError):b.require_cutover()
            for at in (float('nan'),float('inf'),1001,0):
                with self.assertRaises(ValueError):b.mark_cutover(at)
            b.mark_cutover(1000)
            with self.assertRaises(ValueError):b.mark_cutover(999)
            self.assertEqual(b.accept(event(created_at=999),lambda p:self.fail()),'rejected')
            self.assertEqual(b.accept(event(),lambda p:200),'accepted')
            result=b.reply('om_SYNTHETIC','body',lambda *a:dict(ok=True,data=dict(message_id='om_OUT')))
            self.assertEqual(result['reply_status'],'unknown')
            b.close();b=Bridge(path,CFG,lambda:1000)
            try:
                self.assertEqual(b.require_cutover(),1000)
                b.recover()
                self.assertEqual(b.accept(event(),lambda p:self.fail()),'duplicate')
                self.assertEqual(b.reply('om_SYNTHETIC','again',lambda *a:self.fail())['exit'],4)
            finally:b.close()

    def test_cutover_nonempty_denied(self):
        with tempfile.TemporaryDirectory() as t:
            b=Bridge(Path(t)/'state',CFG,lambda:1000)
            try:
                b.accept(event(),lambda p:200)
                with self.assertRaises(ValueError):b.mark_cutover(1000)
            finally:b.close()

    def test_relative_config_denied(self):
        with patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['context','--config','relative']),3)

    def test_offline_cutover_command(self):
        import json
        from dataclasses import asdict
        with tempfile.TemporaryDirectory() as t:
            config=Path(t)/'private.json'
            state=Path(t)/'state'
            config.write_text(json.dumps(dict(policy={k:v for k,v in asdict(CFG).items() if k != 'cli_profile'},cli_profile=CFG.cli_profile,state_dir=str(state),live_enabled=False)))
            config.chmod(0o600)
            with patch('sys.stdout',new_callable=io.StringIO), patch('feishu_grok_bot.live.subprocess.Popen') as popen:
                args=['mark-cutover','--config',str(config),'--cutover-at','1000']
                self.assertEqual(main(args),0)
                self.assertEqual(main(args),3)
                popen.assert_not_called()
            b=Bridge(state/'bridge.sqlite',CFG)
            try:self.assertEqual(b.require_cutover(),1000)
            finally:b.close()

    def test_receiver_without_gate_never_launches(self):
        from feishu_grok_bot.live import receive
        with tempfile.TemporaryDirectory() as t:
            with patch('feishu_grok_bot.live.signal.signal'), patch('feishu_grok_bot.live.subprocess.Popen') as popen:
                with self.assertRaisesRegex(ValueError,'cutover_gate_required'):
                    receive({'state_dir':t},CFG,object())
                popen.assert_not_called()

    def test_launcher_fixed_paths(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('reply','context'):
            text=(root/'templates'/('trusted-'+name+'.sh')).read_text()
            self.assertIn('--config "$CONFIG"',text)
            self.assertNotIn('dirname',text)
            self.assertNotIn('"$@"',text)
            if name=='reply':self.assertIn('--live --in-reply-to "$2"',text)
