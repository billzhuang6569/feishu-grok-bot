#!/bin/sh
set -eu
# Administrator edits constants, reviews, then COPIES outside this repository.
ROOT=/opt/feishu-grok-bot
CONFIG=/etc/feishu-grok-bot/private.json
[ "$#" -eq 2 ] && [ "$1" = --in-reply-to ] || exit 3
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
# stdin is inherited without reading/re-encoding it in the launcher.
exec /usr/bin/python3 -m feishu_grok_bot reply --config "$CONFIG" --live --in-reply-to "$2"
