import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from feishu_grok_bot.live import receive
from feishu_grok_bot.core import Bridge
from feishu_grok_bot.ops import Recovery
from test_bridge import CFG, event


class Child:
    def __init__(self,events):
        self.stdin=io.BytesIO()
        def pipe(data):
            r,w=os.pipe();os.write(w,data);os.close(w)
            return os.fdopen(r,'rb',buffering=0)
        self.stdout=pipe(b''.join(json.dumps(e).encode()+b'\n' for e in events))
        self.stderr=pipe(b'[event] ready SYNTHETIC\n')
    def poll(self):return 0
    def wait(self,timeout):return 0


class ReceiverTests(unittest.TestCase):
    def run_receiver(self,events,child_class=Child):
        class Cap:
            cli='/synthetic/never-executed-cli'
            calls=[]
            def post(self,p):self.calls.append(p);return 200
        with tempfile.TemporaryDirectory() as tmp:
            cap=Cap()
            b=Bridge(Path(tmp)/'bridge.sqlite',CFG,lambda:1000)
            b.mark_cutover(1000);b.close()
            from feishu_grok_bot.gate import Gate
            gate_dir=Path(tmp)/'gate';gate_dir.mkdir(mode=0o700)
            g=Gate(gate_dir,lambda:999000000000);g.initialize();g.activate('new')
            with patch.dict('os.environ',{'HOME':'/synthetic/home'},clear=True), patch('feishu_grok_bot.live.subprocess.Popen',side_effect=lambda *a,**k:child_class(events)) as popen, \
                 patch('feishu_grok_bot.live.signal.signal'), \
                 patch('feishu_grok_bot.live.Bridge',side_effect=lambda *a:Bridge(*a,clock=lambda:1000)), \
                 patch('feishu_grok_bot.live.time.time',return_value=1000), \
                 patch('feishu_grok_bot.live.Recovery',return_value=Recovery(maximum=0)), \
                 patch('sys.stdout',new_callable=io.StringIO) as out:
                result=receive({'state_dir':tmp,'shared_gate_dir':str(gate_dir),'gate_mode':'new'},CFG,cap)
            return result,cap.calls,popen.call_args,out.getvalue()

    def test_receiver_mock_stream_and_profile(self):
        result,calls,args,out=self.run_receiver([event()])
        self.assertEqual(result,2) # bounded recovery exhausted after fake EOF
        self.assertEqual(len(calls),1)
        argv=args.args[0]
        self.assertEqual(argv[argv.index('--profile')+1],'SYNTHETIC_PROFILE')
        self.assertIn('consume',argv)
        self.assertNotIn('synthetic question',out)
        self.assertIn('recent_observation',out)

    def test_receiver_drops_prestart_messages(self):
        _,calls,_,_=self.run_receiver([event(created_at=999)])
        self.assertEqual(calls,[])

    def test_receiver_missing_time_failclosed(self):
        e=event();e.pop('created_at')
        _,calls,_,_=self.run_receiver([e]);self.assertEqual(calls,[])

    def test_receiver_no_competitor_if_child_will_not_exit(self):
        class Stuck(Child):
            def wait(self,timeout):raise subprocess.TimeoutExpired('synthetic',timeout)
        with self.assertRaisesRegex(RuntimeError,'consume_did_not_exit'):
            self.run_receiver([],Stuck)
