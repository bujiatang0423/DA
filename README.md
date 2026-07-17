# DA 独立交易研究平台

DA 是独立于 LA 的四维盾剑 V2.12 研究与决策平台，不执行自动交易。

## 四项功能

- 候选推荐：提交点时分析任务，策略引擎负责确定性筛选与排序。
- 持仓分析：读取点时持仓快照，计算敞口、盈亏、回撤和 ATR 止损。
- 历史回测：使用点时快照、T+1、成交量参与率、滑点和费用进行研究回测。
- Web 可视化：React 页面调用 API 展示任务、候选、持仓和 walk-forward 计划。

## 本地运行

```bash
docker compose up -d postgres
python -m alembic upgrade head
python -m backend.app.main
cd web && npm run dev
```

完成数据库迁移后，API 默认监听 `127.0.0.1:8000`，Web 默认监听 `127.0.0.1:5173`。

## 验证

```bash
make verify
```

真实交易动作始终需要人工确认；系统固定输出 `auto_trade_enabled=false`。
