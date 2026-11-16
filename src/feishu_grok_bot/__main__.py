import argparse
import json
from pathlib import Path
import sys
from .core import Bridge
from .live import load, Capabilities, receive, exclusive, live_bridge


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['reply','context','receive','stop-bus','mark-cutover'])
    p.add_argument('--config',default='config/local.json')
    p.add_argument('--live',action='store_true')
    p.add_argument('--in-reply-to')
    p.add_argument('--chat-id')
    p.add_argument('--cutover-at',type=float)
    a = p.parse_args(argv)
    if a.command not in ('context','mark-cutover') and not a.live:
        print('{"ok":false,"error":"live_guard_closed"}')
        return 3
    if not Path(a.config).is_absolute():
        print('{"ok":false,"error":"absolute_config_required"}')
        return 3
    if a.cutover_at is not None and a.command != 'mark-cutover':
        p.error('unsupported arguments')
    if a.command != 'reply' and a.in_reply_to or a.command != 'context' and a.chat_id:
        p.error('unsupported arguments')
    try:
        settings,config = load(a.config,live=a.command not in ('context','mark-cutover'))
        if a.command == 'receive':
            return receive(settings,config,Capabilities(settings,a.live))
        if a.command == 'stop-bus':
            # Shared lock prevents bus stop while our receiver is consuming.
            with exclusive(Path(settings['state_dir'])/'receiver.lock'):
                return Capabilities(settings,a.live).stop_bus(config)
        if a.command == 'mark-cutover':
            with exclusive(Path(settings['state_dir'])/'receiver.lock'):
                bridge = Bridge(Path(settings['state_dir'])/'bridge.sqlite',config)
                try:
                    bridge.mark_cutover(a.cutover_at)
                finally:
                    bridge.close()
            print('{"ok":true,"cutover":"marked"}')
            return 0
        bridge = (live_bridge(settings, config) if a.command == 'reply' else
                  Bridge(Path(settings['state_dir'])/'bridge.sqlite',config))
        try:
            if a.command == 'context':
                result = bridge.context(a.chat_id)
                code = 0 if result['ok'] else 3
            else:
                body = sys.stdin.buffer.read(16385).decode('utf-8')
                result = bridge.reply(a.in_reply_to,body,Capabilities(settings,a.live).send)
                code = result.pop('exit')
            print(json.dumps(result,ensure_ascii=False))
            return code
        finally:
            bridge.close()
    except Exception:
        print('{"ok":false,"error":"local_operation_refused_or_failed"}')
        return 3


if __name__ == '__main__':
    sys.exit(main())
