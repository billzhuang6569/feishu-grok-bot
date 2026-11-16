# 安全边界

默认 live guard 和可选 UI 关闭。只允许私有配置中唯一 owner + p2p；模型不得选择发送目标、profile、代际或路径。配置在仓库外 0600、状态和 gate 0700，受信同一 OS 用户；Routine/model 不可改配置、账本、代码、锁或 gate-admin。

所有 CLI 使用审核后的绝对 cli_path、显式 cli_profile 与统一 cli_environment。环境仅含固定 PATH、HOME 和可选官方目录定位变量；不继承任意凭据提供者。上下文 DB 明文，需加密磁盘和受控备份；TTL 清理不等于安全擦除。

gate claim/lease 跨完整外部操作，pause 提交后排空。禁止删锁、清空 unknown、替换 DB 绕过幂等或恢复原始未加 gate 的程序。UI 只反馈 bridge 阶段；未知、403、429、崩溃均不盲重试，不影响正文分类。

不得提交 .env、store、真实配置、状态、凭据、日志、上下文或内部证据。公开导入只使用干净候选 allowlist，原历史禁止上传，不能复用原 git 元数据。启发式扫描不能证明没有秘密，发布前仍需复核。

公开仓库：https://github.com/billzhuang6569/feishu-grok-bot 。报告问题时只提供脱敏的错误类别与合成复现，不提供凭据或真实消息。

可选 reaction / 阶段卡片默认关闭，尚未生产验收，见 [reaction 与阶段卡片](https://github.com/billzhuang6569/feishu-grok-bot/issues/2)。当前 Webhook Routine 未找到可供本桥使用的官方工具事件或进度出口，见 [真实工具事件](https://github.com/billzhuang6569/feishu-grok-bot/issues/1)；这不等于官方明确不支持。卡片仅显示 bridge 已观察阶段。
