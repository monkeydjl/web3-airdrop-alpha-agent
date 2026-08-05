# ──────────────────────────────────────────────
# pytest 全局配置 — 测试环境隔离
# ──────────────────────────────────────────────
# 为什么需要这个文件：
# config.py 在模块导入时就执行 `settings = Settings()`，它会读取仓库根目录
# 的 .env。本地开发者若把 .env 配成生产参数（APP_ENV=production / HOST=0.0.0.0
# / API_KEY 空），Settings() 的“生产环境安全自检”会在实例化时抛错，导致 pytest
# 在 collection 阶段直接崩溃（不是断言失败，而是 import 就炸）。
#
# 解决办法：在任何 app 模块被导入之前（即本文件顶层、其它 import 之前）强制把
# 进程环境变量改成安全的测试值。pydantic-settings 的优先级是 环境变量 > .env
# 文件，因此这里的强制覆盖能压过操作员本地的生产 .env。
#
# 用强制赋值而非 setdefault：目的就是要盖掉 .env 里可能存在的生产配置。
# 注意：这不会削弱安全自检本身——test_review_regressions.py 里用
# `Settings(_env_file=None, app_env="production", ...)` 显式构造的用例走的是
# init kwargs，优先级高于环境变量，仍会正常触发拒绝逻辑。
import os

os.environ["APP_ENV"] = "test"
os.environ["API_KEY"] = ""
os.environ["HOST"] = "127.0.0.1"
