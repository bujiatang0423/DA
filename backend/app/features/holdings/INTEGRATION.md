# 持仓分析集成交接

持仓分析只产生可审计的人工建议；`auto_trade_enabled` 固定为 `false`，任何建议都要求
人工确认。组合根接线必须保留同一个点时钟：先读取组合快照，再用真实持仓证券 ID 读取 PIT
快照，并将 manifest、策略版本和 `as_of_time` 一并校验。

## 集成要求

1. 在 Alembic 迁移中导入本 feature 的 ORM metadata，创建分析结果及建议明细表；迁移必须可
   重复执行并保留 manifest 冲突拒绝语义。
2. 用 PIT warehouse、`PortfolioReader`、`StrategyInputBuilder`、`V212StrategyEngine` 和
   `HoldingAnalysisRepository` 构造 `HoldingAnalysisService`，禁止注入 LA runtime 或 Markdown
   parser。
3. 将同一个 `PortfolioWriter` 注入持仓查询、人工校正和实际成交路由；校正使用 optimistic
   version 和审计原因，实际成交使用真实价格、费用、方向、数量和成交时间。
4. 在全局 feature registry 调用 `build_holding_feature()`，并注册
   `holdingFeature` 到 Web 导航；API DTO 必须从生成的 OpenAPI schema 派生。
5. 导出 OpenAPI 并连续运行两次 `npm run generate:api`，第二次生成不得产生 diff。
6. 运行端到端验收：legacy 持仓展示、人工校正、实际成交、异步分析、持久化结果读取及 API/
   worker 重启后查询。
7. 审计日志不得包含持仓备注、原始 LLM 输入/输出、源代码路径或 API secret；任何缺失数据
   都必须 fail-closed。

## 验收命令

```bash
python -m pytest backend/tests/features/holdings -q
python -m ruff check backend/app/features/holdings backend/tests/features/holdings
python -m mypy backend/app/features/holdings
npm --prefix web test -- --run src/features/holdings
npm --prefix web run typecheck
npm --prefix web run build
```
