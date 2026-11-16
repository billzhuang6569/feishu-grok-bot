#!/usr/bin/python3
"""Copy to a trusted admin-only location; never expose to Routine/model tools."""
from feishu_grok_bot.gate import Gate
import argparse

p = argparse.ArgumentParser()
p.add_argument('operation', choices=['initialize', 'pause', 'activate'])
p.add_argument('--mode', choices=['new', 'legacy-compatible'])
a = p.parse_args()
# Administrator reviews and fixes this constant; no payload/environment mapping.
g = Gate('/var/lib/feishu-shared-gate')
if a.operation == 'activate':
    g.activate(a.mode)
else:
    getattr(g, a.operation)()
