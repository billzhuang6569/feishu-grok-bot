# 工作树与候选映射

| 范围 | 映射与差异 |
|---|---|
| src/** | 全部 Python 源码逐字节一致，无导出替换 |
| tests/run.py、全部 test_*.py | 全部纯离线合成测试逐字节一致，包含 bridge/capabilities/receiver/phase2/phase3/phase4/ui_isolation |
| tests/selfcheck.py | 唯一测试辅助文件差异：受限工作树另做显式旧源码映射核验；公开候选只核对自身 allowlist、散列和静态扫描 |
| bin/** | 所有入口逐字节一致；selfcheck 入口执行本目录 tests/selfcheck.py |
| templates/** | 三个通用受信模板逐字节一致，固定示例路径 |
| pyproject.toml、requirements.lock、config/example.json | 逐字节一致；cli_profile 只在私有配置指定，无代码常量替换 |
| README/HANDOFF/SECURITY/CONTRIBUTING/LICENSE/THIRD_PARTY_NOTICES | 逐字节一致 |
| docs/DEPLOY、COMPATIBILITY、PROGRESS、PROTOCOL-SOURCES、OPEN-SOURCE-AUDIT、RELEASE-MAPPING、RELEASE-ALLOWLIST | 逐字节一致，公开技术说明为同一份 |
| ALLOWLIST.json | 候选独立清单，覆盖全部候选文件但不自哈希 |
| 受限交付记录、历史研究、原始证据、审计工具、运行数据、原 git 元数据 | 不在公开候选中；不作为运行或测试依赖 |

导出脚本只复制显式列表，导出时核对核心字节；不会在候选中硬编码替代 profile。候选不包含 git 元数据。

公开仓库：https://github.com/billzhuang6569/feishu-grok-bot 。

公开历史必须来自干净 allowlist 候选的全新导入，仅包含 ALLOWLIST.json 列出的文件及清单自身；不得上传原开发历史或携带原 git 元数据。
