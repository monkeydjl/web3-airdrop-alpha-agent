# HANDOFF — 2026-07-26

## 项目当前状态

多智能体 Web3 空投评分系统，后端 FastAPI + 前端 Next.js 16，已完成系统审查修复（采集链路 / 流水线 / 安全 / 评分规范 / 前端），2428 测试声称全绿但本次提交后**未实际跑验证**。工作区已清零，7 个 commit 在本地未推送。

## 本次会话做了什么

1. **通读整个项目** — 后端全部源码（agents / collectors / opportunity / routers / services / db / pipeline_run / config / auth / scheduler / repository）、前端 12 页面、文档 38 份、测试套件、Docker / 可观测性配置
2. **分 7 批提交 224 个工作区变更**，详见 `SESSION_MEMORY_2026-07-26.md`
3. **补写记忆文档** — 首份 SESSION_MEMORY + HANDOFF

## 进行中的工作（未完成）

- **无进行中任务** — 本次会话只做了通读 + 提交，无未完成的功能开发

## 关键决定

- **旧 HTML 原型全部删除** — `airdrop-alpha-console/` 已被 `frontend-next/` 完全替代
- **旧顶层 `tests/` 目录删除** — 测试已迁移到 `backend/tests/`，旧目录是空壳
- **提交分批而非一次性** — 7 个 commit 按 type(scope) 规范，便于 revert 和 review
- **未补 verify.ps1** — 验证入口仍为 `cd backend && pytest`

## 如何运行与验证

### 启动

```bash
# 后端
cd backend
pip install -e ".[dev]"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 前端（另开终端）
cd frontend-next
npm install
npm run dev   # http://localhost:3002

# Windows 一键
Start.bat
```

### 验证

```bash
cd backend
pytest                    # 全量测试（声称 2428 passed, 4 skipped）
pytest --cov=app          # 覆盖率（≥80% 才通过）
ruff check .              # lint
ruff format --check .     # 格式检查
```

### 当前验证状态

- **未验证** — 本次会话提交后未运行 pytest / ruff，测试基线 2428 是 README 声称的数字
- 最近一次声称通过：2026-07-26（CHANGELOG 记录的审查修复批次）

## 已知问题 / 风险

1. **未跑验证** — 7 个 commit 后未运行测试，可能有回归
2. **无 verify.ps1** — 健康五件套缺验证脚本，当前依赖手动 `cd backend && pytest`
3. **`backend/.pytest_tmp/` 权限拒绝** — git status 有 warning，不影响提交但可能影响 pytest 运行
4. **7 个 commit 未推送** — 全部在本地 `master`，未 `git push`
5. **无远程仓库配置确认** — 未检查是否有 remote 可推送

## 下一步（给下一个会话的行动清单）

- [ ] **跑验证** — `cd backend && pytest -q`，确认 2428 tests 全绿（若有失败，查看 `SYSTEM_AUDIT_REPORT.md` 对应修复项）
- [ ] **补 verify.ps1** — 创建 `scripts/verify.ps1`，封装 `cd backend && pytest -q --cov=app`
- [ ] **考虑 git push** — 确认远程仓库地址，推送 7 个 commit
- [ ] **下一阶段功能** — 参见 `docs/V2_TASKS.md` 和 `docs/ENGINEERING_ROADMAP.md` 中未完成的 V2/V3 项

---

_交接日期：2026-07-26 · 会话记忆见 `SESSION_MEMORY_2026-07-26.md` · 变更记录见 `CHANGELOG.md`_
