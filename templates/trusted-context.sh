#!/bin/sh
set -eu
ROOT=/opt/feishu-grok-bot
CONFIG=/etc/feishu-grok-bot/private.json
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
case "$#" in
  0) exec /usr/bin/python3 -m feishu_grok_bot context --config "$CONFIG" ;;
  2) [ "$1" = --chat-id ] || exit 3
     exec /usr/bin/python3 -m feishu_grok_bot context --config "$CONFIG" --chat-id "$2" ;;
  *) exit 3 ;;
esac
