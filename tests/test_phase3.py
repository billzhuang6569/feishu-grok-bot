"""Synthetic retired-legacy replacement; no imports/copies of old source."""
import tempfile
from pathlib import Path
import threading
import time
import unittest
from feishu_grok_bot.gate import Gate, Fenced, event_ms
from feishu_grok_bot.core import Bridge
from test_bridge import CFG, event, response


class SharedFenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tick = 999000000000
        self.g = Gate(self.root, lambda: self.tick)
        self.g.initialize()
        self.g.activate('legacy-compatible')

    def tearDown(self):
        self.tmp.cleanup()

    def bridge(self, mode='legacy-compatible'):
        return Bridge(self.root/(mode+'.sqlite'), CFG, lambda: 1002, self.g, mode)

    def switch(self, mode='new'):
        self.g.pause()
        self.tick += 1000000000
        self.g.activate(mode)

    def test_dual_modes_and_delayed_helper(self):
        old, new = self.bridge(), self.bridge('new')
        try:
            self.assertEqual(new.accept(event(), lambda p:self.fail()), 'rejected')
            self.assertEqual(old.accept(event(), lambda p:200), 'accepted')
            self.switch()
            self.assertEqual(old.reply('om_SYNTHETIC','late',lambda *a:self.fail())['exit'],3)
            self.assertEqual(new.accept(event(),lambda p:self.fail()), 'rejected')
            self.switch('legacy-compatible')
            self.assertEqual(old.reply('om_SYNTHETIC','later',lambda *a:self.fail())['exit'],3)
            self.assertEqual(old.accept(event(),lambda p:self.fail()),'rejected')
        finally:
            old.close(); new.close()

    def test_sent_unknown_dedup_survives_generations(self):
        for kind in ('sent','unknown'):
            b=self.bridge()
            mid='om_'+kind
            try:
                self.assertEqual(b.accept(event(message_id=mid,event_id=kind),lambda p:200),'accepted')
                result=b.reply(mid,'body',lambda *a:response() if kind=='sent' else {})
                self.assertEqual(result['reply_status'],kind)
                self.assertEqual(b.reply(mid,'again',lambda *a:self.fail())['exit'],4)
            finally:b.close()
        self.switch();self.switch('legacy-compatible')
        b=self.bridge()
        try:
            self.assertEqual(b.db.execute('SELECT reply FROM inbox ORDER BY mid').fetchall(),[('sent',),('unknown',)])
            for kind in ('sent','unknown'):
                self.assertEqual(b.reply('om_'+kind,'late',lambda *a:self.fail())['exit'],3)
        finally:b.close()

    def test_pause_drains_accept_and_long_send(self):
        for operation in ('accept','reply'):
            entered,release,done=threading.Event(),threading.Event(),threading.Event()
            errors=[]
            def external(*args):
                entered.set()
                if not release.wait(5):raise AssertionError('timeout')
                return 200 if operation=='accept' else response()
            def worker():
                b=self.bridge()
                try:
                    if operation=='reply':b.accept(event(message_id='om_reply',event_id='reply'),lambda p:200)
                    if operation=='accept':b.accept(event(message_id='om_accept',event_id='accept'),external)
                    else:b.reply('om_reply','body',external)
                except BaseException as e:errors.append(e)
                finally:b.close()
            def pause():
                try:self.g.pause();done.set()
                except BaseException as e:errors.append(e)
            w=threading.Thread(target=worker);w.start()
            self.assertTrue(entered.wait(3))
            p=threading.Thread(target=pause);p.start()
            # Wait for durable pause intent, not just a scheduler delay.
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                with self.g.db() as db:paused=db.execute('SELECT paused FROM control').fetchone()[0]
                if paused:break
                time.sleep(.005)
            self.assertEqual(paused,1)
            self.assertFalse(done.is_set())
            with self.assertRaises(Fenced):
                with self.g.lease('legacy-compatible','om_other',1001,True):self.fail()
            release.set();w.join(5);p.join(5)
            self.assertFalse(w.is_alive());self.assertFalse(p.is_alive())
            self.assertEqual(errors,[]);self.assertTrue(done.is_set())
            self.tick+=1000000;self.g.activate('legacy-compatible')

    def test_restart_pause_and_atomic_activation(self):
        self.g.pause()
        restarted=Gate(self.root,lambda:self.tick+1000000)
        with self.assertRaises(Fenced):
            with restarted.lease('legacy-compatible','om_X',1000,True):self.fail()
        restarted.activate('new')
        with self.assertRaises(Fenced):restarted.activate('legacy-compatible')
        with restarted.lease('new','om_X',1000,True):pass
        with self.assertRaises(Fenced):
            with restarted.lease('legacy-compatible','om_X'):self.fail()

    def test_crashed_operation_blocks_activation_after_restart(self):
        # Synthetic durable crash image: lease raised before outcome committed.
        with self.assertRaises(RuntimeError):
            with self.g.lease('legacy-compatible','om_CRASH',1000,True):raise RuntimeError('synthetic crash')
        restarted=Gate(self.root,lambda:self.tick+1000000)
        with self.assertRaises(Fenced):restarted.pause()
        with self.assertRaises(Fenced):restarted.activate('new')
        with self.assertRaises(Fenced):
            with restarted.lease('legacy-compatible','om_CRASH'):self.fail()

    def test_timestamp_precision_and_missing(self):
        for v in (None,True,0,'nan','inf',999.0001):
            with self.assertRaises(Fenced):event_ms(v)
        self.assertEqual(event_ms('1000.001'),1000001)
        self.g.pause();self.tick=1000000000001;self.g.activate('legacy-compatible')
        for v in (1000,1000.001,None):
            with self.assertRaises(Fenced):
                with self.g.lease('legacy-compatible','om_BOUND',v,True):self.fail()
        with self.g.lease('legacy-compatible','om_AFTER','1000.002',True):pass

    def test_no_gate_or_permissions_fail_closed(self):
        missing=self.root/'missing';missing.mkdir(mode=0o700)
        g=Gate(missing)
        with self.assertRaises(Exception):
            with g.lease('new','om_X',1000,True):self.fail()
        self.root.chmod(0o755)
        with self.assertRaises(Fenced):Gate(self.root)
        self.root.chmod(0o700)

    def test_no_patch_deployment_removal_preserves_metadata(self):
        # Synthetic legacy slot changes entrypoint only; original bytes untouched.
        original=b'synthetic legacy executable; never executed'
        slot=self.root/'legacy-original';slot.write_bytes(original)
        deployment={'entrypoint':'original'}
        deployment['entrypoint']='trusted-compatible-launcher'
        b=self.bridge()
        try:b.accept(event(),lambda p:200)
        finally:b.close()
        self.g.pause()
        deployment['entrypoint']='disabled'  # Withdrawal is stopped, not unsafe resume.
        self.assertEqual(slot.read_bytes(),original)
        with self.g.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM claims').fetchone()[0],1)
        self.assertTrue((self.root/'legacy-compatible.sqlite').exists())

    def test_invalid_owner_and_payload_cannot_modify_gate(self):
        b=self.bridge()
        try:
            self.assertEqual(b.accept(event(sender_open_id='ou_OTHER'),lambda p:self.fail()),'rejected')
            with self.g.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM claims').fetchone()[0],0)
            self.assertEqual(b.accept(event(gate_mode='new',generation=99,shared_gate_dir='/untrusted'),lambda p:200),'accepted')
            with self.g.db() as db:
                self.assertEqual(db.execute('SELECT generation,mode,paused FROM control').fetchone(),(1,'legacy-compatible',0))
        finally:b.close()

    def test_bridge_missing_time_and_live_missing_gate(self):
        from feishu_grok_bot.live import live_bridge
        b=self.bridge()
        try:
            e=event();e.pop('created_at')
            self.assertEqual(b.accept(e,lambda p:self.fail()),'rejected')
        finally:b.close()
        with self.assertRaises(KeyError):live_bridge({'state_dir':str(self.root)},CFG)

    def test_activation_waits_for_long_operation_and_pause(self):
        entered,release,paused,activated=[threading.Event() for _ in range(4)]
        errors=[]
        def work():
            try:
                with self.g.lease('legacy-compatible','om_LONG',1000,True):
                    entered.set()
                    if not release.wait(5):raise AssertionError('timeout')
            except BaseException as e:errors.append(e)
        def pause():
            try:self.g.pause();paused.set()
            except BaseException as e:errors.append(e)
        def activate():
            try:self.g.activate('new');activated.set()
            except BaseException as e:errors.append(e)
        w=threading.Thread(target=work);w.start();self.assertTrue(entered.wait(3))
        p=threading.Thread(target=pause);p.start()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            with self.g.db() as db:state=db.execute('SELECT paused FROM control').fetchone()[0]
            if state:break
            time.sleep(.005)
        self.assertEqual(state,1)
        self.tick+=1000000000
        a=threading.Thread(target=activate);a.start()
        self.assertFalse(paused.wait(.02));self.assertFalse(activated.is_set())
        release.set()
        for t in (w,p,a):t.join(5);self.assertFalse(t.is_alive())
        self.assertEqual(errors,[]);self.assertTrue(paused.is_set());self.assertTrue(activated.is_set())
        with self.assertRaises(Fenced):
            with self.g.lease('new','om_LONG'):self.fail()
