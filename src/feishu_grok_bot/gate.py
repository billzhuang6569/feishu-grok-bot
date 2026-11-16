"""Trusted local generation fence. No payload-selected paths or generations.

SQLite commits pause intent before flock drain. A shared lease spans the entire
external operation and its durable outcome. Lock files must never be replaced.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import fcntl
import os
from pathlib import Path
import sqlite3
import time
import uuid


class Fenced(ValueError):
    pass


def event_ms(value):
    try:
        if isinstance(value, bool) or value is None:
            raise ValueError()
        n = Decimal(str(value)) * 1000
        if not n.is_finite() or n <= 0 or n != n.to_integral_value():
            raise ValueError()
        return int(n)
    except (InvalidOperation, ValueError, TypeError):
        raise Fenced('exact_millisecond_event_time_required') from None


class Gate:
    def __init__(self, directory, clock_ns=time.time_ns):
        self.root = Path(directory)
        self.clock_ns = clock_ns
        if not self.root.is_absolute() or self.root.is_symlink():
            raise Fenced('absolute_private_gate_required')
        # Preprovisioned trusted directory; missing gate is never auto-created.
        for p in [self.root, *self.root.parents]:
            st = p.stat()
            if p.is_symlink() or (st.st_mode & 0o022 and not st.st_mode & 0o1000):
                raise Fenced('unsafe_gate_ancestor')
        st = self.root.stat()
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise Fenced('private_gate_required')

    @contextmanager
    def db(self):
        p = self.root/'gate.sqlite'
        if p.is_symlink():
            raise Fenced('unsafe_gate_database')
        if p.exists() and (p.stat().st_uid != os.getuid() or p.stat().st_mode & 0o077):
            raise Fenced('private_gate_database_required')
        con = sqlite3.connect(p, timeout=30, isolation_level=None)
        p.chmod(0o600)
        con.execute('PRAGMA synchronous=FULL')
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def lock(self, exclusive=False, name='drain.lock'):
        p = self.root/name
        fd = os.open(p, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            st = os.fstat(fd)
            if st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise Fenced('private_gate_lock_required')
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            os.close(fd)

    def require_active(self, mode):
        with self.db() as db:
            row = db.execute('SELECT mode,paused FROM control WHERE id=1').fetchone()
            if row != (mode, 0) or mode not in ('new', 'legacy-compatible'):
                raise Fenced('inactive_generation')

    def initialize(self):
        with self.lock(True, 'admin.lock'), self.lock(True), self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS control(id INTEGER PRIMARY KEY CHECK(id=1),
              generation INTEGER, mode TEXT, cutoff_ms INTEGER, paused INTEGER);
            CREATE TABLE IF NOT EXISTS claims(mid TEXT PRIMARY KEY, generation INTEGER);
            CREATE TABLE IF NOT EXISTS operations(token TEXT PRIMARY KEY);
            ''')
            db.execute('INSERT OR IGNORE INTO control VALUES(1,0,\'closed\',0,1)')

    def pause(self):
        with self.lock(True, 'admin.lock'):
            with self.db() as db:
                if db.execute('UPDATE control SET paused=1 WHERE id=1').rowcount != 1:
                    raise Fenced('missing_gate')
            # Return is the drain certificate; a crash before return is not one.
            with self.lock(True), self.db() as db:
                if db.execute('SELECT 1 FROM operations').fetchone():
                    raise Fenced('crashed_operation_requires_external_reconciliation')

    def activate(self, mode):
        if mode not in ('new', 'legacy-compatible'):
            raise Fenced('invalid_mode')
        with self.lock(True, 'admin.lock'), self.lock(True), self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM operations').fetchone():
                raise Fenced('unresolved_operation')
            row = db.execute('SELECT generation,cutoff_ms,paused FROM control WHERE id=1').fetchone()
            if not row or row[2] != 1:
                raise Fenced('pause_required')
            # Reject the entire boundary millisecond, including future rounding.
            cutoff = (self.clock_ns()+999999)//1000000
            if cutoff <= row[1]:
                raise Fenced('clock_must_advance')
            db.execute('UPDATE control SET generation=?,mode=?,cutoff_ms=?,paused=0 WHERE id=1',
                       (row[0]+1, mode, cutoff))
            db.commit()

    @contextmanager
    def lease(self, mode, mid, created_at=None, accept=False):
        with self.lock(), self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT generation,mode,cutoff_ms,paused FROM control WHERE id=1').fetchone()
            if not row or row[3] or row[1] != mode:
                raise Fenced('inactive_generation')
            if accept:
                if event_ms(created_at) <= row[2]:
                    raise Fenced('before_activation_boundary')
                if db.execute('SELECT 1 FROM claims WHERE mid=?', (mid,)).fetchone():
                    raise Fenced('claimed_message')
                db.execute('INSERT INTO claims VALUES(?,?)', (mid,row[0]))
            elif db.execute('SELECT generation FROM claims WHERE mid=?', (mid,)).fetchone() != (row[0],):
                raise Fenced('cross_generation_reply')
            token = uuid.uuid4().hex
            db.execute('INSERT INTO operations VALUES(?)', (token,))
            db.commit()
            try:
                yield
            except BaseException:
                # An escaping exception is uncertain; retain the barrier.
                raise
            else:
                db.execute('DELETE FROM operations WHERE token=?', (token,))
