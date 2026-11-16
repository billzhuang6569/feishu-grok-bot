# 交接

项目提供可离线运行的单用户文本桥，包含全部合成测试与部署模板。

公开仓库：https://github.com/billzhuang6569/feishu-grok-bot 。

公开历史必须来自干净 allowlist 候选的全新导入，仅包含 ALLOWLIST.json 列出的文件及清单自身；不得上传原开发历史或携带原 git 元数据。

配置新增必填顶层 cli_profile，无默认，缺失或非法 fail closed。只在已有私有配置填入当前正在使用的 profile，保持现网值不变。reaction_enabled / progress_card_enabled 省略或 false 均关闭；reaction_emoji 默认 OnIt，仅允许 OnIt、THINKING。详见 [部署](docs/DEPLOY.md)。

progress 的可取消 Capabilities.ui_send 复用正文发送的绝对 cli_path、profile 与 cli_environment；shared gate、当前代际、目标白名单和 live guard 继续强制。已确认文本 sent 不会被 UI 异常改变。进度意图与确认分开，unknown、403、429、崩溃均不自动重放，未清理状态可诊断。

UI 由单 worker 与最多 32 消息合并队列执行，主路径不等 UI；队列满可丢帧。worker 独立连接、非阻塞获取 UI 锁，CLI 最多 30 秒，pause/shutdown 可取消并回收。shutdown 最多等 250ms，未结束返回未排空；无法证明 child 退出则保留 gate operations 屏障，禁止把正文 sent 当作 UI 排空证书。没有新增配置。旧状态机回归直接驱动串行 backend 观察各确认帧；新增异步入口回归覆盖阻塞 UI 下 post/send/下一 accept、并发、代际、诚实排空、取消和重启。

功能与限界见 [兼容性](docs/COMPATIBILITY.md)、[进度协议](docs/PROGRESS.md)、[安全](SECURITY.md)。公开候选不包含原始内部证据。

可选 reaction / 阶段卡片默认关闭，尚未生产验收，见 [reaction 与阶段卡片](https://github.com/billzhuang6569/feishu-grok-bot/issues/2)。当前 Webhook Routine 未找到可供本桥使用的官方工具事件或进度出口，见 [真实工具事件](https://github.com/billzhuang6569/feishu-grok-bot/issues/1)；这不等于官方明确不支持。卡片仅显示 bridge 已观察阶段。所有上线、真实权限与主机恢复可靠性仍需部署者验证。
