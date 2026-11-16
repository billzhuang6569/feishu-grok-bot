# 发布 allowlist

仅下列文件及候选 ALLOWLIST.json 可进入干净初始导入。每项 SHA-256 在 ALLOWLIST.json；manifest 不自哈希。本清单共 46 项，加 ALLOWLIST.json 为 47 个公开文件。全部代码、合成测试、部署模板均完整导出；原历史不可上传。

- `.gitignore`
- `CONTRIBUTING.md`
- `HANDOFF.md`
- `LICENSE`
- `README.md`
- `SECURITY.md`
- `THIRD_PARTY_NOTICES.md`
- `bin/context`
- `bin/receive`
- `bin/reply`
- `bin/run-integration`
- `bin/run-tests`
- `bin/selfcheck`
- `bin/stop-bus`
- `config/example.json`
- `docs/COMPATIBILITY.md`
- `docs/DEPLOY.md`
- `docs/OPEN-SOURCE-AUDIT.md`
- `docs/PROGRESS.md`
- `docs/PROTOCOL-SOURCES.md`
- `docs/RELEASE-ALLOWLIST.md`
- `docs/RELEASE-MAPPING.md`
- `pyproject.toml`
- `requirements.lock`
- `src/feishu_grok_bot/__init__.py`
- `src/feishu_grok_bot/__main__.py`
- `src/feishu_grok_bot/core.py`
- `src/feishu_grok_bot/gate.py`
- `src/feishu_grok_bot/live.py`
- `src/feishu_grok_bot/ops.py`
- `src/feishu_grok_bot/progress.py`
- `src/feishu_grok_bot/ui_boundary.py`
- `templates/gate-admin.py`
- `templates/trusted-context.sh`
- `templates/trusted-reply.sh`
- `tests/run.py`
- `tests/run_integration.py`
- `tests/selfcheck.py`
- `tests/test_bridge.py`
- `tests/test_candidate_selfcheck.py`
- `tests/test_capabilities.py`
- `tests/test_phase2.py`
- `tests/test_phase3.py`
- `tests/test_phase4.py`
- `tests/test_receiver.py`
- `tests/test_ui_isolation.py`

新增公开执行边界与独立合成 integration 入口：`src/feishu_grok_bot/ui_boundary.py`、`tests/run_integration.py`、`bin/run-integration`（100755）。unit 保持禁止真实子进程；integration 不访问网络、真实业务 CLI 或凭据，精确清理合成执行树。
