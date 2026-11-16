# 公开协议核验（2026-11-16）

时间为 Asia/Shanghai (+08:00)。飞书 HTML 页 HTTP 200 但只有动态壳，没有提供可读正文；实际阅读使用它声明的公开 Markdown 入口，并在线读取官方固定提交 SDK。没有携带 token，没有调用鉴权 OpenAPI，没有真实业务收发。

| 阅读来源 | GET 时间 | HTTP | 关键段落结论 |
|---|---|---|---|
| [reaction create](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-reaction/create.md) | 10:49:36 +08:00 | 200 | 前提条件/请求/请求体/响应：bot 在会话内，POST reactions，reaction_type.emoji_type；返回 reaction_id/operator/action_time/reaction_type |
| [reaction delete](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-reaction/delete.md) | 10:49:37 +08:00 | 200 | 使用限制：只删自己添加且存在的 reaction；DELETE 路径需 message_id/reaction_id |
| [reaction list](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-reaction/list.md) | 10:49:37 +08:00 | 200 | GET reactions、分页；只作研究，本桥不调用 |
| [emoji](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-reaction/emojis-introduce.md) | 10:49:38 +08:00 | 200 | 表格第16行 THINKING、第39行 OnIt，大小写准确 |
| [patch](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/patch.md) | 10:52:52 +08:00 | 200 | 注意事项/使用限制/请求体：同发送身份、update_multi=true、14天、单卡5QPS、content 为序列化 JSON 字符串、30KB |
| [Card 2.0](https://open.feishu.cn/document/feishu-cards/card-json-v2-structure.md) | 10:49:40 +08:00 | 200 | 字段说明 header/body 非必填；body 章节要求组件，未明确空 elements 合法性；仅共享卡片，客户端 >=7.20 |
| [markdown 组件](https://open.feishu.cn/document/feishu-cards/card-json-v2-components/content-components/rich-text.md) | 10:52:53 +08:00 | 200 | 属性说明 tag=markdown、content 为必填字符串；实现采用一个固定阶段组件，不依赖空 body |
| [SDK im.ts](https://raw.githubusercontent.com/larksuite/node-sdk/b188be60134d409b61259546bcf69c731d2b0b7c/code-gen/projects/im.ts) | 10:49:12 +08:00 | 200 | 285–320 patch 的 content:string、message_id、PATCH；4801起 reaction delete，5105起 create；不验证卡片内部 JSON |
| [SDK LICENSE](https://raw.githubusercontent.com/larksuite/node-sdk/b188be60134d409b61259546bcf69c731d2b0b7c/LICENSE) | 10:49:12 +08:00 | 200 | 完整正文 MIT，Copyright (c) 2022 Lark Technologies Pte. Ltd. |
| [cc-connect LICENSE 路径](https://raw.githubusercontent.com/chenhg5/cc-connect/0df18338c4838bff28f726fa4f28d4f7defdfa6a/LICENSE) | 10:52:54 +08:00 | 404 | 未得到授权正文，固定本地树也无 LICENSE/COPYING；禁止复制实现 |

reaction create/delete 使用 `/open-apis/im/v1/messages/:message_id/reactions`，delete 再加 `/:reaction_id`；create POST、delete DELETE、list GET。机器人须启用能力、在会话内，撤回消息不可操作，系统消息不可添加。create/delete 权限任一：im:message 或 im:message.reactions:write_only。最小写权限选后者；list/read 的 im:message.reactions:read 另列为非运行依赖。

patch 使用 PATCH `/open-apis/im/v1/messages/:message_id`。其权限表任一：im:message、im:message:send_as_bot、im:message:update；最窄独立更新 scope 是 update，已有 send_as_bot 的部署可能无需新增。初次回复卡片使用现有发送权限，无 cardkit scope。空 elements 的文档缺口尚存，SDK 的 string 类型不能补足此缺口，本实现改用最小非空 body，默认关闭且未真实联调。

本地官方 Lark CLI 1.0.100 在空临时 HOME、无凭据环境下 help/schema 已核实：

| 命令 | 参数 |
|---|---|
| im reactions create | --as bot --params JSON(message_id) --data JSON(reaction_type.emoji_type) --json |
| im reactions delete | --as bot --params JSON(message_id,reaction_id) --json；无 --data |
| im messages patch | --as bot --params JSON(message_id) --data JSON(content=序列化卡片) --json |
| im +messages-reply | --as bot --message-id、--msg-type interactive、--content、--idempotency-key、--json |

`im messages reply` 不存在，schema 返回 Unknown method。绝对 cli_path 与显式私有 cli_profile 用于所有调用，Capabilities.send 统一构造受限环境。CLI 成功 ok=true,data；OpenAPI 成功 code=0,data；缺证明、冲突、预览保持 unknown，不仅凭退出码判断。

## Grok Bot

[Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) 于 2026-11-16 11:03:41 +08:00 GET 200，页面更新 2026-11-11。“Webhooks”说明入口 URL、Bearer key、可选 JSON，200 表示已接受并启动；“Manage routines”描述应用内运行历史，未给本桥可订阅的工具事件、进度流字段或鉴权契约。

[Cursor 官方社区支持讨论](https://forum.cursor.com/t/grok-bot-webhooks-dont-appear-on-desktop-linux-version/173891) 的 2026-11-09 支持回复说明 Feishu/Lark 没有内建 trigger，并推荐 webhook relay 触发。网页工具可读正文；11:03:41 的普通 GET 为 403。该回复不是工具事件出口规范。

有界公开研究使用3个检索词、5个唯一页面阅读/尝试：`"Grok Bot" "webhook" routine progress tools`、`site:cursor.com/docs "webhook" "routines"`、`site:x.ai "skills-routines-and-automations" "Bot"`。另三个尝试为 x.ai/grok-bot（GET 403，网页工具404）、docs.x.ai/docs/grok-bot/skills-routines-and-automations（404）、cursor.com/docs/grok-bot/skills-routines-and-automations（GET 200 HTML壳，网页工具失败）。没有把这些失败页面当作已读正文。未使用 X：当前无 X/Twitter 公开检索工具。

结论为**未找到可用官方出口**，并非官方明确不支持。应用内运行历史不是公开 API；xAI 模型 API、Codex 日志、私有接口和会话凭据不能替代。卡片继续只显示本桥真实观察阶段。
