# 可选进度协议

默认关闭，只有 live_enabled=true、对应开关布尔 true、有效绝对 CLI 路径与 profile、shared gate 当前 generation 的 claim、已核验 app/tenant/owner/p2p 才允许 UI 调用。生产注入 Capabilities.send，复用 cli_environment()；不另造宽松环境。

received → submitted → returned → replied 表示 bridge 已观察阶段。HTTP 200 只是 Routine 接受；returned 表示 helper 收到正文；replied 只允许持久文本 reply=sent 证明。failed 显示“失败或状态待核实”。这些不是工具事件。

终态规则：已 replied 永不被失败/乱序反转；failed 不接受普通阶段回退，但稍后账本证明文本 sent 时可更正为 replied。dispatch unknown 不证明 Routine 未运行，故允许合法 helper 继续给出文本最终结果。文本 reply 的 sent/unknown/failed 分类始终不受 UI 影响。

progress.stage 仅代表期望阶段，不代表已调用成功；card_stage 才是成功信封确认的显示阶段。reaction / card_state 在 CLI 前持久置 unknown，并记录 reaction_op/card_op、reaction_result/card_result 与 diagnostic（仅固定类别：permission_denied/rate_limited/exception/missing_handle 等，无原始错误文本）。已知 reaction_id 才能删除自身 reaction，已知 card_mid 才能 patch 原卡。卡片回复使用 +messages-reply 专用 flags；patch 使用 raw --params 与 --data，content 为 JSON 字符串；delete 无 --data。

锁顺序：shared gate lease → gate 目录内独占 progress.lock → 短 SQLite 事务。主流程先结束其 bridge DB 事务再反馈，UI 不持 DB 写锁等待 CLI。主流程的外层 gate lease 与 UI 内层 lease 均共享，不做锁升级。gate pause 先提交暂停，再取排空独占锁；不会持 gate DB 事务等待 drain。UI 独占锁跨 IO 和结果提交，所有连接从锁内读取最新持久快照，防止重复写入或过期内存覆盖。

非终态卡片每秒至多更新一次，跳过帧保留 card_stage 不变；终态始终绕过节流。重启恢复与 receiver 本地周期检查对 sent、unknown/failed、过期请求尽可能收尾；不会消费额外事件或发查询请求。已知 active 句柄可安全尝试一次收尾，未知操作永不自动重放。

权限拒绝、429、异常、缺 reaction_id、未知卡片回复、崩溃、过代或已暂停均不能宣称清理完成。unknown 留存诊断；gate 拒绝保留句柄并记录 blocked_or_local_error。未确认 terminal patch 的 card_stage 保持旧值；恢复不会把它伪装成终结。独立的卡片失败不阻止已知 reaction 删除。没有安全句柄时无法保证远端 UI 被清除，须部署者人工核实，禁止抹账本盲重试。

Card 2.0 使用 blue header、default 宽度、update_multi=true，body 仅一个固定阶段 markdown，不含用户正文、代码、表格或链接。公开文档对空 elements 的合法性没有明确保证，因此不依赖空 body。小于 7.20 的客户端会显示标题及升级提示。
