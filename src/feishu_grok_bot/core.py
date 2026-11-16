"""Durable conservative bridge; transports are explicit injected capabilities.

No network imports, environment reads, credentials, or subprocesses here.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path

EVENT = 'im.message.receive_v1'


def ident(value, prefix):
    return isinstance(value, str) and bool(re.fullmatch(prefix + r'[A-Za-z0-9_-]{1,128}', value))


def validate_profile(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('invalid_cli_profile')
    return value


@dataclass(frozen=True, repr=False)
class Config:
    app: str
    tenant: str
    owner: str
    chat: str
    cli_profile: str
    context_ttl: int = 86400
    reply_ttl: int = 600
    max_age: int = 120
    context_items: int = 20
    context_bytes: int = 16384
    budget: int = 30

    def __post_init__(self):
        validate_profile(self.cli_profile)
        for value, prefix in [(self.app, 'cli_'), (self.owner, 'ou_'), (self.chat, 'oc_')]:
            if not ident(value, prefix):
                raise ValueError('invalid_config_identity')
        if not isinstance(self.tenant, str) or not self.tenant or len(self.tenant) > 128:
            raise ValueError('invalid_config_tenant')
        for v in [self.context_ttl, self.reply_ttl, self.max_age, self.context_items, self.context_bytes, self.budget]:
            if type(v) is not int or not 0 < v <= 1000000:
                raise ValueError('invalid_config_limit')

    def __repr__(self):
        return 'Config(redacted)'


def normalize(obj):
    if not isinstance(obj, dict):
        raise ValueError('invalid_event')
    if 'header' in obj:
        h, e = obj['header'], obj.get('event', {})
        m, s = e.get('message', {}), e.get('sender', {})
        content = json.loads(m.get('content', '{}'))
        return dict(event_id=h.get('event_id'), event_type=h.get('event_type'),
                    app_id=h.get('app_id'), tenant_key=h.get('tenant_key'),
                    message_id=m.get('message_id'), chat_id=m.get('chat_id'),
                    sender_open_id=s.get('sender_id', {}).get('open_id'),
                    sender_type=s.get('sender_type'), chat_type=m.get('chat_type'),
                    message_type=m.get('message_type'), text=content.get('text'),
                    created_at=float(m.get('create_time', 0))/1000,
                    thread_id=m.get('thread_id', ''))
    # Official CLI flattening lacks app/tenant. Only Receiver's pinned local
    # process boundary may supply them; arbitrary fixtures must include them.
    x = dict(obj)
    x['sender_open_id'] = x.get('sender_open_id', x.get('sender_id'))
    x['text'] = x.get('text', x.get('content'))
    return x


def classify(obj, chat):
    if not isinstance(obj, dict):
        return 'unknown', None
    if any(x.get(k) for x in (obj, obj.get('data') if isinstance(obj.get('data'), dict) else {}, obj.get('meta') if isinstance(obj.get('meta'), dict) else {}) for k in ('dry_run', 'dry-run', 'preview', 'request')):
        return 'unknown', None
    if obj.get('ok') is False or ('code' in obj and type(obj['code']) in (int, str) and obj['code'] not in (0, '0')):
        return 'failed', None
    if 'code' in obj and type(obj['code']) not in (int, str):
        return 'unknown', None
    success = obj.get('ok') is True or (type(obj.get('code')) in (int, str) and obj.get('code') in (0, '0'))
    if not success:
        return 'unknown', None
    d = obj.get('data')
    if not isinstance(d, dict):
        return 'unknown', None
    candidates = [d]
    if isinstance(d.get('message'), dict):
        candidates.append(d['message'])
    mids = {x[k] for x in candidates for k in ('message_id', 'id') if x.get(k)}
    chats = {x.get('chat_id') for x in candidates if x.get('chat_id')}
    # Stricter than legacy: missing target proof is unknown, never success.
    if len(mids) != 1 or chats != {chat} or not ident(next(iter(mids)), 'om_'):
        return 'unknown', None
    return 'sent', next(iter(mids))


def reply_argv(mid, thread='', *, profile):
    validate_profile(profile)
    if not ident(mid, 'om_'):
        raise ValueError('invalid_message_id')
    key = 'zgrpl-' + hashlib.sha256(mid.encode()).hexdigest()[:42]
    argv = ['lark-cli', '--profile', profile, 'im', '+messages-reply', '--as', 'bot',
            '--message-id', mid, '--text', '-', '--idempotency-key', key, '--json']
    if thread and thread != mid:
        argv += ['--reply-in-thread']
    return argv


def stop_argv(config):
    return ['lark-cli', '--profile', config.cli_profile, 'event', 'stop', '--app-id', config.app, '--json']


class Bridge:
    def __init__(self, path, config, clock=time.time, gate=None, mode=None, progress=None):
        self.cfg, self.clock = config, clock
        self.gate, self.mode = gate, mode
        self.progress = progress
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('unsafe_state_path')
        if path.parent.stat().st_mode & 0o077 or path.parent.stat().st_uid != os.getuid():
            raise ValueError('state_directory_must_be_private')
        self.path = path
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        path.chmod(0o600)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS inbox (
          mid TEXT PRIMARY KEY, eid TEXT UNIQUE NOT NULL, app TEXT, tenant TEXT,
          owner TEXT, chat TEXT, thread TEXT, at REAL, dispatch TEXT, reply TEXT,
          outbound TEXT);
        CREATE TABLE IF NOT EXISTS context (
          seq INTEGER PRIMARY KEY, role TEXT, mid TEXT, at REAL, text TEXT,
          UNIQUE(role,mid));
        CREATE TABLE IF NOT EXISTS observations (kind TEXT PRIMARY KEY, at REAL);
        CREATE TABLE IF NOT EXISTS cutover (id INTEGER PRIMARY KEY CHECK(id=1), at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY CHECK(id=1), fingerprint TEXT);
        ''')
        fp = hashlib.sha256(json.dumps([config.app, config.tenant, config.owner, config.chat]).encode()).hexdigest()
        self.db.execute('INSERT OR IGNORE INTO binding VALUES(1,?)', (fp,))
        if self.db.execute('SELECT fingerprint FROM binding').fetchone()[0] != fp:
            self.db.close()
            raise ValueError('state_binding_mismatch')

    def mark_cutover(self, at):
        """One-time offline gate, under receiver lock, for a genuinely empty new DB."""
        if not math.isfinite(at) or at <= 0 or at > self.clock():
            raise ValueError('invalid_cutover')
        with self.transaction():
            if self.db.execute('SELECT 1 FROM inbox').fetchone() or self.db.execute('SELECT 1 FROM cutover').fetchone():
                raise ValueError('cutover_requires_unmarked_empty_database')
            self.db.execute('INSERT INTO cutover VALUES(1,?)', (at,))

    def require_cutover(self):
        row = self.db.execute('SELECT at FROM cutover WHERE id=1').fetchone()
        if not row or not math.isfinite(row[0]) or not 0 < row[0] <= self.clock():
            raise ValueError('cutover_gate_required')
        return row[0]

    def close(self):
        drained = True
        if self.progress is not None:
            drained = self.progress.shutdown(self)
        self.db.close()
        return drained

    def recover(self):
        # Only call while holding the lifetime receiver lock, before serving.
        # Never turn pending or unknown back into an eligible request.
        with self.transaction():
            self.db.execute("UPDATE inbox SET dispatch='unknown' WHERE dispatch='pending'")
            self.db.execute("UPDATE inbox SET reply='unknown' WHERE reply='pending'")
            self.prune()
        self.reconcile_progress()

    def reconcile_progress(self):
        if self.progress is None:
            return
        for mid, at, dispatch, reply in self.db.execute(
                "SELECT mid,at,dispatch,reply FROM inbox").fetchall():
            if reply == "sent":
                self.feedback(mid, "replied")
            elif reply in ("failed", "unknown") or dispatch == "unknown" or self.clock()-at >= self.cfg.reply_ttl:
                self.feedback(mid, "failed")

    def transaction(self):
        return Transaction(self.db)

    def prune(self):
        self.db.execute('DELETE FROM context WHERE at<=?', (self.clock()-self.cfg.context_ttl,))
        self.db.execute('DELETE FROM context WHERE seq NOT IN (SELECT seq FROM context ORDER BY seq DESC LIMIT ?)', (self.cfg.context_items,))
        while True:
            rows = self.db.execute('SELECT seq,role,mid,at,text FROM context ORDER BY seq').fetchall()
            public = [dict(role=r,message_id=m,at=datetime.fromtimestamp(a,timezone.utc).isoformat(),text=t) for _,r,m,a,t in rows]
            if not rows or len(json.dumps(dict(ok=True,chat_id=self.cfg.chat,items=public), ensure_ascii=False).encode()) <= self.cfg.context_bytes:
                break
            self.db.execute('DELETE FROM context WHERE seq=?', (rows[0][0],))

    def add_context(self, role, mid, text):
        self.db.execute('INSERT OR IGNORE INTO context(role,mid,at,text) VALUES(?,?,?,?)', (role, mid, self.clock(), text))
        self.prune()

    def context(self, chat=None):
        if chat not in (None, self.cfg.chat):
            return {'ok': False, 'error': 'unverified_target'}
        with self.transaction():
            self.prune()
            items = [dict(role=r, message_id=m, at=datetime.fromtimestamp(a, timezone.utc).isoformat(), text=t)
                     for r,m,a,t in self.db.execute('SELECT role,mid,at,text FROM context ORDER BY seq')]
        return dict(ok=True, chat_id=self.cfg.chat, items=items)

    def accept(self, raw, post):
        return self._accept(raw, post)

    def _accept(self, raw, post):
        try:
            e = normalize(raw)
            c, now = self.cfg, self.clock()
            valid = (e.get('app_id') == c.app and e.get('tenant_key') == c.tenant
                     and e.get('event_type') == EVENT and e.get('sender_open_id') == c.owner
                     and e.get('chat_id') == c.chat and e.get('sender_type') == 'user'
                     and e.get('chat_type') == 'p2p' and e.get('message_type') == 'text'
                     and ident(e.get('message_id'), 'om_') and isinstance(e.get('event_id'), str)
                     and 0 < len(e['event_id']) <= 128 and isinstance(e.get('text'), str)
                     and 0 < len(e['text'].encode()) <= 16384
                     and isinstance(e.get('thread_id', ''), str)
                     and len(e.get('thread_id', '')) <= 128
                     and 0 <= now-float(e.get('created_at', 0)) <= c.max_age)
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
            valid = False
        if not valid:
            return 'rejected'
        gate = self.db.execute('SELECT at FROM cutover WHERE id=1').fetchone()
        if gate and float(e['created_at']) < gate[0]:
            return 'rejected'
        if self.gate is not None:
            from .gate import Fenced
            try:
                with self.gate.lease(self.mode, e['message_id'], e.get('created_at'), accept=True):
                    return self._dispatch(e, now, c, post)
            except Fenced:
                return 'rejected'
        return self._dispatch(e, now, c, post)

    def _dispatch(self, e, now, c, post):
        mid = e['message_id']
        with self.transaction():
            if self.db.execute('SELECT 1 FROM inbox WHERE mid=? OR eid=? OR outbound=?', (mid,e['event_id'],mid)).fetchone():
                return 'duplicate'
            if self.db.execute('SELECT COUNT(*) FROM inbox WHERE at>?', (now-3600,)).fetchone()[0] >= c.budget:
                return 'budget_exhausted'
            self.db.execute('INSERT INTO inbox VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',
                            (mid,e['event_id'],c.app,c.tenant,c.owner,c.chat,e.get('thread_id',''),now,'pending','none'))
            self.add_context('owner', mid, e['text'])
        self.feedback(mid, 'received')
        payload = {k: e.get(k, '') for k in ['event_id','message_id','chat_id','sender_open_id','chat_type','thread_id','text']}
        payload.update(verified_at=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                       source='lark-cli-event-consume', app_id=c.app, profile=c.cli_profile)
        try:
            status = post(payload)
            state = 'accepted' if type(status) is int and status == 200 else 'unknown'
        except Exception:
            state = 'unknown'
        self.db.execute('UPDATE inbox SET dispatch=? WHERE mid=?', (state, mid))
        self.feedback(mid, 'submitted' if state == 'accepted' else 'failed')
        return state

    def feedback(self, mid, stage):
        if self.progress is not None and self.gate is not None:
            try:
                self.progress.submit(self, mid, stage)
            except Exception:
                pass  # Optional UI must never change primary reply classification.

    def reply(self, mid, body, send):
        if self.gate is None:
            return self._reply(mid, body, send)
        from .gate import Fenced
        try:
            with self.gate.lease(self.mode, mid):
                return self._reply(mid, body, send)
        except Fenced:
            return dict(ok=False, error='generation_fenced', exit=3)

    def _reply(self, mid, body, send):
        if not ident(mid, 'om_') or not isinstance(body, str) or not body.strip() or len(body.encode()) > 16384:
            return dict(ok=False, error='invalid_input', exit=3)
        with self.transaction():
            rec = self.db.execute('SELECT owner,chat,thread,at,dispatch,reply FROM inbox WHERE mid=?', (mid,)).fetchone()
            if not rec or rec[:2] != (self.cfg.owner, self.cfg.chat) or self.clock()-rec[3] >= self.cfg.reply_ttl:
                return dict(ok=False, error='unverified_or_expired_target', exit=3)
            if rec[5] != 'none':
                return dict(ok=False, error='already_replied_or_pending', exit=4)
            # pending/unknown dispatch can already have awakened the Routine.
            self.db.execute("UPDATE inbox SET reply='pending' WHERE mid=?", (mid,))
        self.feedback(mid, 'returned')
        try:
            state, outbound = classify(send(reply_argv(mid,rec[2], profile=self.cfg.cli_profile), body), self.cfg.chat)
        except Exception:
            state, outbound = 'unknown', None
        with self.transaction():
            self.db.execute('UPDATE inbox SET reply=?,outbound=? WHERE mid=?', (state,outbound,mid))
            if state == 'sent':
                self.db.execute("INSERT OR REPLACE INTO observations VALUES('e2e',?)", (self.clock(),))
                self.add_context('bot',outbound,body)
        self.feedback(mid, 'replied' if state == 'sent' else 'failed')
        return dict(ok=state=='sent', in_reply_to=mid, chat_id=self.cfg.chat,
                    outbound_message_id=outbound, reply_status=state,
                    exit={'sent':0,'failed':1,'unknown':5}[state])


class Transaction:
    def __init__(self, db):
        self.db = db
    def __enter__(self):
        self.db.execute('BEGIN IMMEDIATE')
    def __exit__(self, typ, value, tb):
        self.db.execute('ROLLBACK' if typ else 'COMMIT')
