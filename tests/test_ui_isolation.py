"""Deterministic offline UI isolation; events hold IO until assertions finish."""
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from feishu_grok_bot.core import Bridge
from feishu_grok_bot.gate import Gate, Fenced
from feishu_grok_bot.live import Capabilities
from feishu_grok_bot.progress import Progress
from test_bridge import CFG, event, response

SETTINGS = dict(cli_path='/synthetic/approved-cli', cli_profile=CFG.cli_profile,
                live_enabled=True, reaction_enabled=True, progress_card_enabled=True)


class Fixtures:
    def setup_bridge(self, call=None, settings=None):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        gate_dir = root/'gate'; gate_dir.mkdir(mode=0o700)
        gate = Gate(gate_dir, lambda: 999000000000)
        gate.initialize(); gate.activate('new')
        calls = []
        def ok(argv, body):
            calls.append(argv)
            if argv[4] == 'reactions':
                return {'ok': True, 'data': {'reaction_id': 'synthetic-handle'}}
            return response()
        p = Progress(settings or SETTINGS, call or ok)
        b = Bridge(root/'state.sqlite', CFG, lambda: 1002, gate, 'new', p)
        self.addCleanup(b.close)
        return b, p, gate, calls

    def idle(self, p):
        self.assertTrue(p.wait_idle(3), 'worker did not finish')

    def blocker(self):
        entered, release, exited = [threading.Event() for _ in range(3)]
        calls = []
        def call(argv, body):
            calls.append(argv); entered.set()
            try:
                if not release.wait(5):
                    raise TimeoutError('synthetic hold expired')
                raise TimeoutError('synthetic UI timeout')
            finally:
                exited.set()
        self.addCleanup(release.set)
        return call, entered, release, exited, calls


    def wait_paused(self, g):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            with g.db() as db:
                if db.execute('SELECT paused FROM control').fetchone()[0]:
                    return
            time.sleep(.001)
        self.fail('pause intent was not committed')



class IsolationTests(Fixtures, unittest.TestCase):
    def test_post_send_and_next_accept_complete_while_ui_is_held(self):
        call, entered, release, exited, calls = self.blocker()
        b, p, g, _ = self.setup_bridge(call)
        posts = []
        start = time.monotonic()
        self.assertEqual(b.accept(event(), lambda payload: posts.append(payload) or 200), 'accepted')
        self.assertTrue(entered.wait(2)); self.assertFalse(exited.is_set())
        self.assertEqual(len(posts), 1)
        self.assertEqual(b.reply('om_SYNTHETIC', 'answer', lambda *a: response())['reply_status'], 'sent')
        self.assertEqual(b.accept(event(message_id='om_NEXT', event_id='next'),
                                  lambda payload: posts.append(payload) or 200), 'accepted')
        self.assertEqual(len(posts), 2)
        self.assertFalse(exited.is_set(), 'main flow waited for UI timeout')
        self.assertEqual(len(calls), 1)
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['reaction'], 'unknown')
        elapsed = time.monotonic()-start
        print('UI-ISOLATION: post + text sent + next accept completed while UI held; '
              f'elapsed={elapsed:.6f}s; UI released only after assertions')
        release.set(); self.idle(p)

    def test_queue_bounded_and_same_message_coalesces(self):
        call, entered, release, exited, calls = self.blocker()
        b, p, g, _ = self.setup_bridge(call)
        b.accept(event(), lambda p: 200); self.assertTrue(entered.wait(2))
        for i in range(500):
            b.feedback('om_PENDING'+str(i), 'received')
        with p._condition:
            self.assertEqual(len(p._pending), 32)
        for stage in ('received', 'returned', 'failed', 'submitted', 'replied', 'failed'):
            b.feedback('om_PENDING0', stage)
        with p._condition:
            self.assertEqual(len(p._pending), 32)
            self.assertEqual(p._pending[(str(b.path), 'om_PENDING0')][-1], 'replied')
        self.assertEqual(len(calls), 1)
        release.set(); self.idle(p)

    def test_pause_cannot_certify_blocked_ui_and_cancels_remaining_operations(self):
        call, entered, release, exited, calls = self.blocker()
        b, p, g, _ = self.setup_bridge(call)
        b.accept(event(), lambda p: 200); self.assertTrue(entered.wait(2))
        b.feedback('om_SYNTHETIC', 'returned')
        done = threading.Event(); errors = []
        def pause():
            try: g.pause(); done.set()
            except Exception as exc: errors.append(type(exc).__name__)
        t = threading.Thread(target=pause); t.start()
        try:
            self.wait_paused(g)
            self.assertFalse(done.is_set())
            self.assertFalse(p.shutdown())
            self.assertFalse(done.is_set(), 'shutdown cannot fake a drain certificate')
            self.assertEqual(len(calls), 1)
        finally:
            release.set(); t.join(3)
        self.assertFalse(t.is_alive()); self.assertTrue(done.is_set()); self.assertEqual(errors, [])
        self.idle(p)
        self.assertEqual(len(calls), 1)
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['reaction'], 'unknown')
        g.clock_ns = lambda: 1003000000000; g.activate('new')
        fresh = Progress(SETTINGS, lambda *a: self.fail('cross-generation UI'))
        b.progress = fresh; b.feedback('om_SYNTHETIC', 'failed'); self.idle(fresh)
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['reaction'], 'unknown')

    def test_shutdown_abandons_queue_but_retains_active_unknown_and_lease(self):
        call, entered, release, exited, calls = self.blocker()
        b, p, g, _ = self.setup_bridge(call)
        b.accept(event(), lambda p: 200); self.assertTrue(entered.wait(2))
        b.feedback('om_SYNTHETIC', 'failed')
        self.assertFalse(b.close())
        # Avoid a second close of the caller connection; worker owns its own DB.
        self._cleanups = [x for x in self._cleanups if x[0] != b.close]
        with g.db() as db:
            self.assertTrue(db.execute('SELECT 1 FROM operations').fetchone())
        with self.assertRaises(BlockingIOError):
            with g.lock(True, blocking=False): self.fail('undrained lease')
        with p._condition: self.assertEqual(len(p._pending), 0)
        p.submit(b, 'om_SYNTHETIC', 'received')
        release.set(); self.idle(p)
        self.assertTrue(p.shutdown()); self.assertEqual(len(calls), 1)
        g.pause()  # only actual IO completion allows a certificate

    def test_restart_unknown_is_not_replayed(self):
        b, p, g, calls = self.setup_bridge(lambda *a: {})
        b.accept(event(), lambda p: 200); self.idle(p)
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['reaction'], 'unknown')
        self.assertTrue(p.shutdown())
        fresh = Progress(SETTINGS, lambda *a: self.fail('unknown replay'))
        other = Bridge(b.path, CFG, lambda: 1002, g, 'new', fresh)
        try:
            other.recover(); other.feedback('om_SYNTHETIC', 'returned'); self.idle(fresh)
            self.assertEqual(fresh.row(other.db, 'om_SYNTHETIC')['card_state'], 'unknown')
        finally: other.close()

    def test_terminal_order_and_sent_authority_through_async_queue(self):
        b, p, g, calls = self.setup_bridge()
        b.accept(event(), lambda p: 200); self.idle(p)
        b.feedback('om_SYNTHETIC', 'failed'); self.idle(p)
        b.feedback('om_SYNTHETIC', 'received'); self.idle(p)
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['stage'], 5)
        self.assertEqual(b.reply('om_SYNTHETIC', 'answer', lambda *a: response())['reply_status'], 'sent')
        self.idle(p)
        for stage in ('failed', 'returned', 'received'): b.feedback('om_SYNTHETIC', stage)
        self.idle(p)
        row = p.row(b.db, 'om_SYNTHETIC')
        self.assertEqual((row['stage'], row['card_stage']), (4, 4))
        self.assertEqual(row['reaction'], 'removed')

    def test_ui_failure_preserves_all_text_classifications(self):
        for envelope, state in ((response(), 'sent'), ({}, 'unknown'), ({'ok': False}, 'failed')):
            b, p, g, _ = self.setup_bridge(lambda *a: (_ for _ in ()).throw(TimeoutError()))
            b.accept(event(), lambda p: 200)
            self.assertEqual(b.reply('om_SYNTHETIC', 'answer', lambda *a: envelope)['reply_status'], state)
            self.idle(p)
            self.assertEqual(b.db.execute('SELECT reply FROM inbox').fetchone()[0], state)

    def test_busy_progress_lock_is_skipped_without_blocking_main_or_worker(self):
        b, p, g, calls = self.setup_bridge()
        with g.lock(True, 'progress.lock'):
            self.assertEqual(b.accept(event(), lambda p: 200), 'accepted')
            self.idle(p)
            self.assertEqual(calls, [])
            self.assertEqual(b.reply('om_SYNTHETIC', 'answer', lambda *a: response())['reply_status'], 'sent')
            self.idle(p); self.assertEqual(calls, [])
        b.reconcile_progress(); self.idle(p)
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['card_stage'], 4)
        g.pause()  # skipped lock attempts must not leave phantom crash barriers

    def test_two_workers_no_duplicate_or_stale_terminal_overwrite(self):
        b, p, g, calls = self.setup_bridge()
        b.accept(event(), lambda p: 200); self.idle(p)
        original = p.call; entered = threading.Event(); release = threading.Event()
        def delayed(argv, body):
            if argv[4:6] == ['messages', 'patch']:
                entered.set()
                if not release.wait(5): raise TimeoutError()
            return original(argv, body)
        p.call = delayed
        b.reply('om_SYNTHETIC', 'answer', lambda *a: response())
        self.assertTrue(entered.wait(2))
        second = Progress(SETTINGS, original)
        other = Bridge(b.path, CFG, lambda: 1002, g, 'new', second)
        try:
            other.feedback('om_SYNTHETIC', 'failed'); self.idle(second)
            self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['card_state'], 'unknown')
        finally:
            release.set(); self.idle(p); other.close()
        b.feedback('om_SYNTHETIC', 'failed'); self.idle(p)
        self.assertEqual(sum(a[4:6] == ['messages', 'patch'] for a in calls), 1)
        self.assertEqual(sum(a[4:6] == ['reactions', 'delete'] for a in calls), 1)
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['card_stage'], 4)

    def test_queued_old_generation_hint_cannot_start_external_io(self):
        b, p, g, calls = self.setup_bridge()
        entered = threading.Event(); release = threading.Event()
        advance = p.advance
        def delayed(*args):
            entered.set()
            if not release.wait(5): raise TimeoutError()
            return advance(*args)
        with patch.object(p, 'advance', side_effect=delayed):
            b.accept(event(), lambda p: 200); self.assertTrue(entered.wait(2))
            try:
                g.pause()  # unstarted hints are fenced, with no external intent
                g.clock_ns = lambda: 1003000000000; g.activate('new')
            finally: release.set()
            self.idle(p)
        self.assertEqual(calls, [])
        with g.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM operations').fetchone())

    def test_non_true_flags_do_not_start_worker(self):
        for value in (None, False, 1, 'true'):
            settings = dict(SETTINGS, reaction_enabled=value, progress_card_enabled=value)
            b, p, g, calls = self.setup_bridge(settings=settings)
            b.accept(event(), lambda p: 200)
            self.assertIsNone(p._thread); self.assertEqual(calls, [])


class CancellationTests(Fixtures, unittest.TestCase):
    def capability(self, proof=b'{"drained":true,"result":null}', status=0):
        from unittest.mock import Mock
        child = Mock()
        child.communicate.return_value = (proof, None)
        child.wait.return_value = status
        return Capabilities(SETTINGS, True), child

    def invoke(self, cap, child, cancelled=lambda: False):
        with patch.dict('os.environ', {'HOME': '/synthetic/home'}, clear=True), \
             patch('feishu_grok_bot.live.subprocess.Popen', return_value=child) as spawn:
            value = cap.ui_send([SETTINGS['cli_path'], 'synthetic'], 'body', cancelled)
            return value, spawn.call_args

    def test_ui_child_success_uses_stdin_and_shared_environment(self):
        cap, child = self.capability(b'{"drained":true,"result":{"ok":true}}')
        value, args = self.invoke(cap, child)
        self.assertEqual(value, {'ok': True})
        self.assertEqual(child.communicate.call_args.kwargs['input'], b'body')
        self.assertEqual(args.kwargs['env'], {'HOME': '/synthetic/home', 'PATH': '/usr/bin:/bin'})
        self.assertEqual(len(args.kwargs['pass_fds']), 1)

    def test_no_proof_retains_barrier(self):
        from feishu_grok_bot.live import UIUnreaped
        cap, child = self.capability(b'{}')
        with self.assertRaises(UIUnreaped): self.invoke(cap, child)

    def test_abnormal_supervisor_exit_rejects_proof(self):
        from feishu_grok_bot.live import UIUnreaped
        cap, child = self.capability(status=2)
        with self.assertRaises(UIUnreaped): self.invoke(cap, child)

    def test_malformed_proof_rejected(self):
        from feishu_grok_bot.live import UIUnreaped
        cap, child = self.capability(b'incomplete')
        with self.assertRaises(UIUnreaped): self.invoke(cap, child)

    def test_pre_cancel_starts_no_process(self):
        cap, child = self.capability()
        value, args = self.invoke(cap, child, lambda: True)
        self.assertIsNone(value); self.assertIsNone(args)

    def test_supervisor_failure_keeps_unknown_and_gate_barrier(self):
        cap, child = self.capability(status=3)
        b, p, g, _ = self.setup_bridge(cap.send)
        with patch.dict('os.environ', {'HOME': '/synthetic/home'}, clear=True), \
             patch('feishu_grok_bot.live.subprocess.Popen', return_value=child):
            b.accept(event(), lambda p: 200); self.idle(p)
        self.assertFalse(p.shutdown())
        self.assertEqual(p.row(b.db, 'om_SYNTHETIC')['reaction'], 'unknown')
        with self.assertRaises(Fenced): g.pause()
        with self.assertRaises(Fenced): g.activate('new')
