# 部署、迁移与操作

本手册使用通用示例路径，不自动安装或操作服务。部署可靠性需在目标环境独立验收，不保证 24/7。以下真实收发步骤只在部署者自己的授权环境执行。Python 3.11–3.14；无需 pip 依赖。CLI 须另行安装并审核版本、绝对路径和 SHA-256。

## 1. 安装和离线检查

把 allowlist 中的完整文件复制到 `/opt/feishu-grok-bot`，由管理员控制代码与 launcher 写权限；以专用受信 OS 用户运行 receiver 和 helper。该用户必须能访问自身获授权的官方 CLI store。不要复制其他用户 store，也不要把凭据放进仓库。

```sh
cd /opt/feishu-grok-bot
PYTHONDONTWRITEBYTECODE=1 bin/run-tests
bin/selfcheck
```

测试禁止网络和真实子进程。候选 selfcheck 只核对本候选 allowlist 和散列。外部 CLI 不在 requirements.lock 中，示例占位符不能直接运行。

## 2. 私有配置与迁移

在仓库外创建 `/etc/feishu-grok-bot/private.json`（0600），参考 config/example.json。配置必须是绝对路径、非软链接且不在安装根内。所有占位符必须由部署者核实替换。

| 字段 | 要求 |
|---|---|
| cli_path | 审核后的 CLI 绝对路径，不依赖 PATH |
| cli_profile | **新增必填，无默认**。1–64 个 ASCII 字母/数字/下划线/连字符，首位须字母或数字；缺失/非法拒绝加载 |
| live_enabled | true 加入口 --live 才可真实收发，默认关闭 |
| state_dir | 专属绝对私有目录，例如 /var/lib/feishu-grok-bot，0700，同受信用户拥有 |
| policy.app/tenant/owner/chat | 独立核验的 app、tenant、唯一 owner、唯一 p2p，不接受模型选择目标 |
| shared_gate_dir | 预建 0700 持久 gate 目录，示例 /var/lib/feishu-shared-gate |
| gate_mode | new 或 legacy-compatible；都运行本项目受 gate 管理的代码 |
| reaction_enabled / progress_card_enabled | 新增可选，省略等于 false，只有布尔 true 启用 |
| reaction_emoji | 可选，默认 OnIt，白名单 OnIt / THINKING，大小写严格 |

迁移现有部署时，在**已有私有配置**增加 cli_profile，填写当前正在使用的 profile，保持原值不变；不执行 profile 切换。其它 policy 限制项及原有默认保持兼容，不需要改变已有 ID 或 TTL。纯核心 Config 构造也显式传入 cli_profile。勿打印配置或提交私有值。profile 与 app 的真实绑定由部署者独立核验，名称不能证明绑定。

上下文 SQLite 明文，需加密磁盘及受控备份；目录 0700、数据库 0600，同一可信用户执行。Routine/model 不得获授配置、数据库、gate-admin 写权限。

## 3. CLI 环境、权限与 Routine

所有 CLI 路径统一来自 cli_path，所有子进程环境统一通过 cli_environment()：固定 PATH=/usr/bin:/bin，必需 HOME；仅可再传 LARKSUITE_CLI_CONFIG_DIR / LARKSUITE_CLI_DATA_DIR。目录变量须绝对、无换行；不继承任意凭据提供者变量。程序只把定位变量传给 CLI，不检查 store 文件。

文本发送沿用已获授权的发送权限。reaction 写权限选择 `im:message.reactions:write_only`；更新卡片最窄独立权限是 `im:message:update`。官方 patch 也允许已有 `im:message:send_as_bot` 或 `im:message` 任一权限，因此如果已有发送权限已覆盖 patch，不必新增 update。reaction list/read 非运行依赖，不为本功能申请；无 cardkit 权限。见 [官方核验](PROTOCOL-SOURCES.md)。

receiver 从受保护服务环境取得 FEISHU_ROUTINE_WEBHOOK_URL 和 FEISHU_ROUTINE_AUTHORIZATION（Bearer 格式）；只允许 HTTPS 的既定 Routine webhook 主机及路径，不跟随重定向、不盲重试。具体 URL/key 不入配置示例、仓库、argv、日志。HTTP 200 仅表示接受并启动，不代表任务完成。

部署者在本产品中设置 Webhook Routine；将其最终回复步骤映射到独立受信 reply launcher。不要在仓库中保存 Routine 的真实凭据或配置。可从 templates/trusted-reply.sh 和 trusted-context.sh 复制到 `/opt/feishu-grok-launchers/reply` 与 context，按安装路径审核固定 ROOT、CONFIG 常量并设置可执行。禁止软链到旧入口；禁止允许模型修改模板或把任意参数透传。

reply 契约是 `--in-reply-to <message_id>` 加原样 stdin；context 可无参数或 `--chat-id <固定目标>`。Routine 只可调用这两个固定入口，不可调用 gate-admin、stop-bus 或任意 CLI。卡片仅显示 bridge 阶段。

## 4. 首次启动与 gate

创建上述 state 和 gate 目录，属主为受信运行用户，权限 0700。首次迁移前必须停止并禁用所有未加 gate 的旧 receiver/helper/supervisor 及自动重启入口，证明所有在途发送已退出。无法证明则保持停机。本项目的锁无法约束旧代码。

在独立新库上标记切口，T 替换为维护窗口中有限正数 Unix 秒，不晚于当前时间：

```sh
cd /opt/feishu-grok-bot
PYTHONPATH=/opt/feishu-grok-bot/src /usr/bin/python3 -B -m feishu_grok_bot mark-cutover --config /etc/feishu-grok-bot/private.json --cutover-at T
```

只允许未标记、空 inbox 的新库；无网络，无 live。不导入旧账本，不用新空库绕过去重。重启必须复用同一 DB、切口、gate 和锁 inode。

管理员审核 templates/gate-admin.py 的固定 gate 路径，复制到 `/opt/feishu-grok-launchers/gate-admin.py`，只授管理员执行，运行身份须与 gate 文件属主一致。不要暴露给模型。

```sh
PYTHONPATH=/opt/feishu-grok-bot/src /usr/bin/python3 -B /opt/feishu-grok-launchers/gate-admin.py initialize
PYTHONPATH=/opt/feishu-grok-bot/src /usr/bin/python3 -B /opt/feishu-grok-launchers/gate-admin.py activate --mode new
PYTHONPATH=/opt/feishu-grok-bot/src /usr/bin/python3 -B -m feishu_grok_bot receive --config /etc/feishu-grok-bot/private.json --live
```

initialize 建立暂停状态；只有 pause 状态且无残留 operation 才能 activate。receive 为前台进程，应记录自己启动的 PID，由受信服务管理器管理；不得同时运行两个 receiver。可选 UI 默认保持关闭，完成部署者有限真实验收后再单独启用。

## 5. 停止、重启与健康

先执行管理员 `gate-admin.py pause`，等待正常返回取得排空证明。之后向自己管理的 receiver PID 发 SIGTERM，等待退出；不要用按名称批量 kill。pause 阻塞或失败不等于排空，禁止随后 activate；残留 operations 要人工核实，不可删记录解锁。停 receiver 时它只终止自己的 consumer child。

重启复用原 DB/gate：确认进程退出，`activate --mode new`，再启动唯一 receiver。切代也采用相同顺序，两模式共用 gate/DB。不得替换锁文件、删除 claims 或清空 pending/unknown。child 退出有最多五次退避重连；child 不退出即停止，local ready 但 upstream stale 不强行重启事件总线。外部无限自动重启会绕过退避意图，不应配置。

健康 stdout 只有枚举状态，无 payload/ID/URL：process 表示本进程存活；local_bus ready 仅表示本地 CLI marker；upstream 是近期可信入站观察；E2E 是已核目标 sent 观察。安静时 unknown/stale 不能证明故障；没有主动探测消息。不承诺主机重启恢复 SLA。

部署者的真实验收需要自己授权的新测试消息，分别核对入站、HTTP acceptance、Routine 完成、helper sent；不要用历史消息补验。程序返回 sent 0、failed 1、拒绝 3、重复 4、unknown 5。进度 UI 错误不改变这些分类。对于 progress 表 diagnostic 非空、unknown、card_stage 与 stage 不一致，先人工核实；不得重复 UI 写入或重发正文。

## 6. 回滚

先 pause 并取得排空证明，再停止唯一 receiver 并确认退出，默认保持停机。保留 DB/gate/claims/operations/锁 inode及诊断记录。若需回到上一版，必须选已验证同样 gate 协议且兼容当前 schema 的版本，保留私有 profile 和路径，重新验证离线测试，再以新代 activate；不能启动原始未加 gate 的旧程序。无法确认兼容则保持停机。禁止恢复旧 prompt/旧 helper 可调用路径，禁止删除状态获得“干净”回滚。

可选 reaction / 阶段卡片默认关闭，尚未生产验收，见 [reaction 与阶段卡片](https://github.com/billzhuang6569/feishu-grok-bot/issues/2)。当前 Webhook Routine 未找到可供本桥使用的官方工具事件或进度出口，见 [真实工具事件](https://github.com/billzhuang6569/feishu-grok-bot/issues/1)；这不等于官方明确不支持。卡片仅显示 bridge 已观察阶段。

公开仓库：https://github.com/billzhuang6569/feishu-grok-bot 。公开历史必须来自干净 allowlist 候选的全新导入，仅包含 ALLOWLIST.json 列出的文件及清单自身；不得上传原开发历史或携带原 git 元数据。
