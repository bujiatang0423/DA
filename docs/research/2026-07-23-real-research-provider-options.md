# 本地真实研究数据源方案

更新：2026-07-23。本文只列出数据拥有方或官方运营方的入口；不把未公开、无
服务承诺的网页内部接口当作生产 API。

## 结论

推荐分三层接入：

1. **财报主源：巨潮资讯官方数据服务。** 用其受授权的结构化财务指标、定期报告
   和公告元数据填充 `ResearchMarketDataPort.financials`。
2. **政策主源：证监会 + 中国政府网。** 以政策原文建立可审计的本地证据库；交易所
   规则作为证券自律监管补充。没有看到可承诺稳定性的免费官方政策检索 REST API，
   因此不应把网页内部 XHR 当作生产依赖。
3. **文本归因：DeepSeek API。** 它是 LLM 提供商接口，确实需要 DeepSeek API Key，
   但它不提供财报或政策事实；只对上述已入库、可追溯的原文做受约束的结构化提取。

这与当前项目接口契合：`financials` 提供带 `published_at` 的财务事实，`materials`
提供政策原文与首次观察时间，LLM 仅实现 `extract`。LLM 输出须继续经过项目已有的
schema、证据来源、发布时间和禁用交易字段校验。

## 财报与公告

### 首选：巨潮资讯（CNINFO）官方数据服务

- 巨潮首页称其为中国证监会指定的上市公司信息披露网站，覆盖上市公司公告和财务
  数据：[巨潮资讯首页](https://www.cninfo.com.cn/new/index)。
- 官方数据服务/API 文档入口：[深证信数据服务](https://webapi.cninfo.com.cn/#/apiDoc)。
  页面说明 Access Key/Access Secret 是调用密钥，并提供 token；部分接口和数据需要
  产品授权、购买或升级。实际覆盖字段、许可、价格、QPS/日配额应在试用或合同中逐项
  确认，公开页面没有统一的限流承诺。

建议采购或开通后按发行人代码和报告期增量同步，并在 PostgreSQL 原始表保存：来源
record id、原文 URL、报告期、公告 `published_at`、抓取/首次观察时间、原文 SHA-256、
许可证/产品标识。事实只能在 `published_at` 后用于持仓分析；回测也必须按该时间切片。

### 原文核验与低频回退

下列均为交易所官方披露页，适合对公告 PDF/HTML 做原文核验和补漏，不应依赖其未公开
内部接口做高频批量抓取：

- [上交所上市公司公告](https://www.sse.com.cn/disclosure/listedinfo/announcement/)
- [深交所上市公司公告](https://www.szse.cn/disclosure/listed/notice/index.html)
- [北交所公告](https://www.bse.cn/disclosure/announcement.html)

网页入口没有公开稳定 REST 契约、认证方式或 QPS 承诺。若采用，应限速、遵守站点条款，
保存原文快照/hash，并把失败保持为“数据缺失”，而非以测试数据代替。

## 政策与监管材料

建议先建立一个小而明确的官方源清单，而不是泛抓新闻：

| 范围 | 官方来源 | 使用方式 |
| --- | --- | --- |
| 资本市场监管 | [证监会法规/规则](https://www.csrc.gov.cn/csrc/c100028/common_list.shtml) | 主政策证据源 |
| 监管解释 | [证监会政策解读](https://www.csrc.gov.cn/csrc/c100039/common_list.shtml) | 与规则原文关联，不替代规则 |
| 宏观及国务院文件 | [中国政府网政策](https://www.gov.cn/zhengce/index.htm)、[国务院政策文件库](https://www.gov.cn/zhengce/zhengceku/) | 宏观和产业政策主源 |
| 上市/交易所自律规则 | [上交所法律规则](https://www.sse.com.cn/lawandrules/)、[深交所法律规则](https://www.szse.cn/lawrules/) | 交易制度和自律规则补充 |

这些官方页面未提供可公开确认的通用检索 API、凭据或 QPS。可行的本地方案是低频增量
采集 + 人工审核：存储 URL、发文机关、文号、标题、发布日期、生效日期、适用范围、
原文、内容 hash、首次观察时间和审核结果。只有已审核且 `published_at <= as_of_time`
的资料才能交给 `PolicyPort.materials` 与 LLM。

如果需要全市场、低延迟且结构化的政策事件流，应向有授权的数据服务商采购；在签约前
要求明确覆盖范围、再发布许可、历史修订、SLA、QPS 和归档权。不要用未记录授权的
搜索结果或网页内部接口替代。

## DeepSeek LLM provider

是的，**DeepSeek provider 就是使用 DeepSeek 平台创建的 API Key 调用模型**，但 key
只应配置在本机环境变量/密钥存储中，绝不可提交到仓库、日志或任务产物。

- [首次 API 调用官方文档](https://api-docs.deepseek.com/)：OpenAI 兼容接口的
  `base_url` 是 `https://api.deepseek.com`，通过平台申请 API Key，并以
  `Authorization: Bearer ...` 调用。
- [JSON Output 官方文档](https://api-docs.deepseek.com/guides/json_mode)：可设置
  `response_format={"type":"json_object"}`。官方同时提示偶发空内容，所以适配器必须
  重试有限次数，仍失败则 fail-closed。
- [并发限制官方文档](https://api-docs.deepseek.com/quick_start/rate_limit)：并发按账户
  计算，超限返回 HTTP 429；当前文档列出 v4-flash 2500、v4-pro 500。小型本地项目仍应
  用更低的本地队列并发和指数退避。

实现建议：使用非思考模式、要求 JSON，并将模型名、prompt hash、所有输入原文 hash、
输出 hash 与响应时间一并落库。LLM 的职责限于从指定的政策/财报证据中提取
`policy_direction`、风险标记、完整性和引用片段；不能让它自行搜索、补造事实、输出买卖
动作或仓位。当前项目的 `validate_factor` 已适合担任最后一道校验。

## 推荐落地顺序

1. 申请/试用 CNINFO 数据服务，确认字段、许可和限额；先实现财报入库和点时筛选。
2. 建立证监会、中国政府网、两所规则的受审核政策采集清单和本地证据表。
3. 申请 DeepSeek Key，增加一个只读取本地已审核证据的 LLM adapter，并接入现有
   schema 校验和审计字段。
4. 设置 `DA_RESEARCH_PROVIDER_FACTORY=包路径:factory`，由 factory 返回完整的
   market、policy 和 llm provider；任一源不可用仍保持当前 fail-closed 行为。

在前两步完成前，不应把持仓分析改成用 fixture 或 LLM 自行生成财报/政策结果。
