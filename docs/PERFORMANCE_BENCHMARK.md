# 性能测试基准

> 配套文档：ENGINEERING_ROADMAP.md §23、OBSERVABILITY.md §4。本文档定义性能测试的目标、场景、脚本与验收标准，供实现阶段压测与回归验证照做。
>
> 适用阶段：MVP（本地基准）→ V2（生产级压测）→ V3（大规模扩展验证）。

---

## 1. 设计原则

1. **可复现**：测试环境、数据、脚本固定，结果可对比。
2. **渐进式**：从单接口到全链路，从低并发到高并发。
3. **生产对齐**：测试数据量与生产规模对齐（MVP 50 项目、V2 300 项目）。
4. **自动化**：CI 集成基准测试，性能退化自动告警。

---

## 2. 性能目标

### 2.1 API 响应时间

| 接口 | P50 目标 | P95 目标 | P99 目标 | 备注 |
|---|---|---|---|---|
| `GET /health` | < 10ms | < 50ms | < 100ms | 健康检查 |
| `GET /projects` | < 100ms | < 300ms | < 500ms | 列表查询（50 项目） |
| `GET /project/{id}` | < 50ms | < 150ms | < 300ms | 单项目详情 |
| `POST /run` | < 5s | < 30s | < 60s | 触发分析（50 项目） |
| `POST /re-score/{id}` | < 500ms | < 2s | < 5s | 单项目重算 |
| `GET /insights` | < 200ms | < 500ms | < 1s | 聚合洞察 |
| `POST /feedback` | < 100ms | < 300ms | < 500ms | 提交反馈 |
| `GET /audit` | < 100ms | < 300ms | < 500ms | 审计日志查询 |

### 2.2 吞吐量

| 场景 | MVP 目标 | V2 目标 | V3 目标 |
|---|---|---|---|
| `GET /projects` QPS | 50 | 200 | 1000 |
| `GET /project/{id}` QPS | 100 | 500 | 2000 |
| 并发用户数 | 5 | 50 | 500 |
| 单次 run 项目数 | 50 | 300 | 1000+ |

### 2.3 资源使用

| 资源 | MVP 上限 | V2 上限 |
|---|---|---|
| CPU | 1 核 | 2 核 |
| 内存 | 256MB | 512MB |
| 磁盘 | 1GB | 10GB |
| 网络 | 10Mbps | 100Mbps |

---

## 3. 测试场景

### 3.1 场景一：API 基准测试

#### 3.1.1 单接口延迟
测试单个接口在不同数据量下的响应时间。

```python
# tests/perf/test_api_latency.py
import time
import requests

BASE_URL = "http://localhost:8000"

def test_health_latency():
    """健康检查延迟"""
    latencies = []
    for _ in range(100):
        start = time.time()
        r = requests.get(f"{BASE_URL}/health")
        latencies.append((time.time() - start) * 1000)
        assert r.status_code == 200
    
    p50 = sorted(latencies)[50]
    p95 = sorted(latencies)[95]
    p99 = sorted(latencies)[99]
    
    assert p50 < 10, f"P50 {p50}ms > 10ms"
    assert p95 < 50, f"P95 {p95}ms > 50ms"
    assert p99 < 100, f"P99 {p99}ms > 100ms"

def test_projects_list_latency():
    """项目列表查询延迟"""
    latencies = []
    for _ in range(50):
        start = time.time()
        r = requests.get(f"{BASE_URL}/api/v1/projects?limit=50")
        latencies.append((time.time() - start) * 1000)
        assert r.status_code == 200
    
    p50 = sorted(latencies)[25]
    p95 = sorted(latencies)[47]
    
    assert p50 < 100, f"P50 {p50}ms > 100ms"
    assert p95 < 300, f"P95 {p95}ms > 300ms"
```

#### 3.1.2 并发吞吐量
测试多并发下的 QPS 与错误率。

```python
# tests/perf/test_api_throughput.py
import asyncio
import aiohttp
import time

BASE_URL = "http://localhost:8000"
CONCURRENCY = 10
TOTAL_REQUESTS = 100

async def fetch_project(session, project_id):
    async with session.get(f"{BASE_URL}/api/v1/project/{project_id}") as r:
        return r.status

async def test_concurrent_throughput():
    """并发吞吐量测试"""
    project_ids = [f"test-project-{i}" for i in range(10)]  # 测试数据
    
    async with aiohttp.ClientSession() as session:
        start = time.time()
        
        tasks = []
        for i in range(TOTAL_REQUESTS):
            project_id = project_ids[i % len(project_ids)]
            tasks.append(fetch_project(session, project_id))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        elapsed = time.time() - start
        qps = TOTAL_REQUESTS / elapsed
        
        success = sum(1 for r in results if r == 200)
        errors = TOTAL_REQUESTS - success
        
        assert qps > 50, f"QPS {qps} < 50"
        assert errors == 0, f"Errors: {errors}/{TOTAL_REQUESTS}"
```

---

### 3.2 场景二：Pipeline 端到端

#### 3.2.1 单次 run 耗时
测试完整 pipeline 在不同项目数下的耗时。

```python
# tests/perf/test_pipeline_e2e.py
import time
import requests

BASE_URL = "http://localhost:8000"

def test_run_50_projects():
    """50 项目完整 run 耗时"""
    start = time.time()
    r = requests.post(f"{BASE_URL}/api/v1/run", json={"source": "seed", "limit": 50})
    elapsed = time.time() - start
    
    assert r.status_code == 200
    assert elapsed < 60, f"50 projects took {elapsed}s > 60s"

def test_run_100_projects():
    """100 项目完整 run 耗时（V2）"""
    start = time.time()
    r = requests.post(f"{BASE_URL}/api/v1/run", json={"source": "seed", "limit": 100})
    elapsed = time.time() - start
    
    assert r.status_code == 200
    assert elapsed < 120, f"100 projects took {elapsed}s > 120s"
```

#### 3.2.2 单项目分析耗时
测试单个项目从 collect 到 score 的端到端延迟。

```python
# tests/perf/test_single_project_latency.py
def test_single_project_analysis():
    """单项目分析延迟"""
    # 触发 re-score 单项目
    project_id = "test-project-001"
    
    start = time.time()
    r = requests.post(f"{BASE_URL}/api/v1/re-score/{project_id}")
    elapsed = time.time() - start
    
    assert r.status_code == 200
    assert elapsed < 3, f"Single project took {elapsed}s > 3s (rule only)"
```

---

### 3.3 场景三：数据库性能

#### 3.3.1 查询性能
测试不同数据量下的查询性能。

```python
# tests/perf/test_db_query.py
import sqlite3
import time

DB_PATH = "backend/data/airdrop.db"

def test_query_1k_projects():
    """1k 项目查询性能"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    start = time.time()
    cursor.execute("SELECT * FROM projects ORDER BY score DESC LIMIT 50")
    results = cursor.fetchall()
    elapsed = (time.time() - start) * 1000
    
    assert elapsed < 100, f"Query took {elapsed}ms > 100ms"
    conn.close()

def test_query_10k_projects():
    """10k 项目查询性能（V2）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    start = time.time()
    cursor.execute("SELECT * FROM projects WHERE label='FARM' ORDER BY score DESC LIMIT 50")
    results = cursor.fetchall()
    elapsed = (time.time() - start) * 1000
    
    assert elapsed < 200, f"Query took {elapsed}ms > 200ms"
    conn.close()
```

#### 3.3.2 写入性能
测试批量写入的吞吐量。

```python
# tests/perf/test_db_write.py
def test_batch_insert_50():
    """批量插入 50 项目"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    start = time.time()
    conn.execute("BEGIN TRANSACTION")
    for i in range(50):
        cursor.execute(
            "INSERT OR REPLACE INTO projects (id, name, sector, stage, source) VALUES (?,?,?,?,?)",
            (f"perf-test-{i}", f"Project {i}", "L2", "testnet", "seed")
        )
    conn.commit()
    elapsed = (time.time() - start) * 1000
    
    assert elapsed < 500, f"Batch insert took {elapsed}ms > 500ms"
    conn.close()
```

---

### 3.4 场景四：前端性能

#### 3.4.1 Lighthouse 评分
使用 Lighthouse 评估前端性能。

```bash
# 运行 Lighthouse
npx lighthouse http://localhost:8000/ --output=json --output-path=reports/lighthouse.json

# 验收标准
# - Performance ≥ 90
# - Accessibility ≥ 95
# - Best Practices ≥ 90
# - SEO ≥ 80
```

#### 3.4.2 首屏加载时间
测试 Dashboard 首屏加载时间。

```javascript
// tests/perf/test_fcp.js (Playwright)
const { test, expect } = require('@playwright/test');

test('First Contentful Paint < 2s', async ({ page }) => {
  await page.goto('http://localhost:8000/');
  
  const fcp = await page.evaluate(() => {
    return new Promise((resolve) => {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.name === 'first-contentful-paint') {
            resolve(entry.startTime);
          }
        }
      }).observe({ type: 'paint', buffered: true });
    });
  });
  
  expect(fcp).toBeLessThan(2000);
});
```

---

## 4. 压测脚本（Locust）

### 4.1 Locust 配置

```python
# tests/perf/locustfile.py
from locust import HttpUser, task, between

class DashboardUser(HttpUser):
    wait_time = between(1, 3)  # 用户间隔 1-3 秒
    
    @task(10)
    def view_projects(self):
        """浏览项目列表（高频操作）"""
        self.client.get("/api/v1/projects?limit=50")
    
    @task(5)
    def view_project_detail(self):
        """查看项目详情"""
        self.client.get("/api/v1/project/test-project-001")
    
    @task(3)
    def filter_projects(self):
        """筛选项目"""
        self.client.get("/api/v1/projects?label=FARM&sector=L2")
    
    @task(2)
    def view_insights(self):
        """查看洞察"""
        self.client.get("/api/v1/insights")
    
    @task(1)
    def submit_feedback(self):
        """提交反馈"""
        self.client.post("/api/v1/feedback", json={
            "project_id": "test-project-001",
            "signal": "useful"
        })
```

### 4.2 运行压测

```bash
# 安装 Locust
pip install locust

# 运行压测（Web UI）
locust -f tests/perf/locustfile.py --host=http://localhost:8000

# 运行压测（CLI 模式）
locust -f tests/perf/locustfile.py \
  --host=http://localhost:8000 \
  --users 50 \
  --spawn-rate 10 \
  --run-time 5m \
  --headless \
  --csv=reports/locust
```

### 4.3 压测验收标准

| 指标 | 通过条件 |
|---|---|
| 平均响应时间 | < 500ms |
| P95 响应时间 | < 1000ms |
| 错误率 | < 0.1% |
| QPS | > 50（MVP）/ > 200（V2） |

---

## 5. 性能回归测试

### 5.1 CI 集成

```yaml
# .github/workflows/perf.yml
name: Performance Regression
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  perf:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      
      - name: Install dependencies
        run: pip install -r backend/requirements.txt
      
      - name: Start server
        run: |
          python backend/run.py &
          sleep 5
      
      - name: Run API latency tests
        run: pytest tests/perf/test_api_latency.py -v
      
      - name: Run pipeline e2e tests
        run: pytest tests/perf/test_pipeline_e2e.py -v
      
      - name: Run Locust smoke
        run: |
          locust -f tests/perf/locustfile.py \
            --host=http://localhost:8000 \
            --users 10 \
            --spawn-rate 5 \
            --run-time 1m \
            --headless \
            --csv=reports/locust
      
      - name: Upload reports
        uses: actions/upload-artifact@v4
        with:
          name: perf-reports
          path: reports/
```

### 5.2 性能基线

```json
// reports/baseline.json
{
  "version": "v1.0",
  "timestamp": "2026-07-08T08:00:00Z",
  "metrics": {
    "health_p50_ms": 5,
    "projects_list_p50_ms": 45,
    "project_detail_p50_ms": 25,
    "run_50_projects_s": 12.5,
    "single_project_re_score_ms": 850,
    "db_query_1k_ms": 15,
    "db_batch_insert_50_ms": 120
  }
}
```

### 5.3 回归告警规则

| 指标 | 退化阈值 | 告警级别 |
|---|---|---|
| API P50 延迟 | > 基线 150% | warning |
| API P95 延迟 | > 基线 200% | critical |
| 错误率 | > 1% | critical |
| 单次 run 耗时 | > 基线 200% | warning |
| 内存使用 | > 基线 150% | warning |

---

## 6. 性能优化清单

### 6.1 已知优化点

| 优化项 | 阶段 | 预期收益 |
|---|---|---|
| 项目列表分页 | MVP | 避免全量加载 |
| 数据库索引 | MVP | 查询加速 10x |
| 外部源缓存 | MVP | 减少 API 调用 |
| asyncio 并行 agent | MVP | 4x 吞吐提升 |
| Redis 缓存（V2） | V2 | 读 QPS 10x |
| PostgreSQL 切换 | V2 | 并发写提升 |
| 前端虚拟滚动 | V2 | 大数据量流畅滚动 |
| Celery 异步任务 | V3 | 水平扩展 worker |

### 6.2 监控指标

```python
# 关键性能指标（Prometheus）
airdrop_api_request_duration_seconds  # API 延迟直方图
airdrop_api_requests_total            # API 请求计数
airdrop_run_duration_seconds          # Pipeline 耗时
airdrop_run_projects_count            # 单次 run 项目数
airdrop_db_query_duration_seconds     # DB 查询延迟
airdrop_db_connections_active         # DB 连接数
```

---

## 7. 测试数据生成

```python
# tests/perf/generate_test_data.py
"""生成性能测试数据"""

def generate_projects(count: int = 1000):
    """生成测试项目数据"""
    sectors = ["L2", "DeFi", "NFT", "Gaming", "AI", "DePIN", "Restaking"]
    stages = ["testnet", "mainnet", "ideation"]
    labels = ["FARM", "WATCH", "IGNORE"]
    
    projects = []
    for i in range(count):
        project = {
            "id": f"perf-test-{i:06d}",
            "name": f"Test Project {i}",
            "url": f"https://project{i}.example.com",
            "sector": sectors[i % len(sectors)],
            "stage": stages[i % len(stages)],
            "score": 100 - (i % 100),
            "label": labels[i % len(labels)],
            "source": "seed",
        }
        projects.append(project)
    
    return projects

if __name__ == "__main__":
    import json
    projects = generate_projects(1000)
    with open("tests/perf/test_data_1k.json", "w") as f:
        json.dump(projects, f)
```

---

_文档版本：v1.0 · 配套 ENGINEERING_ROADMAP.md §23 / OBSERVABILITY.md §4 · 实现阶段按场景逐步落地测试。_
