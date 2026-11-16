# 开源审计

公开仓库：https://github.com/billzhuang6569/feishu-grok-bot 。采用 MIT 许可。

公开历史必须来自干净 allowlist 候选的全新导入，仅包含 ALLOWLIST.json 列出的文件及清单自身；不得上传原开发历史或携带原 git 元数据。

**原历史禁止上传**。全部原 commit/tree/blob/ref（含不可达对象）排除，不能直接 push，不能复用 git 元数据。历史审计仅使用元数据，不输出真实匹配值；不得扩大读取凭据、store、真实配置或真实账本的权限。

候选包含完整 src、全部纯离线合成测试、依赖声明、示例配置、通用 launcher 和可运行部署说明。核心代码、测试和技术文档按字节复制，不在导出时替换常量。cli_profile 在私有配置显式指定，测试仅合成值。差异见 [RELEASE-MAPPING](RELEASE-MAPPING.md)。

只可导入候选 ALLOWLIST.json 精确列出的文件及 manifest 自身；manifest 不自哈希。候选 selfcheck 仅验证本目录，不依赖旧项目、原证据或 git。原始内部证据、管理目录、历史、认证、状态、缓存不进入候选。全文件扫描包括 ID、凭据形状、私有路径、profile、webhook 和垃圾文件规则；规则未命中不等于绝对无秘密。

可选 reaction / 阶段卡片默认关闭，尚未生产验收，见 [reaction 与阶段卡片](https://github.com/billzhuang6569/feishu-grok-bot/issues/2)。当前 Webhook Routine 未找到可供本桥使用的官方工具事件或进度出口，见 [真实工具事件](https://github.com/billzhuang6569/feishu-grok-bot/issues/1)；这不等于官方明确不支持。卡片仅显示 bridge 已观察阶段。
