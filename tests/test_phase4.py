import json
import tempfile
from pathlib import Path
import unittest
from feishu_grok_bot.core import Bridge as AsyncBridge
from feishu_grok_bot.gate import Gate
from feishu_grok_bot.progress import Progress, card
from test_bridge import CFG, event, response


class Bridge(AsyncBridge):
    """Drive the serialized backend directly for existing state-machine checks.

    Public nonblocking submission/lifecycle is exercised in test_ui_isolation.
    These checks deliberately observe every intermediate acknowledged frame.
    """
    def feedback(self, mid, stage):
        if self.progress is not None and self.gate is not None:
            self.progress.advance(self, mid, stage)


class ProgressTests(unittest.TestCase):
    def run_case(self, behavior='ok', enabled=True):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); gate = Gate(root, lambda:999000000000)
        gate.initialize(); gate.activate('new')
        calls = []
        def call(argv, body):
            resource, method = (('messages','reply') if argv[4] == '+messages-reply' else argv[4:6]); calls.append((resource, method, argv))
            if behavior == 'crash': raise TimeoutError()
            if behavior == 'permission': return {'ok':False,'error':{'code':403}}
            if behavior == '429': return {'ok':False,'error':{'code':429}}
            if behavior == 'unknown': return {}
            if resource == 'reactions': return {'ok':True,'data':{'reaction_id':'synthetic-reaction'}}
            return response()
        progress = Progress({'cli_path':'/synthetic/approved-cli','cli_profile':CFG.cli_profile,'live_enabled':True, 'reaction_enabled':enabled,
                             'progress_card_enabled':enabled},call)
        b = Bridge(root/'state.sqlite',CFG,lambda:1002,gate,'new',progress)
        self.addCleanup(b.close)
        return b, calls, gate

    def test_lifecycle_and_no_content(self):
        b,calls,g = self.run_case()
        self.assertEqual(b.accept(event(),lambda p:200),'accepted')
        self.assertEqual(b.reply('om_SYNTHETIC','private code table',lambda *a:response())['reply_status'],'sent')
        self.assertEqual([x[:2] for x in calls], [('reactions','create'),('messages','reply'),('messages','patch'),('reactions','delete')])
        self.assertNotIn('private code table',json.dumps(calls))
        b.feedback('om_SYNTHETIC','received')
        self.assertEqual(len(calls),4)
        self.assertEqual(b.accept(event(),lambda p:self.fail()),'rejected')

    def test_optional_failures_do_not_change_sent(self):
        for failure in ('permission','429','unknown','crash'):
            with self.subTest(failure=failure):
                b,calls,g=self.run_case(failure)
                b.accept(event(),lambda p:200)
                self.assertEqual(b.reply('om_SYNTHETIC','answer',lambda *a:response())['reply_status'],'sent')
                self.assertEqual(len(calls),2)
                self.assertEqual(b.reply('om_SYNTHETIC','again',lambda *a:self.fail())['exit'],4)

    def test_disabled_fenced_late_and_restart(self):
        b,calls,g=self.run_case(enabled=False)
        b.accept(event(),lambda p:200); self.assertEqual(calls,[])
        b,calls,g=self.run_case('crash')
        b.accept(event(),lambda p:200); b.recover()
        b.feedback('om_SYNTHETIC','returned'); self.assertEqual(len(calls),2)
        g.pause(); g.clock_ns=lambda:1001000000000; g.activate('new')
        b.feedback('om_SYNTHETIC','failed'); self.assertEqual(len(calls),2)
        self.assertEqual(b.reply('om_SYNTHETIC','late',lambda *a:self.fail())['exit'],3)

    def test_whitelist_and_stage_payload(self):
        with self.assertRaises(ValueError): Progress({'reaction_emoji':'invented'},lambda *a:None)
        self.assertLess(len(json.dumps(card('returned')).encode()),1000)

    def test_failed_dispatch_cleanup_and_terminal_order(self):
        b,calls,g=self.run_case()
        self.assertEqual(b.accept(event(),lambda p:429),'unknown')
        self.assertEqual(calls[-1][:2],('reactions','delete'))
        count=len(calls)
        b.feedback('om_SYNTHETIC','returned')
        self.assertEqual(len(calls),count)
        self.assertEqual(b.reply('om_SYNTHETIC','answer',lambda *a:{})['reply_status'],'unknown')

    def test_owner_rejection_and_real_reopen(self):
        b,calls,g=self.run_case('crash')
        self.assertEqual(b.accept(event(sender_open_id='ou_OTHER'),lambda p:self.fail()),'rejected')
        self.assertEqual(calls,[])
        b.accept(event(),lambda p:200)
        path=Path(b.db.execute('PRAGMA database_list').fetchone()[2])
        # A second connection simulates reopening durable state without replay.
        reopened=Bridge(path,CFG,lambda:1002,g,'new',b.progress)
        try:
            reopened.recover(); reopened.feedback('om_SYNTHETIC','returned')
            self.assertEqual(len(calls),2)
        finally: reopened.close()

    def test_success_envelopes_fail_closed(self):
        from feishu_grok_bot.progress import success
        for obj in ({'ok':True,'code':429},{'ok':True,'meta':{'preview':True}}, {'code':False}):
            self.assertFalse(success(obj))
        self.assertTrue(success({'ok':True}))
        self.assertTrue(success({'code':0}))

    def test_absolute_cli_and_shared_environment(self):
        from feishu_grok_bot.live import Capabilities
        from unittest.mock import patch
        b,calls,g=self.run_case()
        settings={'live_enabled':True,'cli_path':'/synthetic/approved-cli',
                  'cli_profile':CFG.cli_profile,'reaction_enabled':True,'progress_card_enabled':True}
        cap=Capabilities(settings,True)
        b.progress=Progress(settings,cap.send)
        class Done:
            stdout=json.dumps(response()).encode()
        with patch.dict('os.environ',{'HOME':'/synthetic/home','POISON':'secret'},clear=True), \
             patch('feishu_grok_bot.live.subprocess.run',return_value=Done()) as run, \
             patch.object(cap, 'ui_send', side_effect=lambda argv, body, cancelled: cap.send(argv, body)):
            b.accept(event(),lambda p:200)
            for args,kw in run.call_args_list:
                self.assertEqual(args[0][0],settings['cli_path'])
                self.assertEqual(kw['env'],{'HOME':'/synthetic/home','PATH':'/usr/bin:/bin'})
                self.assertEqual(args[0][2],CFG.cli_profile)
            card_call=run.call_args_list[1].args[0]
            self.assertIn('+messages-reply',card_call)
            self.assertNotIn('--data',card_call)

    def test_terminal_sent_cannot_reverse(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        b.reply('om_SYNTHETIC','answer',lambda *a:response())
        n=len(calls)
        for stage in ('failed','returned','received','replied'):
            b.feedback('om_SYNTHETIC',stage)
        self.assertEqual(len(calls),n)
        self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['stage'],4)

    def test_terminal_bypasses_throttle_and_records_ack(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        self.assertEqual(len(calls),2)
        self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['card_stage'],1)
        b.reply('om_SYNTHETIC','answer',lambda *a:response())
        row=b.progress.row(b.db,'om_SYNTHETIC')
        self.assertEqual(row['card_stage'],4);self.assertEqual(row['reaction'],'removed')
        self.assertEqual(row['diagnostic'],'')

    def test_failed_dispatch_can_end_in_proven_sent(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:429)
        b.reply('om_SYNTHETIC','answer',lambda *a:response())
        row=b.progress.row(b.db,'om_SYNTHETIC')
        self.assertEqual((row['stage'],row['card_stage']),(4,4))
        self.assertEqual(sum(x[:2]==('reactions','delete') for x in calls),1)

    def test_caller_cannot_invent_sent(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        b.feedback('om_SYNTHETIC','replied')
        self.assertNotEqual(b.progress.row(b.db,'om_SYNTHETIC')['stage'],4)

    def test_expiration_cleanup_and_late_result(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        b.clock=lambda:2000;b.reconcile_progress()
        self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['reaction'],'removed')
        self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['card_stage'],5)
        n=len(calls)
        self.assertEqual(b.reply('om_SYNTHETIC','late',lambda *a:self.fail())['exit'],3)
        b.reconcile_progress();self.assertEqual(len(calls),n)

    def test_unknown_missing_id_is_diagnostic_not_deleted(self):
        b,calls,g=self.run_case()
        original=b.progress.call
        def no_id(argv,body):
            if argv[4:6]==['reactions','create']:
                calls.append(('reactions','create',argv));return {'ok':True,'data':{}}
            return original(argv,body)
        b.progress.call=no_id;b.accept(event(),lambda p:200)
        b.reply('om_SYNTHETIC','answer',lambda *a:response())
        row=b.progress.row(b.db,'om_SYNTHETIC')
        self.assertEqual(row['reaction'],'unknown');self.assertTrue(row['diagnostic'])
        self.assertNotIn(('reactions','delete'),[x[:2] for x in calls])

    def test_terminal_ui_failures_remain_unconfirmed(self):
        for failure in ('permission','429','crash','unknown'):
            b,calls,g=self.run_case();b.accept(event(),lambda p:200)
            def fail(argv,body):
                calls.append(('terminal','failure',argv))
                if failure=='crash':raise TimeoutError()
                return {} if failure=='unknown' else {'ok':False,'error':{'code':failure}}
            b.progress.call=fail
            self.assertEqual(b.reply('om_SYNTHETIC','answer',lambda *a:response())['reply_status'],'sent')
            row=b.progress.row(b.db,'om_SYNTHETIC')
            self.assertEqual((row['stage'],row['card_stage']),(4,1))
            self.assertEqual(row['reaction'],'unknown');self.assertEqual(row['reaction_op'],'delete')
            self.assertTrue(row['diagnostic']);n=len(calls)
            b.recover();b.feedback('om_SYNTHETIC','failed');self.assertEqual(len(calls),n)

    def test_restart_pending_text_reconciles_known_handles(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        b.db.execute("UPDATE inbox SET reply='pending'")
        path=Path(b.db.execute('PRAGMA database_list').fetchone()[2])
        reopened=Bridge(path,CFG,lambda:1002,g,'new',b.progress)
        try:
            reopened.recover()
            row=b.progress.row(reopened.db,'om_SYNTHETIC')
            self.assertEqual(row['reaction'],'removed');self.assertEqual(row['card_stage'],5)
            self.assertEqual(reopened.db.execute('SELECT reply FROM inbox').fetchone()[0],'unknown')
        finally:reopened.close()

    def test_target_tampering_denied(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200);n=len(calls)
        b.db.execute("UPDATE inbox SET owner='ou_OTHER'")
        b.feedback('om_SYNTHETIC','failed');self.assertEqual(len(calls),n)

    def test_generation_rejection_keeps_unresolved_handles(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200);n=len(calls)
        g.pause();g.clock_ns=lambda:1003000000000;g.activate('new')
        b.feedback('om_SYNTHETIC','failed')
        row=b.progress.row(b.db,'om_SYNTHETIC')
        self.assertEqual(row['reaction'],'active');self.assertTrue(row['diagnostic'])
        self.assertEqual(len(calls),n)

    def test_concurrent_connections_serialize_terminal(self):
        import threading
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        b.db.execute("UPDATE inbox SET reply='sent'")
        path=Path(b.db.execute('PRAGMA database_list').fetchone()[2])
        barrier=threading.Barrier(3);errors=[]
        def worker(stage):
            try:
                local=Bridge(path,CFG,lambda:1002,g,'new',b.progress)
                try:barrier.wait();local.feedback('om_SYNTHETIC',stage)
                finally:local.close()
            except BaseException as e:errors.append(type(e).__name__)
        threads=[threading.Thread(target=worker,args=(s,)) for s in ('failed','returned')]
        for t in threads:t.start()
        barrier.wait()
        for t in threads:t.join(5);self.assertFalse(t.is_alive())
        self.assertEqual(errors,[])
        self.assertEqual(sum(x[:2]==('messages','patch') for x in calls),1)
        self.assertEqual(sum(x[:2]==('reactions','delete') for x in calls),1)
        self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['card_stage'],4)

    def test_out_of_order_nonterminal_does_not_regress(self):
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        b.clock=lambda:1004;b.feedback('om_SYNTHETIC','returned')
        n=len(calls);b.feedback('om_SYNTHETIC','received')
        self.assertEqual(len(calls),n);self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['card_stage'],3)

    def test_profile_configuration_required_and_validated(self):
        from feishu_grok_bot.core import validate_profile
        for value in (None,'','<CLI_PROFILE>','../bad','has space','x\n'):
            with self.assertRaises(ValueError):validate_profile(value)
        self.assertEqual(validate_profile('SYNTHETIC_PROFILE'),'SYNTHETIC_PROFILE')

    def test_progress_exception_never_changes_text_unknown_or_failed(self):
        for result,expected in (({},'unknown'),({'ok':False},'failed')):
            b,calls,g=self.run_case('crash');b.accept(event(),lambda p:200)
            self.assertEqual(b.reply('om_SYNTHETIC','answer',lambda *a:result)['reply_status'],expected)

    def test_late_blocked_io_prevents_duplicate_and_stale_snapshot(self):
        import threading
        b,calls,g=self.run_case();b.accept(event(),lambda p:200)
        b.db.execute("UPDATE inbox SET reply='sent'")
        original=b.progress.call;entered=threading.Event();release=threading.Event();errors=[]
        def delayed(argv,body):
            if argv[4:6]==['messages','patch']:
                entered.set()
                if not release.wait(3):raise TimeoutError()
            return original(argv,body)
        b.progress.call=delayed
        path=Path(b.db.execute('PRAGMA database_list').fetchone()[2])
        def worker(stage):
            try:
                local=Bridge(path,CFG,lambda:1002,g,'new',b.progress)
                try:local.feedback('om_SYNTHETIC',stage)
                finally:local.close()
            except BaseException as e:errors.append(type(e).__name__)
        first=threading.Thread(target=worker,args=('replied',));first.start()
        try:
            self.assertTrue(entered.wait(3))
            # Durable intent is unknown while CLI result has not returned.
            self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['card_state'],'unknown')
            second=threading.Thread(target=worker,args=('failed',));second.start()
            release.set();second.join(5);self.assertFalse(second.is_alive())
        finally:release.set();first.join(5)
        self.assertEqual(errors,[])
        self.assertEqual(sum(x[:2]==('messages','patch') for x in calls),1)
        self.assertEqual(b.progress.row(b.db,'om_SYNTHETIC')['card_stage'],4)

    def test_malformed_card_result_does_not_prevent_known_reaction_cleanup(self):
        b,calls,g=self.run_case();b.progress.cards=False;b.accept(event(),lambda p:200)
        b.progress.cards=True
        original=b.progress.call
        def malformed(argv,body):
            if argv[4]=='+messages-reply':return {'ok':True,'data':{'message_id':[], 'chat_id':CFG.chat}}
            return original(argv,body)
        b.progress.call=malformed
        self.assertEqual(b.reply('om_SYNTHETIC','answer',lambda *a:response())['reply_status'],'sent')
        row=b.progress.row(b.db,'om_SYNTHETIC')
        self.assertEqual(row['reaction'],'removed');self.assertEqual(row['card_state'],'unknown')

    def test_profile_missing_or_invalid_config_fails_closed(self):
        from dataclasses import asdict
        from feishu_grok_bot.live import load
        policy={k:v for k,v in asdict(CFG).items() if k!='cli_profile'}
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config.json'
            for profile in (None,'<CLI_PROFILE>','../../profile'):
                data={'policy':policy}
                if profile is not None:data['cli_profile']=profile
                p.write_text(json.dumps(data));p.chmod(0o600)
                with self.assertRaisesRegex(ValueError,'invalid_cli_profile'):load(p)

    def test_diagnostic_results_are_fixed_categories(self):
        for failure,tag in (('permission','permission_denied'),('429','rate_limited'),('crash','exception'),('unknown','unknown')):
            b,calls,g=self.run_case(failure);b.accept(event(),lambda p:200)
            row=b.progress.row(b.db,'om_SYNTHETIC')
            self.assertEqual(row['reaction_result'],tag)
            self.assertEqual(row['card_result'],tag)
