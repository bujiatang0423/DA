# CNINFO 定期报告公告检索与原文获取调研

调研日期：2026-07-23。范围仅限巨潮资讯自身页面、其加载的官方 JavaScript 与其官方
数据服务入口；没有把第三方封装或非官方资料作为证据。

## 结论

巨潮资讯网页本身可低频、可复现地检索 A 股定期报告公告，并公开提供 PDF 原文。其页面
内部请求不是公开承诺的生产 API；要让运行时自动、持续地获取财报，应优先开通
**深证信数据服务**，以合同/API 文档规定的授权、额度和字段为准。网页 XHR 只能作为
受控的人工/低频回退，不能视为稳定服务契约。

## 官方可观察的网页端点

### 1. 公告列表

- 方法及 URL：`POST https://www.cninfo.com.cn/new/hisAnnouncement/query`
- 证据：巨潮历史公告页加载的官方脚本
  [`history-notice.js`](https://www.cninfo.com.cn/new/js/app/disclosure/notice/history-notice.js)
  的 `getHistory` 方法；该页为
  [巨潮历史公告检索页](https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/search)。
- 该脚本以 `application/x-www-form-urlencoded` 的 jQuery `data` 发出以下字段：

  | 字段 | 页面含义/示例 |
  | --- | --- |
  | `pageNum`, `pageSize` | 页码、页大小，例如 `1`, `30` |
  | `column` | 市场；深市 A 股为 `szse`，沪市页面使用 `sse` |
  | `tabName` | `fulltext` |
  | `plate` | 板块筛选；不筛选时空字符串 |
  | `stock` | `证券代码,orgId`；多只以 `;` 分隔，例如 `000568,gssz0000568` |
  | `searchkey`, `secid` | 页面关键词/基金公司筛选；不使用时空字符串 |
  | `category` | 定期报告分类，见下表 |
  | `trade` | 行业筛选；不使用时空字符串 |
  | `seDate` | 公告日期范围：`YYYY-MM-DD~YYYY-MM-DD` |
  | `sortName`, `sortType` | 可选排序；页面默认空字符串 |
  | `isHLtitle` | 页面固定传 `true` |

  页面脚本没有在这条请求上设置 API key。实测使用正常浏览器的 `User-Agent`、站内
  `Origin`/`Referer` 与表单编码可返回 JSON；响应同时下发 `/new` 会话 cookie。不要绕过
  站点的访问控制、验证码或限流；如果这些控制出现，应记录为获取失败并切换为授权服务或
  人工处理。

| 报告种类 | `category` |
| --- | --- |
| 年报 | `category_ndbg_szsh` |
| 半年报 | `category_bndbg_szsh` |
| 一季报 | `category_yjdbg_szsh` |
| 三季报 | `category_sjdbg_szsh` |

上述分类 ID 同样直接定义在该官方脚本的 `period`/`category` 配置中。

**可复现实例（已于调研日返回数据）：** 查询泸州老窖 2025 年披露的年报：

```text
POST /new/hisAnnouncement/query
pageNum=1&pageSize=30&column=szse&tabName=fulltext&plate=
&stock=000568,gssz0000568&searchkey=&secid=
&category=category_ndbg_szsh&trade=&seDate=2025-01-01~2025-12-31
&sortName=&sortType=&isHLtitle=true
```

`orgId` 不应猜测：同一官方脚本按市场下载证券清单，例如深市的
[`szse_stock.json`](https://www.cninfo.com.cn/new/data/szse_stock.json) 与沪市的
[`sse_stock.json`](https://www.cninfo.com.cn/new/data/sse_stock.json)，其中 `stockList`
元素具有 `code`、`orgId` 与 `zwjc`。实测 `000568` 对应 `gssz0000568`；`600188`
对应 `gssh0600188`。

### 2. 单条公告元数据与原文

- 详情页面：
  `https://www.cninfo.com.cn/new/disclosure/detail?stockCode={secCode}&announcementId={id}&orgId={orgId}&announcementTime={YYYY-MM-DD}`
- 元数据请求：`POST https://www.cninfo.com.cn/new/announcement/bulletin_detail`
  ，查询参数为 `announceId={id}&flag={plate == 'szse'}&announceTime={YYYY-MM-DD}`。
- 证据：巨潮详情页所加载的官方
  [`notice-detail.js`](https://www.cninfo.com.cn/new/assets/js/disclosure/notice-detail.js)。该
  脚本把响应的 `announcement.adjunctUrl` 拼为 `v3_cninfo + "/" + adjunctUrl`，并用浏览器
  `GET` 下载 blob；`v3_cninfo` 在页面中配置为 `https://static.cninfo.com.cn`（协议随页面
  协商）。

实测响应中 `announcement` 至少包含：`secCode`、`secName`、`orgId`、`announcementId`、
`announcementTitle`、`announcementTime`（Unix 毫秒）、`adjunctUrl`、`adjunctSize`（KB）、
`adjunctType`、`columnId`、`announcementType`、`shortTitle`。列表响应也包含这些关键字段。

例如列表和详情均返回：

```json
{
  "secCode": "000568",
  "announcementId": "1223350383",
  "announcementTitle": "2024年年度报告",
  "announcementTime": 1745769600000,
  "adjunctUrl": "finalpage/2025-04-28/1223350383.pdf",
  "adjunctType": "PDF"
}
```

另一个沪市实测：以 `column=sse`、`stock=600188,gssh0600188` 查询年报，返回
`announcementId=1225048701`、标题“兖矿能源2025年年度报告全文”、披露时间
`1774627200000`、附件 `finalpage/2026-03-28/1225048701.PDF`。这也验证了主报告选择
规则必须排除“摘要”，并优先标题含“年度报告全文”的中文主报告。

因此 PDF 的官方公开 URL 是：
[`https://static.cninfo.com.cn/finalpage/2025-04-28/1223350383.pdf`](https://static.cninfo.com.cn/finalpage/2025-04-28/1223350383.pdf)。
调研时 `HEAD` 返回 `200`、`Content-Type: application/pdf`、`Accept-Ranges: bytes`，详情页
也直接将其嵌入 PDF 查看器并提供下载。

## 选取、时点和实现边界

- 分类检索会同时返回“英文版”“摘要”等条目。入库时应以报告期、`announcementTime` 和
  标题精确规则选取正式中文报告，避免把摘要或英文版误当主报告；保留所有候选及选择理由。
- `announcementTime` 是披露可用时间的官方元数据。系统应将其转换为带时区的时间，保存
  原始毫秒、首次观察时间、请求/响应 hash 与 PDF SHA-256；不能以 PDF 的 HTTP
  `Last-Modified` 替代披露时间。
- 下载后可在本地从公开 PDF 提取文本，技术上没有额外 token 或加密要求。此结论仅说明
  **页面已公开提供给浏览器下载**，不是对批量抓取、长期保存、再分发或用文本训练模型的
  许可判断。

## 合规与稳定性判断

页面页脚的
[免责声明](https://www.cninfo.com.cn/new/index) 说明网站努力保证信息准确可靠但不担保
准确性和完整性，并称访问即视为接受声明。该页面没有给出允许自动化批量抓取、文本再利用
或再分发的明确许可。故不能仅凭公开 PDF 宣称“文本提取已获授权”。上线前应向深圳证券
信息有限公司确认使用场景（自动下载频率、本地留存、文本抽取、LLM 处理及再分发），并
按适用的条款、合同和法律执行。

官方、面向程序调用的渠道是
[深证信数据服务 API 文档入口](https://webapi.cninfo.com.cn/#/apiDoc)。其官方首页描述该
服务覆盖上市公司、基金、债券和公告，支持接口访问；页面应用还显示 access token、产品
授权和下载/计费流程。未登录公开页未暴露可无凭据调用的“定期报告列表/原文”接口详情，
因此具体 endpoint、Access Key/Secret 或 token 取得方式、产品范围、QPS、费用和文本许可
必须以开户后的文档/合同为准，不能从网页 XHR 推断。

## 推荐决策

1. 生产自动补齐：采购/开通深证信数据服务，使用其受授权 API，并将上述网页字段作为
   期望映射而非契约。
2. 授权完成前：只在人工确认或极低频、单证券的回退工作流中使用网页端点；节流、缓存、
   禁止并发扫描，遇到响应异常直接 fail-closed。
3. 无论来源：只保存必需的原文和提取结果，保留公告 URL、ID、披露时点、hash 和许可依据；
   不向用户承诺网页端点的稳定性或文本处理授权。

## 附录：上交所、深交所披露页核验（2026-07-23）

### 证券归属与当前白名单

`601899.SH`（紫金矿业）和 `601567.SH`（三星电气）均为**上交所**证券；后者并不是
深市证券，因而不应以深交所接口查询它。上交所官方证券建议数据
[`ssesuggestdata.js`](https://www.sse.com.cn/js/common/ssesuggestdata.js) 也列有
`601567 / 三星电气`。

当前项目的 `OfficialEvidenceStore` 对 `financial_announcement` 仅允许 `cninfo.com.cn`
及其子域名；见
[`official_evidence.py`](../../backend/app/infrastructure/market/official_evidence.py)。因此：

| 官方 PDF host | 当前作为财报证据是否可导入 | 原因 |
| --- | --- | --- |
| `static.sse.com.cn` | 否 | 不在财报 allowlist（仅政策 allowlist 有 `sse.com.cn`） |
| `disc.static.szse.cn` | 否 | 不在财报 allowlist（仅政策 allowlist 有 `szse.cn`） |

即便未来扩展 host，仍应将“由官方检索响应返回的相对附件路径”与已验证的披露元数据
绑定；不要仅按 URL 形式放行或猜测 PDF 文件名。

### 上交所：适用于 601899、601567 的公开网页路径

- 页面：[上交所上市公司信息披露](https://www.sse.com.cn/disclosure/listedinfo/announcement/)
  及其官方脚本
  [`search_listedCompanyInfo_2021.js`](https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_listedCompanyInfo_2021.js)。
- 当前页面使用：`GET https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do`
  （JSONP，`jsonCallBack`）。主要参数为 `isPagination=true`、`pageHelp.pageSize`、
  `pageHelp.pageNo`、`pageHelp.beginPage`、`pageHelp.cacheSize`、`pageHelp.endPage`、
  `SECURITY_CODE`、`TITLE`、`START_DATE`、`END_DATE`、`BULLETIN_TYPE`、`stockType`。
  定期报告分类来自官方
  [`announce_type.json`](https://www.sse.com.cn/disclosure/listedinfo/announcement/json/announce_type.json)：
  年报 `0101`、一季报 `0102`、半年报 `0103`、三季报 `0104`。
- 兼容的历史页面实现使用：`GET
  https://query.sse.com.cn/security/stock/queryCompanyBulletin.do`，参数为 `productId`、
  `securityType`、`reportType2`、`reportType`、`beginDate`、`endDate` 和 `pageHelp.*`。
  两者都只是页面内部的 JSONP 查询，并没有找到被上交所声明为稳定第三方开发 API 的
  文档或 SLA。
- `queryCompanyBulletinNew.do` 实测对 `601899`、`BULLETIN_TYPE=0101` 返回：
  标题“紫金矿业集团股份有限公司2025年年度报告”、披露日 `2026-03-21`、相对路径
  `/disclosure/listedinfo/announcement/c/new/2026-03-21/601899_20260321_PPHD.pdf`；对
  `601567` 返回标题“三星电气2025年年度报告”、披露日 `2026-04-25`、相对路径
  `/disclosure/listedinfo/announcement/c/new/2026-04-25/601567_20260425_YPP2.pdf`。
  响应记录的关键字段包括 `TITLE`、`SSEDATE`、`URL`、`SECURITY_CODE`、
  `SECURITY_NAME`、`BULLETIN_TYPE_DESC`。
- 页面定义 `staticBulletinUrl=//static.sse.com.cn`，所以附件 URL 为
  `https://static.sse.com.cn` 加响应 `URL`。直接自动访问该静态 host 实测可能返回
  `x-tengine-error: denied by bot`，故不能当作可靠运行时下载通道；不得试图绕过其反自动化
  控制。

上交所页面还说明栏目内容由上市公司提供、部分文档经软件自动转换；页脚保留上交所版权。
这不构成对批量下载、文本抽取或再分发的许可。

### 深交所：仅供真正的深市证券使用

虽然这两个持仓不适用，深交所自身网页提供如下路径，适用于例如 `000568.SZ`：

- 页面：[深交所上市公司公告](https://www.szse.cn/disclosure/listed/notice/index.html)；其官方
  脚本为
  [`listedAnnoun.min.js`](https://www.szse.cn/modules/disclosure/js/modules/listedAnnoun.min.js?version=1.2.218)。
- 请求：`POST https://www.szse.cn/api/disc/announcement/annList`，JSON 可为
  `{"stock":["000568"],"channelCode":["listedNotice_disc"],"seDate":["YYYY-MM-DD","YYYY-MM-DD"],"bigCategoryId":["010301"],"pageSize":50,"pageNum":1}`；
  `010301` 为年报类别。
- 响应包含 `title`、`publishTime`、`attachPath`、`attachFormat`、`secCode`；PDF 由
  `https://disc.static.szse.cn/download` + `attachPath` + `?n={文件名}` 构成。该 endpoint
  同样是网页实现，未发现官方开发者 API 合约。对 `601567` 的查询返回空结果，与其上交所
  归属一致。

深交所公告页同样有不保证信息准确、完整的免责声明；没有发现可据以认定批量抓取或文本
再利用获授权的公开许可。
