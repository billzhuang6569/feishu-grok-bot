from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from feishu_grok_bot.core import Bridge, Config, EVENT, classify, normalize, reply_argv, stop_argv
from feishu_grok_bot.ops import Health, Recovery
from feishu_grok_bot.live import Capabilities, exclusive, load
from feishu_grok_bot.__main__ import main

# All identifiers are deliberately synthetic; no existing history or constants.
CFG = Config('cli_SYNTHETIC','synthetic_tenant','ou_SYNTHETIC','oc_SYNTHETIC', 'SYNTHETIC_PROFILE')


def event(**kwargs):
    e = dict(app_id=CFG.app,tenant_key=CFG.tenant,event_type=EVENT,
             sender_open_id=CFG.owner,chat_id=CFG.chat,sender_type='user',
             chat_type='p2p',message_type='text',message_id='om_SYNTHETIC',
             event_id='synthetic_event',created_at=1000,text='synthetic question')
    e.update(kwargs)
    return e


def response(**kwargs):
    return {'ok':True,'data':dict(message_id='om_SYNTHETIC_OUT',chat_id=CFG.chat,**kwargs)}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'bridge.sqlite'
        self.now = 1000
        self.b = Bridge(self.path,CFG,lambda:self.now)
        self.addCleanup(lambda:self.b.close())
        self.calls = []

    def post(self,p):
        self.calls.append(p)
        return 200

    def seed(self):
        self.assertEqual(self.b.accept(event(),self.post),'accepted')

    def test_payload_contract(self):
        self.seed()
        self.assertEqual(set(self.calls[0]),set('event_id message_id chat_id sender_open_id chat_type thread_id text verified_at source app_id profile'.split()))
        self.assertEqual(self.calls[0]['source'],'lark-cli-event-consume')
        self.assertEqual(self.calls[0]['profile'],'SYNTHETIC_PROFILE')

    def test_duplicate_message_different_event(self):
        self.seed()
        self.assertEqual(self.b.accept(event(event_id='other'),self.post),'duplicate')
        self.assertEqual(len(self.calls),1)

    def test_duplicate_event_different_message(self):
        self.seed()
        self.assertEqual(self.b.accept(event(message_id='om_OTHER'),self.post),'duplicate')

    def test_restart_no_replay(self):
        self.seed()
        self.b.close()
        self.b = Bridge(self.path,CFG,lambda:self.now)
        self.b.recover()
        self.assertEqual(self.b.accept(event(),self.post),'duplicate')
        self.assertEqual(len(self.calls),1)

    def test_pending_recovery_no_retry(self):
        self.seed()
        self.b.db.execute("UPDATE inbox SET dispatch='pending',reply='pending'")
        self.b.recover()
        self.assertEqual(self.b.db.execute('SELECT dispatch,reply FROM inbox').fetchone(),('unknown','unknown'))
        self.assertEqual(self.b.reply('om_SYNTHETIC','answer',lambda *a:self.fail())['exit'],4)

    def test_crash_during_post(self):
        def crash(p):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.b.accept(event(),crash)
        self.b.recover()
        self.assertEqual(self.b.accept(event(),self.post),'duplicate')
        self.assertEqual(self.b.db.execute('SELECT dispatch FROM inbox').fetchone()[0],'unknown')

    def test_reply_success_stdin_target(self):
        self.seed()
        calls=[]
        def send(argv,body):
            calls.append((argv,body));return response()
        result=self.b.reply('om_SYNTHETIC','synthetic answer',send)
        self.assertEqual(result['exit'],0)
        argv,body=calls[0]
        self.assertNotIn(body,argv)
        self.assertEqual(argv[argv.index('--text')+1],'-')
        self.assertEqual(argv[argv.index('--message-id')+1],'om_SYNTHETIC')
        self.assertEqual(len(self.b.context()['items']),2)
        self.assertEqual(self.b.db.execute("SELECT at FROM observations WHERE kind='e2e'").fetchone()[0],1000)
        self.assertEqual(self.b.reply('om_SYNTHETIC','again',send)['exit'],4)

    def test_unknown_timeout_no_retry(self):
        self.seed()
        calls=[]
        def send(*a):
            calls.append(1);raise TimeoutError('SYNTHETIC_SECRET')
        r=self.b.reply('om_SYNTHETIC','answer',send)
        self.assertEqual(r['reply_status'],'unknown')
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(r))
        self.assertEqual(self.b.reply('om_SYNTHETIC','again',send)['exit'],4)
        self.assertEqual(len(calls),1)

    def test_crash_during_send(self):
        self.seed()
        def crash(*a):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.b.reply('om_SYNTHETIC','answer',crash)
        self.b.recover()
        self.assertEqual(self.b.reply('om_SYNTHETIC','again',lambda *a:self.fail())['exit'],4)

    def test_expired_reply(self):
        self.seed();self.now+=CFG.reply_ttl
        self.assertEqual(self.b.reply('om_SYNTHETIC','answer',lambda *a:self.fail())['exit'],3)

    def test_unregistered_reply(self):
        self.assertEqual(self.b.reply('om_OTHER','answer',lambda *a:self.fail())['exit'],3)

    def test_context_ttl_physically_pruned(self):
        self.seed();self.now+=CFG.context_ttl
        self.assertEqual(self.b.context()['items'],[])
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM context').fetchone()[0],0)

    def test_context_count_and_bytes(self):
        for i in range(60):
            with self.b.transaction():self.b.add_context('owner','om_'+str(i),'字'*1000)
        rows=self.b.context()['items']
        self.assertLessEqual(len(rows),20)
        self.assertLessEqual(len(json.dumps(self.b.context(),ensure_ascii=False).encode()),CFG.context_bytes)

    def test_context_other_chat_denied(self):
        self.seed();self.assertFalse(self.b.context('oc_OTHER')['ok'])

    def test_budget(self):
        for i in range(CFG.budget):
            self.assertEqual(self.b.accept(event(message_id='om_'+str(i),event_id=str(i)),self.post),'accepted')
        self.assertEqual(self.b.accept(event(),self.post),'budget_exhausted')

    def test_state_binding_rejects_reconfiguration(self):
        with self.assertRaisesRegex(ValueError,'state_binding_mismatch'):
            Bridge(self.path,replace(CFG,owner='ou_OTHER'))

    def test_corrupt_db_fails_closed(self):
        p=Path(self.tmp.name)/'bad';p.write_text('corruption')
        with self.assertRaises(sqlite3.DatabaseError):Bridge(p,CFG)

    def test_public_state_directory_rejected(self):
        d=Path(self.tmp.name)/'public';d.mkdir(mode=0o755);d.chmod(0o755)  # Explicit public fixture, independent of umask.
        with self.assertRaisesRegex(ValueError,'state_directory_must_be_private'):Bridge(d/'state',CFG)

    def test_private_state_permissions(self):
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_concurrent_inbound(self):
        def worker(i):
            b=Bridge(self.path,CFG,lambda:1000)
            try:return b.accept(event(),lambda p:200)
            finally:b.close()
        with ThreadPoolExecutor(max_workers=8) as ex:results=list(ex.map(worker,range(30)))
        self.assertEqual(results.count('accepted'),1)
        self.assertEqual(results.count('duplicate'),29)

    def test_concurrent_reply(self):
        self.seed();calls=[]
        def worker(i):
            b=Bridge(self.path,CFG,lambda:1000)
            try:return b.reply('om_SYNTHETIC','answer',lambda *a:(calls.append(1) or response()))['exit']
            finally:b.close()
        with ThreadPoolExecutor(max_workers=8) as ex:results=list(ex.map(worker,range(30)))
        self.assertEqual(results.count(0),1);self.assertEqual(len(calls),1)

    def test_no_history_dispatch_on_recover(self):
        self.seed();self.b.recover();self.assertEqual(len(self.calls),1)

    def test_raw_envelope(self):
        raw=dict(header=dict(event_type=EVENT,event_id='raw',app_id=CFG.app,tenant_key=CFG.tenant),
                 event=dict(sender=dict(sender_type='user',sender_id=dict(open_id=CFG.owner)),
                            message=dict(message_id='om_RAW',chat_id=CFG.chat,chat_type='p2p',message_type='text',create_time='1000000',content='{"text":"synthetic"}')))
        self.assertEqual(self.b.accept(raw,self.post),'accepted')


# Individually reported negative security and response cases, not duplicated tests.
BAD_EVENTS = {
    'owner':{'sender_open_id':'ou_OTHER'}, 'chat':{'chat_id':'oc_OTHER'},
    'app':{'app_id':'cli_OTHER'}, 'tenant':{'tenant_key':'other'},
    'group':{'chat_type':'group'}, 'echo':{'sender_type':'app'},
    'missing_sender_type':{'sender_type':None}, 'non_text':{'message_type':'image'},
    'event_type':{'event_type':'other'}, 'missing_id':{'message_id':None},
    'invalid_id':{'message_id':'--unsafe'}, 'missing_event':{'event_id':''},
    'empty_body':{'text':''}, 'large_body':{'text':'字'*6000},
    'old':{'created_at':1}, 'future':{'created_at':1001},
    'nan_time':{'created_at':float('nan')}, 'missing_time':{'created_at':None},
    'bad_thread':{'thread_id':[]},
}
for name,changes in BAD_EVENTS.items():
    def test(self,changes=changes):
        self.assertEqual(self.b.accept(event(**changes),lambda p:self.fail('must not forward')),'rejected')
        self.assertEqual(self.b.context()['items'],[])
    setattr(BridgeTests,'test_policy_reject_'+name,test)

for name,status in [('timeout',None),('server_error',500),('rate_limit',429),('rejected',403),('redirect',302)]:
    def test(self,status=status):
        calls=[]
        def post(p):
            calls.append(1)
            if status is None:raise TimeoutError()
            return status
        self.assertEqual(self.b.accept(event(),post),'unknown')
        self.assertEqual(self.b.accept(event(),post),'duplicate')
        self.assertEqual(len(calls),1)
    setattr(BridgeTests,'test_post_no_retry_'+name,test)


class ContractTests(unittest.TestCase):
    def test_cli_success_without_code(self):self.assertEqual(classify(response(),CFG.chat)[0],'sent')
    def test_openapi_success(self):self.assertEqual(classify(dict(code=0,data=response()['data']),CFG.chat)[0],'sent')
    def test_missing_code_unknown(self):self.assertEqual(classify(dict(data=response()['data']),CFG.chat)[0],'unknown')
    def test_explicit_failure(self):self.assertEqual(classify(dict(ok=False,data=response()['data']),CFG.chat)[0],'failed')
    def test_nonzero_code_overrides(self):self.assertEqual(classify(dict(ok=True,code=403,data=response()['data']),CFG.chat)[0],'failed')
    def test_missing_target_proof(self):self.assertEqual(classify(dict(ok=True,data=dict(message_id='om_OUT')),CFG.chat)[0],'unknown')
    def test_conflicting_target(self):self.assertEqual(classify(dict(ok=True,data=dict(message_id='om_OUT',chat_id='oc_OTHER')),CFG.chat)[0],'unknown')
    def test_nested_target_conflict(self):
        p=response();p['data']['message']={'message_id':'om_OTHER','chat_id':'oc_OTHER'}
        self.assertEqual(classify(p,CFG.chat)[0],'unknown')
    def test_missing_outbound(self):self.assertEqual(classify(dict(code=0,data=dict(chat_id=CFG.chat)),CFG.chat)[0],'unknown')
    def test_boolean_code_not_success(self):self.assertEqual(classify(dict(code=False,data=response()['data']),CFG.chat)[0],'unknown')
    def test_stop_scope(self):
        a=stop_argv(CFG);self.assertEqual(a[a.index('--app-id')+1],CFG.app)
        self.assertNotIn('--all',a);self.assertEqual(a[a.index('--profile')+1],'SYNTHETIC_PROFILE')
    def test_thread_flag(self):self.assertIn('--reply-in-thread',reply_argv('om_SYNTHETIC','synthetic_thread', profile=CFG.cli_profile))
    def test_idempotency_key_stable(self):
        self.assertEqual(reply_argv('om_SYNTHETIC', profile=CFG.cli_profile),reply_argv('om_SYNTHETIC', profile=CFG.cli_profile))
        self.assertLessEqual(len(reply_argv('om_SYNTHETIC', profile=CFG.cli_profile)[-2]),50)
    def test_guard_before_config_or_stdin(self):
        with patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(main(['reply','--in-reply-to','om_SYNTHETIC']),3)
        self.assertIn('live_guard_closed',out.getvalue())
    def test_live_transport_default_closed(self):
        with self.assertRaises(ValueError):Capabilities({})
    def test_cli_arbitrary_recipient_rejected(self):
        with patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit):main(['reply','--user-id','ou_OTHER'])
    def test_health_ready_not_upstream(self):
        h=Health(process=True,local_bus=True)
        self.assertEqual(h.snapshot(1000),dict(process='alive',local_bus='ready',upstream='unknown',e2e='unknown'))
    def test_health_stale(self):
        self.assertEqual(Health(True,True,1,1).snapshot(1000)['upstream'],'stale')
    def test_health_recent(self):self.assertEqual(Health(True,True,990,990).snapshot(1000)['e2e'],'recent_observation')
    def test_reconnect_bounded(self):
        h=Health(True,True);r=Recovery()
        self.assertEqual([r.disconnected(h) for _ in range(6)],[1,2,4,8,16,None])
        self.assertFalse(h.local_bus)
    def test_reconnect_reset(self):
        r=Recovery();r.disconnected(Health());r.stable();self.assertEqual(r.failures,0)
    def test_single_consumer_lock(self):
        with tempfile.TemporaryDirectory() as t:
            with exclusive(Path(t)/'lock'):
                with self.assertRaises(BlockingIOError):exclusive(Path(t)/'lock')
    def test_config_invalid(self):
        for kwargs in [dict(owner=''),dict(chat=[]),dict(budget=0),dict(context_ttl=True),dict(app='placeholder')]:
            with self.assertRaises(ValueError):replace(CFG,**kwargs)
    def test_config_repr_redacted(self):self.assertNotIn(CFG.owner,repr(CFG))
    def test_config_live_gate(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config';p.write_text('{"live_enabled":false}');p.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'live_guard_closed'):load(p,True)
    def test_socket_denied(self):
        import socket
        with self.assertRaisesRegex(AssertionError,'offline_boundary'):socket.socket()
    def test_subprocess_denied(self):
        import subprocess
        with self.assertRaisesRegex(AssertionError,'offline_boundary'):subprocess.run(['must-never-run'])
