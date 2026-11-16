# Contributing

Run `PYTHONDONTWRITEBYTECODE=1 bin/run-tests` and `bin/selfcheck` before review.
Use synthetic fixtures only; never connect tests to services. Preserve gate,
unknown/no-retry and target verification guarantees. Keep src/tests/templates and
technical docs identical to the reviewed candidate. No credentials, real configs,
state or logs in patches. Contributions use the MIT license. Use the [public repository](https://github.com/billzhuang6569/feishu-grok-bot)
for issues and pull requests. Public history must start with a fresh import of
the clean allowlist candidate and ALLOWLIST.json; never import the original
development history or its git metadata.
