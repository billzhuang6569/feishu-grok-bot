# 可选进度协议

默认关闭，只有 live_enabled=true、对应开关布尔 true、有效绝对 CLI 路径与 profile、shared gate 当前 generation 的 claim、已核验 app/tenant/owner/p2p 才允许 UI 调用。生产通过 Capabilities 的可取消 ui_send 执行 UI，复用正文发送的绝对 cli_path、profile 与 cli_environment()；不另造宽松环境。

received → submitted → returned → replied 表示 bridge 已观察阶段。HTTP 200 只是 Routine 接受；returned 表示 helper 收到正文；replied 只允许持久文本 reply=sent 证明。failed 显示“失败或状态待核实”。这些不是工具事件。

终态规则：已 replied 永不被失败/乱序反转；failed 不接受普通阶段回退，但稍后账本证明文本 sent 时可更正为 replied。dispatch unknown 不证明 Routine 未运行，故允许合法 helper 继续给出文本最终结果。文本 reply 的 sent/unknown/failed 分类始终不受 UI 影响。

progress.stage 仅代表期望阶段，不代表已调用成功；card_stage 才是成功信封确认的显示阶段。reaction / card_state 在 CLI 前持久置 unknown，并记录 reaction_op/card_op、reaction_result/card_result 与 diagnostic（仅固定类别：permission_denied/rate_limited/exception/missing_handle 等，无原始错误文本）。已知 reaction_id 才能删除自身 reaction，已知 card_mid 才能 patch 原卡。卡片回复使用 +messages-reply 专用 flags；patch 使用 raw --params 与 --data，content 为 JSON 字符串；delete 无 --data。

主路径只投递内存提示，不等待 UI 锁、CLI、超时或 UI 确认；Routine post、正文 send、下一入站 accept 可在 UI 被阻塞时继续。每个 UI 实例只有一个后台 worker，最多 32 个待处理消息，同消息提示合并，另有最多一个执行中任务。队列满时丢弃新提示，不增加线程或重试；UI 阶段允许跳帧，不保证每条消息都有 reaction 或卡片。关闭开关时不启动 worker。没有新增配置。

worker 使用独立 SQLite 连接。锁顺序仍为 shared gate lease → 独占 progress.lock → 短 SQLite 事务，但两把文件锁均非阻塞获取：竞争时放弃该提示；主路径不获取 progress.lock。UI 独占锁跨 IO 和确认提交，锁内重读持久快照，避免重复写入或过期快照覆盖。数据库写事务不跨 CLI IO。queued 提示没有外部能力；执行时重新核验当前 generation 的 claim、目标和 profile，每次 UI 操作前再查暂停意图。旧代提示不能在新代运行。

每次生产 UI 调用启动一个短生命周期 Python 监管进程（非常驻服务、无新增依赖）。平台前提为 Linux、可用的 `/proc` 子进程列表、`prctl(PR_SET_CHILD_SUBREAPER)`、`waitid(WNOWAIT)`、新会话/进程组及对本次后代的发送信号权限。监管者在启动 CLI 前成为 subreaper；CLI 使用新会话，监管者独立持有其生命周期。30 秒是 CLI 执行预算，不是数据库或内核实时退出保证。

取消使用 owner 独占写端的控制管道：内存 shutdown 信号足以关闭写端，owner 正常退出也使管道 EOF。监管者不访问 gate 数据库，独立终止 CLI 进程组，再反复 kill/reap 自己被内核收养的子进程。CLI 领导者在 killpg 前不被回收，避免其 PID 提前复用。普通 fork、双重 fork 和自行 setsid 的后代可通过 subreaper 收养后清理；正式 integration 包含 fork 与 setsid。只有存活监管者的 `waitpid(-1)` 返回 ECHILD，且 owner 收到完整证明并确认监管者正常退出，才允许释放该 UI operation。进程组本身不能阻止任意逃逸。

执行时仍复验 generation/目标/profile，UI 轮询的 gate 检查使用 SQLite timeout=0，busy 即取消；kill/reap 不依赖 SQLite。pause 先提交暂停意图，再等 leases 并检查 operations，正常返回才是证书。shutdown 停收并丢弃未开始提示，最多 join worker 250ms；未完成返回 false。worker 即使被正常解释器退出截断，独立监管者仍可通过 EOF 完成清理；未收到证明则 operations 留存，不能把后台清理可能完成当作排空证明。helper 正文状态仍只描述正文。

安全边界限于这个活着的监管者能由内核跟踪和回收的执行树，不是恶意程序沙箱。脱离进程组的进程不能仅凭 killpg 保证终止；只有被收养并最终证明 ECHILD 的后代才在证书内。无法收养/不可达 PID、外部既有服务接手的工作、权限或平台变化、不可终止的内核等待、监管者遭 SIGKILL/崩溃、机器异常退出等均不能保证终止。缺证明、异常监管退出、kill/reap 失败均保留 operations 与 unknown，禁止 pause 证书和切代，必须由部署者外部核实整个边界；禁止删除屏障解锁。清理无法完成时监管者继续尝试，owner 的有限等待可返回未确认。

默认关闭，尚未生产验收。没有新增配置或迁移；既有持久 intent、unknown 不重放及 gate schema 保持兼容。`bin/run-tests` 为禁止真实子进程的 unit；独立 `bin/run-integration` 只运行私有临时目录内有限的合成进程，禁止网络，并在 finally 精确回收子进程，清理失败即失败。这些测试不等同于真实部署验收。

非终态卡片每秒至多更新一次；终态绕过节流但仍受队列容量、gate 和取消约束。重启恢复与 receiver 本地周期检查只异步投递 sent、unknown/failed、过期请求的收尾提示；不等待 UI，不消费额外事件或发查询请求。已知 active 句柄可尝试一次收尾；未知操作永不自动重放，未确认 terminal patch 的 card_stage 保留旧值。阶段终态规则在合并提示和持久更新中均保留，持久正文 sent 始终有最终解释权。

权限拒绝、429、异常、缺 reaction_id、未知卡片回复、崩溃、过代或已暂停均不能宣称清理完成。unknown 留存固定类别诊断；gate 拒绝保留句柄并尽可能记录 blocked_or_local_error；取消可记录 cancelled_unconfirmed。锁竞争或队列丢帧不冒充成功确认。独立的卡片失败不阻止已知 reaction 删除，但 pause/shutdown 会阻止新的删除调用。没有安全句柄时无法保证远端 UI 被清除，须部署者人工核实，禁止抹账本盲重试。

全部验证仍为隔离合成测试，尚未生产验收。[reaction 与阶段卡片](https://github.com/billzhuang6569/feishu-grok-bot/issues/2) 及 [真实工具事件](https://github.com/billzhuang6569/feishu-grok-bot/issues/1) 仍待部署者另行验证。

Card 2.0 使用 blue header、default 宽度、update_multi=true，body 仅一个固定阶段 markdown，不含用户正文、代码、表格或链接。公开文档对空 elements 的合法性没有明确保证，因此不依赖空 body。小于 7.20 的客户端会显示标题及升级提示。
