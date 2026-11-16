# 兼容性

| 契约 | 行为 |
|---|---|
| 范围 | 单用户、单一 p2p 文本；无群、多用户、附件支持 |
| reply | --in-reply-to + stdin；sent 0 / failed 1 / 拒绝 3 / 重复 4 / unknown 5 |
| context | 可选 --chat-id；本地有限 role/message_id/at/text JSON |
| 成功信封 | 兼容 CLI ok=true,data 与 OpenAPI code=0,data；明确失败优先；需唯一合法 outbound ID 和一致 chat |
| 缺证明/预览 | unknown；不建立 E2E，不自动重试 |
| CLI | 审核绝对 cli_path；显式私有 cli_profile；bot 身份；统一受限环境 |
| 配置迁移 | 新增顶层 cli_profile 必填无默认，原私有值保持不变；原有 policy 项和默认不变 |
| 可选 UI | reaction_enabled / progress_card_enabled 缺省关闭，reaction_emoji 缺省 OnIt |
| 幂等与历史 | 可信入站账本选目标；pending 恢复为 unknown；不补读历史、失败不重试 |
| Routine payload | event_id/message_id/chat_id/sender_open_id/chat_type/thread_id/text/verified_at/source/app_id/profile |
| gate | shared lease 跨外部 IO，当前 generation + 持久 claim；切代先 pause 排空并停 consumer |
| 卡片 | Card 2.0 header + 一个固定阶段 markdown；原卡 patch；非工具调用详情 |
| UI 收尾 | stage 是意图，card_stage 是确认；终态绕过节流，失败保留 unknown 和 diagnostic |

CLI 扁平事件必须有可信时间戳，受信固定 consumer 只补 app/tenant；无时间戳拒绝。真实 store、profile→app 绑定、Routine helper 可达性与长期可靠性仍需部署者验证。requirements.lock 仅锁定零第三方 Python 依赖，CLI 是独立外部依赖。

context 默认 24h / 20 条 / 16KiB，活动、读取、恢复时清理，停机不主动擦除。未知发送不保证跨系统 exactly-once。当前 shared gate 协议与 [部署](DEPLOY.md) 是有效操作说明；早期未加 gate 的迁移/回旧步骤均无效。
