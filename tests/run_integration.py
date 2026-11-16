"""Linux-only finite synthetic process tests. No network or business CLI.

Independent from run.py: all processes use this runner, Python, or generated
synthetic scripts in a private TemporaryDirectory. Finally reaps exact adopted
children; cleanup failure fails the run. Never uses pkill or system-wide scans.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
os.environ.clear()

def deny(*args, **kwargs):
    raise AssertionError('integration_network_forbidden')

def audit(event, args):
    if event.startswith('socket.') or event == 'os.system':
        deny()
sys.addaudithook(audit)
from feishu_grok_bot.core import Bridge
from feishu_grok_bot.gate import Gate, Fenced
from feishu_grok_bot.live import Capabilities
from feishu_grok_bot.progress import Progress
from test_bridge import CFG, event


def wait(predicate, seconds=5):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('synthetic deadline exceeded')


def child_ids():
    return [int(x) for x in Path('/proc/self/task/%d/children' % os.getpid()).read_text().split()]


def cleanup():
    end = time.monotonic()+6
    while True:
        for pid in child_ids():
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            assert not child_ids()
            return
        if time.monotonic() > end:
            raise AssertionError('synthetic process cleanup failed')
        if not pid: time.sleep(.01)


def gone(pid):
    return not Path('/proc/%d' % pid).exists()


def setup(root, kind='fork'):
    os.environ['HOME'] = str(root)
    script = root/'synthetic-cli.py'
    script.write_text('import os,time\nfrom pathlib import Path\n'
        + ('p=os.fork()\nif p==0:\n'
           + (' os.setsid()\n' if kind == 'escape' else '')
           + f' Path({str(root/"descendant")!r}).write_text(str(os.getpid()))\n'
           + ' time.sleep(1.5)\n'
           + f' Path({str(root/"side-effect")!r}).write_text("synthetic")\n'
           + ' os._exit(0)\n' if kind != 'direct' else '')
        + f'Path({str(root/"ready")!r}).write_text(str(os.getpid()))\n'
        + 'time.sleep(1.5)\n'
        + f'Path({str(root/"side-effect")!r}).write_text("synthetic")\n'
        + 'time.sleep(3)\n')
    # Executable is the current interpreter; argv prefix supplies synthetic file.
    class Synthetic(Capabilities):
        def ui_send(self, argv, body, cancelled):
            return super().ui_send([self.cli, str(script)], body, cancelled)
    gd = root/'gate'; gd.mkdir(mode=0o700)
    g = Gate(gd, lambda:999000000000); g.initialize(); g.activate('new')
    s = dict(cli_path=sys.executable, cli_profile=CFG.cli_profile, live_enabled=True,
             reaction_enabled=False, progress_card_enabled=True)
    cap = Synthetic(s, True); p = Progress(s, cap.send)
    b = Bridge(root/'bridge.sqlite', CFG, lambda:1002, g, 'new', p)
    b.accept(event(), lambda x:200)
    wait(lambda:(root/'ready').exists())
    if kind != 'direct': wait(lambda:(root/'descendant').exists())
    return b, p, g


def owner(root):
    b, p, g = setup(root, 'direct')
    wait(lambda:(root/'close').exists())
    result = b.close()
    (root/'closed').write_text(json.dumps({'drained': result}))
    # Normal interpreter exit while gate DB remains locked by the parent.


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ui-boundary-')
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(cleanup)

    def check_cancel(self, kind, shutdown=False):
        b, p, g = setup(self.root, kind)
        try:
            pids = [int((self.root/n).read_text()) for n in ('ready','descendant')]
            if shutdown:
                p.shutdown(); self.assertTrue(p.wait_idle(4)); self.assertTrue(p.shutdown())
            g.pause()
            self.assertTrue(all(gone(pid) for pid in pids))
            with g.db() as db:
                self.assertEqual(db.execute('select count(*) from operations').fetchone()[0], 0)
            time.sleep(1.6)
            self.assertFalse((self.root/'side-effect').exists())
            print('PROOF', kind, 'shutdown' if shutdown else 'pause',
                  'pids=', pids, 'all reaped; operations=0; no side effect', flush=True)
        finally: b.close()

    def test_fork_pause_p1_1(self): self.check_cancel('fork')
    def test_fork_shutdown(self): self.check_cancel('fork', True)
    def test_setsid_adoption(self): self.check_cancel('escape')

    def test_owner_exit_gate_busy_p1_2(self):
        proc = subprocess.Popen([sys.executable, '-I', '-B', __file__, '--owner', str(self.root)],
                                env={}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        db = None
        try:
            wait(lambda:(self.root/'ready').exists())
            pid = int((self.root/'ready').read_text())
            db = sqlite3.connect(self.root/'gate/gate.sqlite', isolation_level=None)
            db.execute('BEGIN EXCLUSIVE'); time.sleep(.15)
            (self.root/'close').touch()
            proc.communicate(timeout=4)
            self.assertEqual(proc.returncode, 0)
            # Supervisor continues cleanup even after owner has normally exited.
            wait(lambda:gone(pid))
            db.rollback(); db.close(); db = None
            g = Gate(self.root/'gate')
            with g.db() as con:
                ops = con.execute('select count(*) from operations').fetchone()[0]
            closed = json.loads((self.root/'closed').read_text())
            if not closed['drained']:
                self.assertGreater(ops, 0)
                with self.assertRaises(Fenced): g.pause()
            time.sleep(1.6)
            self.assertFalse((self.root/'side-effect').exists())
            print('PROOF owner normal exit + exclusive gate lock: CLI reaped; '
                  'close=%s operations=%s; no side effect' % (closed, ops), flush=True)
        finally:
            if db is not None: db.rollback(); db.close()
            if proc.poll() is None: proc.kill()
            proc.wait(timeout=3)

    def test_supervisor_loss_retains_barrier(self):
        b, p, g = setup(self.root)
        try:
            pid = int((self.root/'ready').read_text())
            supervisor = int(Path('/proc/%d/stat' % pid).read_text().split()[3])
            os.kill(supervisor, signal.SIGKILL)
            self.assertTrue(p.wait_idle(4)); self.assertFalse(p.shutdown())
            with self.assertRaises(Fenced): g.pause()
            with self.assertRaises(Fenced): g.activate('new')
            # Our outer test subreaper owns the now-orphaned synthetic processes.
            cleanup()
            self.assertTrue(gone(pid))
            self.assertFalse((self.root/'side-effect').exists())
            with g.db() as db:
                self.assertGreater(db.execute('select count(*) from operations').fetchone()[0], 0)
            print('PROOF lost supervisor: no certificate or generation switch; '
                  'operations retained; exact synthetic children recovered', flush=True)
        finally: b.close()


if __name__ == '__main__':
    if sys.platform != 'linux' or ctypes.CDLL(None).prctl(36, 1, 0, 0, 0):
        raise SystemExit('Linux subreaper required')
    if len(sys.argv) > 1 and sys.argv[1] == '--owner':
        owner(Path(sys.argv[2]))
    else:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Integration))
        cleanup()
        print('CLEANUP PROOF: waitpid ECHILD; no synthetic descendants remain', flush=True)
        sys.exit(0 if result.wasSuccessful() else 1)
