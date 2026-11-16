# 可选进度协议

默认关闭，只有 live_enabled=true、对应开关布尔 true、有效绝对 CLI 路径与 profile、shared gate 当前 generation 的 claim、已核验 app/tenant/owner/p2p 才允许 UI 调用。生产通过 Capabilities 的可取消 ui_send 执行 UI，复用正文发送的绝对 cli_path、profile 与 cli_environment()；不另造宽松环境。

received → submitted → returned → replied 表示 bridge 已观察阶段。HTTP 200 只是 Routine 接受；returned 表示 helper 收到正文；replied 只允许持久文本 reply=sent 证明。failed 显示“失败或状态待核实”。这些不是工具事件。

终态规则：已 replied 永不被失败/乱序反转；failed 不接受普通阶段回退，但稍后账本证明文本 sent 时可更正为 replied。dispatch unknown 不证明 Routine 未运行，故允许合法 helper 继续给出文本最终结果。文本 reply 的 sent/unknown/failed 分类始终不受 UI 影响。

progress.stage 仅代表期望阶段，不代表已调用成功；card_stage 才是成功信封确认的显示阶段。reaction / card_state 在 CLI 前持久置 unknown，并记录 reaction_op/card_op、reaction_result/card_result 与 diagnostic（仅固定类别：permission_denied/rate_limited/exception/missing_handle 等，无原始错误文本）。已知 reaction_id 才能删除自身 reaction，已知 card_mid 才能 patch 原卡。卡片回复使用 +messages-reply 专用 flags；patch 使用 raw --params 与 --data，content 为 JSON 字符串；delete 无 --data。

主路径只投递内存提示，不等待 UI 锁、CLI、超时或 UI 确认；Routine post、正文 send、下一入站 accept 可在 UI 被阻塞时继续。每个 UI 实例只有一个后台 worker，最多 32 个待处理消息，同消息提示合并，另有最多一个执行中任务。队列满时丢弃新提示，不增加线程或重试；UI 阶段允许跳帧，不保证每条消息都有 reaction 或卡片。关闭开关时不启动 worker。没有新增配置。

worker 使用独立 SQLite 连接。锁顺序仍为 shared gate lease → 独占 progress.lock → 短 SQLite 事务，但两把文件锁均非阻塞获取：竞争时放弃该提示；主路径不获取 progress.lock。UI 独占锁跨 IO 和确认提交，锁内重读持久快照，避免重复写入或过期快照覆盖。数据库写事务不跨 CLI IO。queued 提示没有外部能力；执行时重新核验当前 generation 的 claim、目标和 profile，每次 UI 操作前再查暂停意图。旧代提示不能在新代运行。

每次生产 UI CLI 有内部 30 秒预算，以至多 100ms 的 communicate 等待片段检查 pause/shutdown；取消或超预算时 kill 自己的 UI child，并以最多 1 秒 wait 证明其退出，才释放操作 lease。终止或回收失败保留 operations 崩溃屏障、unknown intent 和未排空状态，不继续执行其它提示。以上为子进程等待预算，不是操作系统或本地数据库延迟的实时承诺；正文发送契约不变。

pause 仍先提交暂停意图，再等 shared leases 实际排空并检查残留 operations，正常返回才是证书。未开始提示被 gate 禁止；正在执行的 UI 必须结束或确认取消。shutdown 清空尚未执行的内存提示，停止接收新提示，最多等 worker 250ms；仍阻塞或未证明子进程退出时返回未排空，receiver 退出路径报 ui_shutdown_unconfirmed，而非成功排空。不可取消的注入调用即使主路径已继续，仍持 lease 和 unknown；其返回前 pause 不能成功。若进程退出留下 operations，重启必须人工核实，禁止删屏障。helper 的正文 sent/unknown/failed 返回值只描述正文，不是 UI 排空证书。

非终态卡片每秒至多更新一次；终态绕过节流但仍受队列容量、gate 和取消约束。重启恢复与 receiver 本地周期检查只异步投递 sent、unknown/failed、过期请求的收尾提示；不等待 UI，不消费额外事件或发查询请求。已知 active 句柄可尝试一次收尾；未知操作永不自动重放，未确认 terminal patch 的 card_stage 保留旧值。阶段终态规则在合并提示和持久更新中均保留，持久正文 sent 始终有最终解释权。

权限拒绝、429、异常、缺 reaction_id、未知卡片回复、崩溃、过代或已暂停均不能宣称清理完成。unknown 留存固定类别诊断；gate 拒绝保留句柄并尽可能记录 blocked_or_local_error；取消可记录 cancelled_unconfirmed。锁竞争或队列丢帧不冒充成功确认。独立的卡片失败不阻止已知 reaction 删除，但 pause/shutdown 会阻止新的删除调用。没有安全句柄时无法保证远端 UI 被清除，须部署者人工核实，禁止抹账本盲重试。

全部验证仍为隔离合成测试，尚未生产验收。[reaction 与阶段卡片](https://github.com/billzhuang6569/feishu-grok-bot/issues/2) 及 [真实工具事件](https://github.com/billzhuang6569/feishu-grok-bot/issues/1) 仍待部署者另行验证。

Card 2.0 使用 blue header、default 宽度、update_multi=true，body 仅一个固定阶段 markdown，不含用户正文、代码、表格或链接。公开文档对空 elements 的合法性没有明确保证，因此不依赖空 body。小于 7.20 的客户端会显示标题及升级提示。
