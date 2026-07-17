# DA 启动脚本设计

## 目标

提供一个从 DA 根目录执行的一键脚本，先清理 8000（FastAPI）和 5173（Vite）端口上的监听进程，再后台启动前后端服务。

## 行为

- `scripts/start.sh start`：清理端口、创建日志/PID 目录并启动两个服务。
- `scripts/start.sh stop`：停止脚本记录的两个服务，并再次清理对应端口。
- `scripts/start.sh status`：显示 PID、端口和进程状态。
- 可通过 `DA_API_PORT`、`DA_WEB_PORT` 覆盖默认端口。
- 只终止指定 TCP 监听端口上的进程，不执行全局进程清理。

日志写入 `data/logs/`，PID 写入 `data/run/`。脚本失败时返回非零退出码。
