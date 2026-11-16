"""Per-call Linux subreaper. No business imports, network, or persistent service.

The control pipe is held only by the owner. EOF also cancels on owner exit.
A proof is emitted only after waitpid reports ECHILD, never merely group exit.
"""
import ctypes
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time


def children():
    # This supervisor is single threaded; these are its exact kernel children.
    return [int(p) for p in Path('/proc/self/task/%d/children' % os.getpid()).read_text().split()]


def supervise(control, command):
    if sys.platform != 'linux' or ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0):
        return 2
    # No CLI starts before the subreaper is established.
    body = sys.stdin.buffer.read()
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
        source.write(body); source.seek(0)
        if select.select([control], [], [], 0)[0]:
            print(json.dumps({'drained': True, 'result': None}), flush=True)
            return 0
        child = subprocess.Popen(command, stdin=source, stdout=output,
                                 stderr=subprocess.DEVNULL, start_new_session=True,
                                 close_fds=True)
        deadline = time.monotonic()+30
        cancelled = False
        while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            if select.select([control], [], [], .02)[0] or time.monotonic() >= deadline:
                cancelled = True
                break
        # Kill the original group even if its leader has exited. Then repeatedly
        # kill adopted children: setsid/double-fork descendants are adopted when
        # their parents die. Never enumerate or kill unrelated system processes.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        while True:
            for pid in children():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break  # Kernel proof: this living subreaper has no descendants.
            if pid == 0:
                time.sleep(.005)
        output.seek(0)
        result = None
        if not cancelled:
            try:
                result = json.loads(output.read())
            except (ValueError, UnicodeError):
                pass
        print(json.dumps({'drained': True, 'result': result}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(supervise(int(sys.argv[1]), sys.argv[2:]))
