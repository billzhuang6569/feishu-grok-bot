# Third-party references

This project is an independent implementation, licensed under MIT (LICENSE).
No third-party implementation source has been copied or vendored. Python runtime
and tests use only the standard library. The separately installed official CLI is
an external deployment dependency, not bundled with this distribution.

| Reference | Fixed revision / license evidence | Use |
|---|---|---|
| larksuite/node-sdk | b188be60134d409b61259546bcf69c731d2b0b7c; LICENSE verified locally and fetched from official GitHub: MIT, Copyright (c) 2022 Lark Technologies Pte. Ltd. | API paths, types and protocol constraints only; no copied implementation |
| chenhg5/cc-connect | 0df18338c4838bff28f726fa4f28d4f7defdfa6a; fixed local tree has no LICENSE/COPYING text; online LICENSE returned HTTP 404 | Design reference for handles, progress and throttling only; README license claim is insufficient; copying remains prohibited |
| Feishu Open Platform documentation | Official public docs; not relicensed by this project | Protocol facts paraphrased, links and section locators in docs/PROTOCOL-SOURCES.md |
| Grok Bot public product docs | Official public docs; not bundled | Webhook capability research only; no internal interfaces or model API substitution |

MIT permits this project's publication without a further approval step. Reference
licenses do not grant permission to copy code whose complete license was not
verified. Full upstream MIT grant/disclaimer is available at the fixed SDK LICENSE
URL listed in the research record; the original file was read in full.
