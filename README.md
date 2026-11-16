# feishu-grok-bot

单用户飞书私聊文本桥：官方 Lark CLI 接收新文本，转交 Grok Bot Webhook Routine，再由受信 helper 回复原消息。Python 3.11–3.14 标准库与 SQLite，无第三方 Python 依赖。独立实现，MIT 许可。

可选 reaction 和 bridge 阶段卡片默认关闭；卡片不是真实工具调用详情。仅允许配置中唯一 owner + p2p，默认 live guard 关闭。unknown 不盲重试，不导入历史，不保证 24/7 或跨系统 exactly-once。

公开仓库：https://github.com/billzhuang6569/feishu-grok-bot 。

可选 reaction / 阶段卡片默认关闭，尚未生产验收，见 [reaction 与阶段卡片](https://github.com/billzhuang6569/feishu-grok-bot/issues/2)。当前 Webhook Routine 未找到可供本桥使用的官方工具事件或进度出口，见 [真实工具事件](https://github.com/billzhuang6569/feishu-grok-bot/issues/1)；这不等于官方明确不支持。卡片仅显示 bridge 已观察阶段。

```sh
PYTHONDONTWRITEBYTECODE=1 bin/run-tests
bin/selfcheck
```

测试使用合成数据、临时状态与 mock；runner 禁止网络和真实子进程。部署时须单独安装审核后的官方 CLI。

- [完整部署、迁移、停启和回滚](docs/DEPLOY.md)
- [配置与行为兼容](docs/COMPATIBILITY.md)
- [进度状态协议](docs/PROGRESS.md)
- [官方资料核验](docs/PROTOCOL-SOURCES.md)
- [安全边界](SECURITY.md)
- [参考许可](THIRD_PARTY_NOTICES.md)
- [交接](HANDOFF.md)

公开历史必须来自干净 allowlist 候选的全新导入，仅包含 ALLOWLIST.json 列出的文件及清单自身；不得上传原开发历史或携带原 git 元数据。
