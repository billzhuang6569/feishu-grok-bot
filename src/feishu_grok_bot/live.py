"""Explicit deployment-only capabilities. Importing performs no IO.

This module has not been exercised against any real service in this release.
"""
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .core import Config, Bridge, EVENT, validate_profile, stop_argv, normalize
from .ops import Health, Recovery


def cli_environment():
    """Linux official store locators only; never inherit credential providers.

    HOME is required; missing HOME fails closed.
    Official config/keychain sources document the two optional directory overrides.
    No store files are inspected here. Deployment must verify store availability.
    """
    env = {'PATH': '/usr/bin:/bin'}
    for key in ('HOME', 'LARKSUITE_CLI_CONFIG_DIR', 'LARKSUITE_CLI_DATA_DIR'):
        value = os.environ.get(key)
        if value:
            if not Path(value).is_absolute() or any(c in value for c in '\r\n\x00'):
                raise ValueError('invalid_store_locator')
            env[key] = value
    if 'HOME' not in env:
        raise ValueError('home_required')
    return env


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def load(path, live=False):
    p = Path(path)
    if not p.is_absolute() or p.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError('external_absolute_config_required')
    if p.is_symlink() or p.stat().st_mode & 0o077:
        raise ValueError('config_must_be_private')
    obj = json.loads(p.read_text())
    if live and obj.get('live_enabled') is not True:
        raise ValueError('live_guard_closed')
    return obj, Config(**obj['policy'], cli_profile=validate_profile(obj.get('cli_profile')))


class UIUnreaped(BaseException):
    """Retain gate crash barrier if child termination cannot be proved."""


class Capabilities:
    def __init__(self, settings, enabled=False):
        if not enabled or settings.get('live_enabled') is not True:
            raise ValueError('live_guard_closed')
        self.settings = settings
        self.cli = settings['cli_path']
        if not Path(self.cli).is_absolute():
            raise ValueError('cli_must_be_absolute')
        self.profile = validate_profile(settings.get('cli_profile'))

    def send(self, argv, body):
        # Only bridge-generated reply command; never caller-chosen destinations.
        done = subprocess.run([self.cli]+argv[1:], input=body.encode(), stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=30, check=False,
                              env=cli_environment())
        return json.loads(done.stdout)

    def ui_send(self, argv, body, cancelled):
        """One per-call subreaper; only its ECHILD proof permits lease exit.

        Text sends keep their existing capability and classification contract.
        Missing proof escapes, leaving the durable gate operation barrier.
        """
        if cancelled():
            return None
        control, cancel = os.pipe()
        proc = None
        try:
            proc = subprocess.Popen(
                [sys.executable, '-I', '-B', str(Path(__file__).with_name('ui_boundary.py')),
                 str(control), self.cli]+argv[1:],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=cli_environment(), pass_fds=(control,), start_new_session=True)
            os.close(control)
            control = None
            deadline = time.monotonic()+30
            first = True
            while True:
                if cancelled() or time.monotonic() >= deadline:
                    os.close(cancel)
                    cancel = None
                    break
                try:
                    out, _ = proc.communicate(input=body.encode() if first else None, timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    first = False
            if cancel is None:
                out, _ = proc.communicate(timeout=4)
            proof = json.loads(out)
            if proc.wait(timeout=1) != 0 or proof.get('drained') is not True:
                raise UIUnreaped()
            return proof.get('result')
        except BaseException as exc:
            # EOF leaves the independent supervisor able to finish cleanup even
            # if this worker/owner exits. Missing proof never releases the lease.
            if isinstance(exc, UIUnreaped):
                raise
            raise UIUnreaped() from None
        finally:
            try:
                for fd in (control, cancel):
                    if fd is not None:
                        os.close(fd)
                if proc is not None:
                    for name in ('stdin', 'stdout'):
                        pipe = getattr(proc, name, None)
                        if pipe is not None:
                            pipe.close()
            except Exception:
                # A local close error must never replace UIUnreaped with an
                # ordinary exception that the optional UI layer can swallow.
                raise UIUnreaped() from None

    def post(self, payload):
        # Deployment maps these names via protected service configuration.
        # No values are loaded at import, and no request parameters come from text.
        url = os.environ.get('FEISHU_ROUTINE_WEBHOOK_URL', '')
        auth = os.environ.get('FEISHU_ROUTINE_AUTHORIZATION', '')
        u = urlsplit(url)
        if (u.scheme != 'https' or u.hostname != 'api2.cursor.sh' or u.port not in (None,443)
            or u.username or u.password or u.query or u.fragment
            or not u.path.startswith('/automations/webhook/')
            or not auth.startswith('Bearer ') or any(x in auth for x in '\r\n\x00')):
            raise ValueError('invalid_restricted_mapping')
        req = Request(url, data=json.dumps(payload).encode(), method='POST',
                      headers={'Content-Type':'application/json','Authorization':auth})
        # Exactly one attempt, including 429/5xx and ambiguous connection errors.
        with build_opener(NoRedirect()).open(req,timeout=10) as response:
            return response.status

    def stop_bus(self, config):
        argv = stop_argv(config)
        return subprocess.run([self.cli]+argv[1:], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=15, check=False, env=cli_environment()).returncode


def exclusive(path):
    p = Path(path)
    p.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if p.is_symlink():
        raise ValueError('unsafe_lock')
    fd = p.open('a')
    p.chmod(0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        fd.close()
        raise
    return fd


def receive(settings, config, cap):
    """Single foreground owner, no daemon install, bounded reconnect on exit.

    Stale upstream requires operator diagnosis, not repeated destructive resets.
    A ready marker says nothing about upstream TCP freshness.
    """
    state = Path(settings['state_dir'])
    lock = exclusive(state/'receiver.lock')
    health, recovery = Health(process=True), Recovery()
    stopping = False
    proc = None
    bridge = None

    def stop(*_):
        nonlocal stopping
        stopping = True
        if bridge is not None and bridge.progress is not None:
            bridge.progress.shutdown()
        if proc is not None and proc.poll() is None:
            proc.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    from .progress import Progress
    bridge = Bridge(state/'bridge.sqlite',config)
    if settings.get('reaction_enabled') is True or settings.get('progress_card_enabled') is True:
        bridge.progress = Progress(settings, cap.send)
    try:
        cutover = bridge.require_cutover()
        from .gate import Gate
        bridge.gate = Gate(settings['shared_gate_dir'])
        bridge.mode = settings['gate_mode']
        bridge.gate.require_active(bridge.mode)
        bridge.recover()
    except BaseException:
        bridge.close()
        lock.close()
        raise
    try:
        while not stopping:
            proc = subprocess.Popen([cap.cli,'--profile',config.cli_profile,'event','consume',EVENT,'--as','bot'],
                                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                    env=cli_environment(),start_new_session=True)
            sel = selectors.DefaultSelector()
            sel.register(proc.stdout,selectors.EVENT_READ,'out')
            sel.register(proc.stderr,selectors.EVENT_READ,'err')
            buffers = {'out':b'', 'err':b''}
            started = time.time()
            try:
                while not stopping and sel.get_map():
                    for key,_ in sel.select(timeout=1):
                        chunk = os.read(key.fileobj.fileno(),65536)
                        if not chunk:
                            sel.unregister(key.fileobj)
                            continue
                        channel = key.data
                        buffers[channel] += chunk
                        if len(buffers[channel]) > 131072:
                            raise ValueError('oversize_consume_line')
                        while b'\n' in buffers[channel]:
                            line,buffers[channel] = buffers[channel].split(b'\n',1)
                            if channel == 'err':
                                if line.startswith(b'[event] ready'):
                                    health.local_bus = True
                                continue
                            try:
                                obj = json.loads(line)
                                if isinstance(obj,dict) and 'header' not in obj:
                                    # Trust only the pinned subprocess identity. Never
                                    # accept an absent timestamp as a new message.
                                    obj.setdefault('app_id',config.app)
                                    obj.setdefault('tenant_key',config.tenant)
                                    obj.setdefault('event_type',EVENT)
                                    if 'created_at' not in obj and 'create_time' in obj:
                                        obj['created_at'] = float(obj['create_time'])/1000
                                if float(normalize(obj).get('created_at',0)) < cutover:
                                    continue  # never process pre-start history
                                result = bridge.accept(obj,cap.post)
                                if result in ('accepted','unknown'):
                                    health.upstream_at = time.time()
                            except (ValueError,TypeError):
                                pass  # No raw stderr, payload or exception messages logged.
                    with bridge.transaction():
                        bridge.prune()
                    bridge.reconcile_progress()
                    observed = bridge.db.execute("SELECT at FROM observations WHERE kind='e2e'").fetchone()
                    health.e2e_at = observed[0] if observed else None
                    print(json.dumps(health.snapshot(time.time())),flush=True)
                    if not health.local_bus and time.time()-started > 30:
                        break
            finally:
                sel.close()
                if proc.stdin:
                    proc.stdin.close()
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # Never start a competitor while previous child may still run.
                    raise RuntimeError('consume_did_not_exit') from None
                finally:
                    proc.stdout.close()
                    proc.stderr.close()
            if stopping:
                break
            delay = recovery.disconnected(health)
            if delay is None:
                return 2
            # Time wait is local recovery, never polling messages.
            deadline = time.monotonic()+delay
            while not stopping and time.monotonic()<deadline:
                time.sleep(min(.2,max(0,deadline-time.monotonic())))
        return 0
    finally:
        drained = bridge.close()
        lock.close()
        if not drained:
            raise RuntimeError('ui_shutdown_unconfirmed')


def live_bridge(settings, config):
    from .gate import Gate
    mode = settings['gate_mode']
    if mode not in ('new', 'legacy-compatible'):
        raise ValueError('invalid_gate_mode')
    from .progress import Progress
    cap = Capabilities(settings, True)
    return Bridge(Path(settings['state_dir'])/'bridge.sqlite', config,
                  progress=(Progress(settings, cap.send) if settings.get('reaction_enabled') is True or settings.get('progress_card_enabled') is True else None),
                  gate=Gate(settings['shared_gate_dir']), mode=mode)
