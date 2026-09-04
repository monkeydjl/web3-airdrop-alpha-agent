"""决策推送（Outbound Notifier，ACTION_LOOP_DESIGN.md §2，F1）。

把评分决策的变化（FARM 跨线 / 降级 / 新 FARM / 观察列表强信号 / 每日摘要）
经出站通道（Telegram Bot API / Discord Webhook）推送给用户。

分层：

- `evaluator.py` —— 评估器：只读数据库的既成事实，产出「值得推送的事件」。
  可以随便重复跑（cron 重跑 / 进程重启），去重靠 notify_log 的
  `(event_key, channel)` 唯一约束，不靠调用方自觉。
- `senders.py` —— 发送器：一条通道一个类，出站必须走 `utils/fetcher`
  （域名白名单 fail-closed 对这条出口自动生效）。
- `service.py` —— 服务层：评估 → 去重入库 → 发送；调度 job 与 pipeline
  收尾钩子都只调它。

Reference:
- docs/ACTION_LOOP_DESIGN.md §2
- docs/OBSERVABILITY.md（notify.* 日志事件）
"""
