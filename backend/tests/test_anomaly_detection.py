from __future__ import annotations

import sqlite3

from app.db import DbConnection
from app.services.anomaly_detection import AnomalyDetectionService, AnomalyReport


def _create_test_db() -> DbConnection:
    """Create in-memory SQLite connection with projects and collection tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT,
            sector TEXT NOT NULL,
            stage TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            label TEXT DEFAULT 'IGNORE',
            raw_signals TEXT,
            narrative_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE raw_projects (
            raw_id TEXT PRIMARY KEY,
            source_id TEXT,
            quarantined INTEGER DEFAULT 0,
            quarantine_reason TEXT,
            processed INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE collection_logs (
            log_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            started_at TIMESTAMP NOT NULL,
            status TEXT
        )
        """
    )
    return conn


def test_detect_score_drift_empty_projects():
    conn = _create_test_db()
    svc = AnomalyDetectionService(conn)
    summary, anomalies = svc.detect_score_drift()
    assert summary.total_projects == 0
    assert summary.mean_score == 0.0
    assert len(anomalies) == 0


def test_detect_score_drift_normal():
    conn = _create_test_db()
    # 插入 10 个均匀分布的项目，均值 50 分左右，无越界与极端偏斜
    for i in range(10):
        score = 45 + i
        label = "FARM" if i < 2 else ("WATCH" if i < 7 else "IGNORE")
        conn.execute(
            "INSERT INTO projects (id, name, sector, stage, score, label) VALUES (?, ?, ?, ?, ?, ?)",
            (f"p-{i}", f"Project {i}", "DeFi", "mainnet", score, label),
        )
    conn.commit()

    svc = AnomalyDetectionService(conn)
    summary, anomalies = svc.detect_score_drift()
    assert summary.total_projects == 10
    assert 48.0 <= summary.mean_score <= 52.0
    assert summary.label_counts["FARM"] == 2
    assert summary.label_ratios["FARM"] == 0.20
    assert len(anomalies) == 0


def test_detect_score_drift_mean_shift_warning():
    conn = _create_test_db()
    # 插入 10 个均值 80 分的高分项目（偏离基准 50 分 > 15 分）
    for i in range(10):
        conn.execute(
            "INSERT INTO projects (id, name, sector, stage, score, label) VALUES (?, ?, ?, ?, ?, ?)",
            (f"p-{i}", f"Project {i}", "AI", "testnet", 80, "WATCH"),
        )
    conn.commit()

    svc = AnomalyDetectionService(conn)
    summary, anomalies = svc.detect_score_drift()
    assert summary.mean_drift == 30.0
    mean_anomalies = [a for a in anomalies if a.id == "score_mean_drift"]
    assert len(mean_anomalies) == 1
    assert mean_anomalies[0].severity == "warning"


def test_detect_score_drift_farm_skew_high():
    conn = _create_test_db()
    # 插入 10 个项目，其中 6 个为 FARM (60% > 40%)
    for i in range(10):
        label = "FARM" if i < 6 else "WATCH"
        conn.execute(
            "INSERT INTO projects (id, name, sector, stage, score, label) VALUES (?, ?, ?, ?, ?, ?)",
            (f"p-{i}", f"Project {i}", "L2", "mainnet", 50, label),
        )
    conn.commit()

    svc = AnomalyDetectionService(conn)
    _summary, anomalies = svc.detect_score_drift()
    skew_anomalies = [a for a in anomalies if a.id == "label_skew_farm_high"]
    assert len(skew_anomalies) == 1
    assert skew_anomalies[0].severity == "warning"


def test_detect_score_drift_zero_spike_critical():
    conn = _create_test_db()
    # 插入 10 个项目，其中 5 个为 0 分 (50% > 30%)
    for i in range(10):
        score = 0 if i < 5 else 60
        conn.execute(
            "INSERT INTO projects (id, name, sector, stage, score, label) VALUES (?, ?, ?, ?, ?, ?)",
            (f"p-{i}", f"Project {i}", "NFT", "ideation", score, "IGNORE"),
        )
    conn.commit()

    svc = AnomalyDetectionService(conn)
    _summary, anomalies = svc.detect_score_drift()
    zero_anomalies = [a for a in anomalies if a.id == "score_zero_spike"]
    assert len(zero_anomalies) == 1
    assert zero_anomalies[0].severity == "critical"


def test_detect_data_quality_p0_violation():
    conn = _create_test_db()
    # 插入缺失 P0 字段 (如 name 为空) 的项目
    conn.execute(
        "INSERT INTO projects (id, name, sector, stage, score, label) VALUES (?, ?, ?, ?, ?, ?)",
        ("p-invalid", "", "DeFi", "mainnet", 50, "WATCH"),
    )
    conn.commit()

    svc = AnomalyDetectionService(conn)
    summary, anomalies = svc.detect_data_quality_issues()
    p0_anomalies = [a for a in anomalies if a.id == "p0_completeness_violation"]
    assert len(p0_anomalies) == 1
    assert p0_anomalies[0].severity == "critical"
    assert summary.p0_completeness < 1.0


def test_run_all_checks_aggregation_and_caching():
    conn = _create_test_db()
    conn.execute(
        "INSERT INTO projects (id, name, sector, stage, score, label) VALUES (?, ?, ?, ?, ?, ?)",
        ("p-1", "Valid Project", "DeFi", "mainnet", 50, "WATCH"),
    )
    conn.commit()

    svc = AnomalyDetectionService(conn)
    report = svc.run_all_checks(force_refresh=True)
    assert isinstance(report, AnomalyReport)
    assert report.overall_status in ("healthy", "warning", "critical")
    assert report.drift_summary.total_projects == 1

    # 验证缓存返回
    report2 = svc.run_all_checks(force_refresh=False)
    assert report2.checked_at == report.checked_at
