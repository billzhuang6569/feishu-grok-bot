"""Optional bridge stages. Durable intents, serialized UI writes, no retries.

stage is desired; card_stage is acknowledged. Unknown never means completed.
No tool telemetry, user content, credentials or independently constructed env.
"""
import hashlib
import json
from pathlib import Path
from .core import classify, ident, validate_profile

STAGES = {'received': 1, 'submitted': 2, 'returned': 3, 'replied': 4, 'failed': 5}
LABELS = {'received': '已接收', 'submitted': '已提交 Routine',
          'returned': '结果返回', 'replied': '已回复', 'failed': '失败或状态待核实'}
EMOJI_ALLOWLIST = frozenset({'OnIt', 'THINKING'})
TERMINAL = {4, 5}


def card(stage):
    return {'schema': '2.0', 'config': {'update_multi': True, 'width_mode': 'default'},
            'header': {'title': {'tag': 'plain_text', 'content': 'Bridge 处理进度'},
                       'subtitle': {'tag': 'plain_text', 'content': LABELS[stage]},
                       'template': 'blue'},
            'body': {'elements': [{'tag': 'markdown', 'content': 'Bridge 阶段：'+LABELS[stage]}]}}


class Progress:
    def __init__(self, settings, call):
        self.reaction = settings.get('reaction_enabled') is True
        self.cards = settings.get('progress_card_enabled') is True
        self.live = settings.get('live_enabled') is True
        self.emoji = settings.get('reaction_emoji', 'OnIt')
        if self.emoji not in EMOJI_ALLOWLIST:
            raise ValueError('emoji_not_allowlisted')
        self.cli = settings['cli_path']
        if not Path(self.cli).is_absolute():
            raise ValueError('cli_must_be_absolute')
        self.profile = validate_profile(settings.get('cli_profile'))
        # Production passes Capabilities.send, which supplies cli_environment().
        self.call = call

    def schema(self, db):
        db.execute('''CREATE TABLE IF NOT EXISTS progress (
            mid TEXT PRIMARY KEY, stage INTEGER, reaction TEXT, rid TEXT,
            card_state TEXT, card_mid TEXT, updated REAL)''')
        columns = {r[1] for r in db.execute('PRAGMA table_info(progress)')}
        # Under exclusive UI lock; preserves previous evidence and unknown barriers.
        for name, decl in [('card_stage', 'INTEGER DEFAULT 0'),
                           ('diagnostic', "TEXT DEFAULT ''"),
                           ('reaction_op', "TEXT DEFAULT ''"),
                           ('card_op', "TEXT DEFAULT ''"),
                           ('reaction_result', "TEXT DEFAULT ''"),
                           ('card_result', "TEXT DEFAULT ''")]:
            if name not in columns:
                db.execute(f'ALTER TABLE progress ADD COLUMN {name} {decl}')

    def advance(self, bridge, mid, stage):
        if not self.live or not (self.reaction or self.cards) or bridge.gate is None:
            return
        if stage not in STAGES or not ident(mid, 'om_'):
            return
        # Order: shared gate lease -> exclusive UI lock -> short DB transaction.
        # Main bridge transactions finish before feedback; no DB lock spans IO.
        # The gate's nested leases are shared; pause never waits with a DB txn.
        try:
            with bridge.gate.lease(bridge.mode, mid):
                with bridge.gate.lock(True, 'progress.lock'):
                    self.schema(bridge.db)
                    self._advance(bridge, mid, stage)
        except Exception:
            # No raw exception strings. Existing unknown intent remains durable.
            try:
                bridge.db.execute("UPDATE progress SET diagnostic='blocked_or_local_error' WHERE mid=?", (mid,))
            except Exception:
                pass

    def _advance(self, bridge, mid, stage):
        db = bridge.db
        row = db.execute('SELECT app,tenant,owner,chat,at,dispatch,reply FROM inbox WHERE mid=?', (mid,)).fetchone()
        c = bridge.cfg
        if not row or row[:4] != (c.app, c.tenant, c.owner, c.chat) or self.profile != c.cli_profile:
            return
        # Durable text outcome is authoritative, even after an ambiguous dispatch.
        if row[6] == 'sent':
            stage = 'replied'
        elif row[6] in ('unknown', 'failed') or bridge.clock()-row[4] >= c.reply_ttl:
            stage = 'failed'
        elif stage == 'replied':
            return  # caller cannot invent a successful terminal outcome
        with bridge.transaction():
            db.execute("INSERT OR IGNORE INTO progress(mid,stage,reaction,card_state,updated) VALUES(?,0,'none','none',0)", (mid,))
            old = self.row(db, mid)
            desired = STAGES[stage]
            if old['stage'] == STAGES['replied']:
                desired = old['stage']
            elif old['stage'] == STAGES['failed'] and stage != 'replied':
                desired = old['stage']
            elif desired not in TERMINAL:
                desired = max(desired, old['stage'])
            db.execute('UPDATE progress SET stage=? WHERE mid=?', (desired, mid))
        terminal = desired in TERMINAL
        stage = next(k for k, v in STAGES.items() if v == desired)
        if self.reaction and old['reaction'] == 'none' and not terminal:
            result = self.operation(bridge, mid, 'reaction', 'create', {'message_id': mid},
                                    {'reaction_type': {'emoji_type': self.emoji}})
            data = result.get('data') if isinstance(result, dict) else None
            rid = data.get('reaction_id') if isinstance(data, dict) else None
            if success(result) and isinstance(rid, str) and 0 < len(rid) <= 256 and not any(x in rid for x in '\r\n\x00'):
                db.execute("UPDATE progress SET reaction='active',rid=? WHERE mid=?", (rid, mid))
            elif success(result):
                db.execute("UPDATE progress SET reaction_result='missing_handle' WHERE mid=?", (mid,))
        old = self.row(db, mid)
        # Throttle only acknowledged nonterminal writes; terminal bypasses it.
        if (self.cards and old['card_state'] in ('none', 'active')
                and old['card_stage'] != desired
                and (terminal or bridge.clock()-old['updated'] >= 1)):
            method = 'patch' if old['card_mid'] else 'reply'
            result = self.operation(bridge, mid, 'card_state', method,
                                    {'message_id': old['card_mid'] or mid},
                                    {'content': json.dumps(card(stage), ensure_ascii=False)})
            if method == 'reply':
                try:
                    state, out = classify(result, c.chat)
                    confirmed = state == 'sent'
                except Exception:
                    confirmed, out = False, None
            else:
                confirmed, out = success(result), old['card_mid']
            if confirmed:
                db.execute("UPDATE progress SET card_state='active',card_mid=?,card_stage=?,updated=? WHERE mid=?",
                           (out, desired, bridge.clock(), mid))
        if terminal:
            current = self.row(db, mid)
            if self.reaction and current['reaction'] == 'active' and current['rid']:
                result = self.operation(bridge, mid, 'reaction', 'delete',
                                        {'message_id': mid, 'reaction_id': current['rid']}, {})
                if success(result):
                    db.execute("UPDATE progress SET reaction='removed' WHERE mid=?", (mid,))
        current = self.row(db, mid)
        pending = ((self.reaction and current['reaction'] not in ('none', 'removed') and terminal)
                   or (self.cards and current['card_stage'] != desired)
                   or current['reaction'] == 'unknown' or current['card_state'] == 'unknown')
        db.execute('UPDATE progress SET diagnostic=? WHERE mid=?',
                   ('unresolved_no_automatic_retry' if pending else '', mid))

    @staticmethod
    def row(db, mid):
        cursor = db.execute('SELECT * FROM progress WHERE mid=?', (mid,))
        return dict(zip((d[0] for d in cursor.description), cursor.fetchone()))

    def operation(self, bridge, mid, column, method, params, data):
        assert column in ('reaction', 'card_state')
        op = 'reaction_op' if column == 'reaction' else 'card_op'
        outcome = 'reaction_result' if column == 'reaction' else 'card_result'
        # Autocommit durable intent BEFORE IO. Crash / 403 / 429 never replay.
        bridge.db.execute(f"UPDATE progress SET {column}='unknown',{op}=?,{outcome}='unconfirmed',diagnostic='intent_unconfirmed' WHERE mid=?", (method, mid))
        argv = [self.cli, '--profile', self.profile, 'im']
        if method == 'reply':
            key = hashlib.sha256(('progress:'+mid).encode()).hexdigest()[:32]
            argv += ['+messages-reply', '--as', 'bot', '--message-id', params['message_id'],
                     '--msg-type', 'interactive', '--content', data['content'], '--idempotency-key', key]
        else:
            argv += ['reactions' if column == 'reaction' else 'messages', method,
                     '--as', 'bot', '--params', json.dumps(params)]
            if method != 'delete':
                argv += ['--data', json.dumps(data)]
        argv += ['--json']
        try:
            result = self.call(argv, '')
            tag = 'envelope_confirmed' if success(result) else 'unknown'
            if isinstance(result, dict):
                error = result.get('error')
                code = error.get('code') if isinstance(error, dict) else result.get('code')
                if not success(result) and code in (403, '403', 99991672, 99991679):
                    tag = 'permission_denied'
                elif not success(result) and code in (429, '429', 230020):
                    tag = 'rate_limited'
                elif result.get('ok') is False:
                    tag = 'rejected'
        except Exception:
            result, tag = None, 'exception'
        bridge.db.execute(f'UPDATE progress SET {outcome}=? WHERE mid=?', (tag, mid))
        return result


def success(obj):
    if not isinstance(obj, dict) or obj.get('ok') is False:
        return False
    if 'code' in obj and (type(obj['code']) not in (int, str) or obj['code'] not in (0, '0')):
        return False
    if any(x.get(k) for x in (obj, obj.get('data') if isinstance(obj.get('data'), dict) else {}, obj.get('meta') if isinstance(obj.get('meta'), dict) else {}) for k in ('dry_run', 'dry-run', 'preview', 'request')):
        return False
    return obj.get('ok') is True or type(obj.get('code')) in (int, str) and obj.get('code') in (0, '0')
