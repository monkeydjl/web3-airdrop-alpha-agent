# ──────────────────────────────────────────────
# Load Test — Web3 Airdrop Alpha Agent System
# ──────────────────────────────────────────────
# 使用 locust 进行 API 负载测试。
# 运行：locust -f tests/load/locustfile.py --host http://localhost:8000
# ──────────────────────────────────────────────

from __future__ import annotations

from locust import HttpUser, between, task


class AirdropUser(HttpUser):
    """模拟用户行为：查看项目列表、查询项目详情、调用健康检查。"""

    wait_time = between(1, 3)

    @task(3)
    def list_projects(self) -> None:
        self.client.get("/api/v1/projects?limit=20")

    @task(2)
    def get_project(self) -> None:
        # 使用示例 project_id；生产环境应从数据源读取
        self.client.get("/api/v1/projects/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d")

    @task(1)
    def health_check(self) -> None:
        self.client.get("/health")
