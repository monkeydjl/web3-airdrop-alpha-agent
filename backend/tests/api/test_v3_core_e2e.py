"""End-to-End integration tests for V3 Core Systems (W12-05).

Verifies the complete integration and cross-feature workflows of:
1. W12-01: Multi-Wallet Strategy Recommendation Engine (US-019).
2. W12-02: Project Memory (evolution timeline) & User Memory (adaptive profiling & personalized reranking).
3. W12-03: Multi-Instance HA & Leader Election (distributed lease, heartbeat, failover).
4. W12-04: Anomaly Detection Engine (score drift, zero-score surge, data quality degradation).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
from app.main import create_app
from app.services.anomaly_detection import AnomalyDetectionService
from app.services.leader_election import LeaderElector
from app.services.user_memory import _CLEARED_USERS


@pytest.fixture(autouse=True)
def clean_v3_core_db(tmp_path, monkeypatch):
    """Ensure a clean, isolated SQLite database for V3 core integration tests."""
    test_db = str(tmp_path / "v3_core_e2e.db")
    monkeypatch.setattr(settings, "db_path", test_db)
    monkeypatch.setattr(settings, "api_key", "test-admin-secret-api-key")
    monkeypatch.setattr(settings, "jwt_secret", "test-v3-e2e-jwt-secret-at-least-32-chars-long!")
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    monkeypatch.setattr(settings, "enable_events_tracking", True)
    monkeypatch.setattr(settings, "ha_enabled", False)

    _CLEARED_USERS.clear()
    AnomalyDetectionService._cached_report = None
    AnomalyDetectionService._cached_at = 0.0
    init_db()

    with get_connection() as conn:
        conn.execute("DELETE FROM leader_election")
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM watchlist")
        conn.execute("DELETE FROM project_skips")
        conn.execute("DELETE FROM interactions")
        conn.execute("DELETE FROM project_history")
        conn.execute("DELETE FROM collection_logs")
        conn.execute("DELETE FROM raw_projects")
        conn.execute("DELETE FROM projects")
        conn.execute("DELETE FROM users")
        conn.commit()

    yield

    _CLEARED_USERS.clear()
    AnomalyDetectionService._cached_report = None
    AnomalyDetectionService._cached_at = 0.0
    with get_connection() as conn:
        conn.execute("DELETE FROM leader_election")
        conn.execute("DELETE FROM project_history")
        conn.execute("DELETE FROM projects")
        conn.commit()


class TestV3CoreFullLifecycleE2E:
    """Full 6-stage lifecycle integration test covering W12-01 through W12-04."""

    def test_full_v3_core_lifecycle(self, monkeypatch):
        # ══════════════════════════════════════════════════════════════
        # Stage 1: Multi-Instance HA Cluster Startup & Election (W12-03)
        # ══════════════════════════════════════════════════════════════
        monkeypatch.setattr(settings, "ha_enabled", True)
        monkeypatch.setattr(settings, "ha_lease_ttl_seconds", 20)
        monkeypatch.setattr(settings, "ha_heartbeat_interval_seconds", 2)

        # Instance Alpha & Instance Beta electors
        elector_alpha = LeaderElector(
            instance_id="inst_alpha",
            lease_ttl_seconds=20,
            heartbeat_interval_seconds=2,
        )
        elector_beta = LeaderElector(
            instance_id="inst_beta",
            lease_ttl_seconds=20,
            heartbeat_interval_seconds=2,
        )

        # Alpha acquires lease first
        assert elector_alpha.acquire_or_renew() is True
        assert elector_alpha.is_leader is True

        # Beta attempts to acquire lease; fails because Alpha holds it
        assert elector_beta.acquire_or_renew() is False
        assert elector_beta.is_leader is False

        # Configure App Alpha (Leader instance) and App Beta (Follower instance)
        app_alpha = create_app(leader_elector=elector_alpha)
        app_beta = create_app(leader_elector=elector_beta)

        with TestClient(app_alpha) as client_alpha, TestClient(app_beta) as client_beta:
            # ══════════════════════════════════════════════════════════════
            # Stage 1: Multi-Instance HA Cluster Startup & Election (W12-03)
            # ══════════════════════════════════════════════════════════════
            res_alpha = client_alpha.get("/api/v1/ha/status")
            assert res_alpha.status_code == 200
            data_alpha = res_alpha.json()["data"]
            assert data_alpha["ha_enabled"] is True
            assert data_alpha["instance_id"] == "inst_alpha"
            assert data_alpha["is_leader"] is True
            assert data_alpha["current_leader"] == "inst_alpha"
            assert data_alpha["status"] == "leader"

            res_beta = client_beta.get("/api/v1/ha/status")
            assert res_beta.status_code == 200
            data_beta = res_beta.json()["data"]
            assert data_beta["ha_enabled"] is True
            assert data_beta["instance_id"] == "inst_beta"
            assert data_beta["is_leader"] is False
            assert data_beta["current_leader"] == "inst_alpha"
            assert data_beta["status"] == "follower"

            # ══════════════════════════════════════════════════════════════
            # Stage 2: Project Ingestion & Multi-Wallet Strategy (W12-01)
            # ══════════════════════════════════════════════════════════════
            # Seed projects into the shared database
            with get_connection() as conn:
                # 1. High-sybil L2 project (FARM)
                conn.execute(
                    """
                    INSERT INTO projects (
                        id, name, sector, stage, score, label, confidence, url,
                        raw_signals, risk_json, created_at, updated_at
                    ) VALUES (
                        'proj_l2_scroll', 'Scroll L2', 'L2', 'mainnet', 88.0, 'FARM', 0.95, 'https://scroll.io',
                        ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        json.dumps({
                            "source": "seed",
                            "no_token_yet": True,
                            "has_testnet": True,
                            "has_points_program": True,
                            "farming_cost": "high",
                        }),
                        json.dumps({
                            "overall_risk_score": 35,
                            "sybil_difficulty": "high",
                        }),
                    ),
                )

                # 2. Low-friction Infra testnet project with points (FARM)
                conn.execute(
                    """
                    INSERT INTO projects (
                        id, name, sector, stage, score, label, confidence, url,
                        raw_signals, risk_json, created_at, updated_at
                    ) VALUES (
                        'proj_infra_fuel', 'Fuel Network', 'Infra', 'testnet', 82.0, 'FARM', 0.90, 'https://fuel.network',
                        ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        json.dumps({
                            "source": "seed",
                            "no_token_yet": True,
                            "has_testnet": True,
                            "has_points_program": True,
                            "farming_cost": "low",
                        }),
                        json.dumps({
                            "overall_risk_score": 20,
                            "sybil_difficulty": "low",
                        }),
                    ),
                )

                # 3. Already launched DeFi project (IGNORE veto)
                conn.execute(
                    """
                    INSERT INTO projects (
                        id, name, sector, stage, score, label, confidence, url,
                        raw_signals, risk_json, created_at, updated_at
                    ) VALUES (
                        'proj_defi_uni', 'Uniswap Protocol', 'DeFi', 'mainnet', 45.0, 'IGNORE', 0.99, 'https://uniswap.org',
                        ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        json.dumps({
                            "source": "seed",
                            "no_token_yet": False,
                            "veto": "already_launched",
                        }),
                        json.dumps({
                            "overall_risk_score": 15,
                        }),
                    ),
                )
                conn.commit()

            # Query Multi-Wallet Strategy for High-Sybil L2 Project
            admin_headers = {"X-API-Key": "test-admin-secret-api-key"}
            res_l2 = client_alpha.get("/api/v1/projects/proj_l2_scroll/multi-wallet-strategy", headers=admin_headers)
            assert res_l2.status_code == 200
            strat_l2 = res_l2.json()["data"]
            assert strat_l2["project_id"] == "proj_l2_scroll"
            assert strat_l2["status"] == "recommended"
            assert strat_l2["tier"] in ("single_curated", "small_cluster")
            assert strat_l2["recommended_wallets_optimal"] >= 1
            assert strat_l2["total_capital_usd_max"] > 0
            assert len(strat_l2["hygiene_guidelines"]) >= 4
            rule_ids = [r["rule_id"] for r in strat_l2["hygiene_guidelines"]]
            assert "zero_wallet_transfer" in rule_ids
            assert "temporal_dispersion" in rule_ids
            assert "environment_isolation" in rule_ids
            assert "path_differentiation" in rule_ids

            # Query Multi-Wallet Strategy for Low-Friction Infra Project (Cluster scale)
            res_infra = client_alpha.get("/api/v1/projects/proj_infra_fuel/multi-wallet-strategy", headers=admin_headers)
            assert res_infra.status_code == 200
            strat_infra = res_infra.json()["data"]
            assert strat_infra["status"] == "recommended"
            assert strat_infra["recommended_wallets_optimal"] >= 3

            # Query Multi-Wallet Strategy for Already-Launched Project (Ineligible)
            res_uni = client_alpha.get("/api/v1/projects/proj_defi_uni/multi-wallet-strategy", headers=admin_headers)
            assert res_uni.status_code == 200
            strat_uni = res_uni.json()["data"]
            assert strat_uni["status"] == "ineligible"
            assert strat_uni["recommended_wallets_optimal"] == 0
            assert strat_uni["tier"] == "not_recommended"

            # ══════════════════════════════════════════════════════════════
            # Stage 3: Evolution History & Project Memory (W12-02)
            # ══════════════════════════════════════════════════════════════
            # Seed historical snapshots in project_history table
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO project_history (
                        project_id, run_id, score, label, stage, snapshot
                    ) VALUES
                    ('proj_l2_scroll', 'run_001', 65, 'WATCH', 'testnet', '{}'),
                    ('proj_l2_scroll', 'run_002', 78, 'WATCH', 'testnet', '{}'),
                    ('proj_l2_scroll', 'run_003', 88, 'FARM', 'mainnet', '{}')
                    """
                )
                conn.commit()

            # Query Project Evolution Timeline via API
            res_timeline = client_alpha.get("/api/v1/projects/proj_l2_scroll/timeline", headers=admin_headers)
            assert res_timeline.status_code == 200
            timeline_data = res_timeline.json()["data"]
            assert timeline_data["project_id"] == "proj_l2_scroll"
            assert timeline_data["snapshot_count"] == 3
            assert timeline_data["score_trend"] == "rising"
            assert timeline_data["score_volatility"] > 0.0
            assert "testnet" in timeline_data["stage_progression"]
            assert "mainnet" in timeline_data["stage_progression"]
            assert "Scroll L2" in timeline_data["llm_context_summary"]

            # ══════════════════════════════════════════════════════════════
            # Stage 4: User Actions & Dynamic Memory Adaptation (W12-02)
            # ══════════════════════════════════════════════════════════════
            # Create an analyst user
            reg_res = client_alpha.post(
                "/api/v1/auth/register",
                json={"email": "v3_analyst@example.com", "password": "SecurePassword123!", "display_name": "V3Analyst"},
            )
            assert reg_res.status_code == 200
            token = reg_res.json()["access_token"]
            auth_headers = {"Authorization": f"Bearer {token}"}

            # 1. Check initial fresh user profile
            prof_res_initial = client_alpha.get("/api/v1/user-profile", headers=auth_headers)
            assert prof_res_initial.status_code == 200
            prof_data_initial = prof_res_initial.json()["data"]
            assert prof_data_initial["engagement_summary"]["total_signals"] == 0

            # 2. User interacts: Leaves positive feedback for Scroll L2
            fb_res = client_alpha.post(
                "/api/v1/feedback",
                headers=auth_headers,
                json={"project_id": "proj_l2_scroll", "signal": "useful", "outcome": "airdropped"},
            )
            assert fb_res.status_code == 200

            # 3. User interacts: Adds Scroll L2 to watchlist
            watch_res = client_alpha.post("/api/v1/watchlist/proj_l2_scroll", headers=auth_headers, json={})
            assert watch_res.status_code == 200

            # 4. User interacts: Skips Uniswap
            skip_res = client_alpha.post("/api/v1/projects/proj_defi_uni/skip", headers=auth_headers)
            assert skip_res.status_code == 200

            # 5. Inferred user profile adapts
            prof_res_adapted = client_alpha.get("/api/v1/user-profile", headers=auth_headers)
            assert prof_res_adapted.status_code == 200
            prof_data_adapted = prof_res_adapted.json()["data"]
            assert prof_data_adapted["engagement_summary"]["total_signals"] >= 3
            assert "L2" in prof_data_adapted["favorite_sectors"]
            assert prof_data_adapted["sector_affinity"].get("L2", 0.0) > 1.0

            # 6. Personalized project listing re-ranks based on user memory
            proj_res_normal = client_alpha.get("/api/v1/projects", headers=auth_headers)
            assert proj_res_normal.status_code == 200
            proj_res_personalized = client_alpha.get("/api/v1/projects?personalized=true", headers=auth_headers)
            assert proj_res_personalized.status_code == 200
            p_items = proj_res_personalized.json()["data"]["projects"]
            assert len(p_items) >= 2
            # Scroll L2 should be boosted to the top for this user
            assert p_items[0]["id"] == "proj_l2_scroll"

            # 7. GDPR profile reset (DELETE /api/v1/user-profile)
            del_prof_res = client_alpha.delete("/api/v1/user-profile", headers=auth_headers)
            assert del_prof_res.status_code == 200
            prof_res_reset = client_alpha.get("/api/v1/user-profile", headers=auth_headers)
            assert prof_res_reset.status_code == 200
            assert prof_res_reset.json()["data"]["is_cleared"] is True

            # ══════════════════════════════════════════════════════════════
            # Stage 5: Anomaly Detection Engine & Quality Scans (W12-04)
            # ══════════════════════════════════════════════════════════════
            # 1. Baseline anomaly scan: with 3 projects, should have valid summary
            anom_res_baseline = client_alpha.get("/api/v1/anomalies", headers=auth_headers)
            assert anom_res_baseline.status_code == 200
            anom_baseline = anom_res_baseline.json()["data"]
            assert anom_baseline["overall_status"] in ("healthy", "warning")
            assert "drift_summary" in anom_baseline
            assert "quality_summary" in anom_baseline

            # 2. Inject critical anomalies into the DB:
            # - Surge of 10 zero-score projects (causes zero_score_surge anomaly)
            # - Stale collection log (5 days ago)
            with get_connection() as conn:
                for i in range(10):
                    conn.execute(
                        f"""
                        INSERT INTO projects (id, name, sector, stage, score, label, confidence, url)
                        VALUES ('zero_proj_{i}', 'Zero Project {i}', 'DeFi', 'mainnet', 0, 'IGNORE', 0.9, 'https://zero.io')
                        """
                    )
                conn.execute(
                    """
                    INSERT INTO collection_logs (log_id, source_id, started_at, status)
                    VALUES ('log_stale_1', 'defillama', '2026-09-10 10:00:00', 'failed')
                    """
                )
                conn.commit()

            # 3. Trigger anomaly scan and verify detection (force_refresh=true to bypass cache)
            anom_res_degraded = client_alpha.get("/api/v1/anomalies?force_refresh=true", headers=auth_headers)
            assert anom_res_degraded.status_code == 200
            anom_degraded = anom_res_degraded.json()["data"]
            assert anom_degraded["total_anomalies"] > 0
            anomaly_types = [a["type"] for a in anom_degraded["anomalies"]]
            assert "score_drift" in anomaly_types
            anomaly_ids = [a["id"] for a in anom_degraded["anomalies"]]
            assert "score_zero_spike" in anomaly_ids

            # ══════════════════════════════════════════════════════════════
            # Stage 6: HA Failover Under Load (W12-03)
            # ══════════════════════════════════════════════════════════════
            # Alpha steps down
            elector_alpha = app_alpha.state.leader_elector
            elector_beta = app_beta.state.leader_elector
            elector_alpha.step_down()
            assert elector_alpha.is_leader is False

            # Beta heartbeats and acquires lease immediately
            assert elector_beta.acquire_or_renew() is True
            assert elector_beta.is_leader is True

            # Verify Beta's REST API reports Leader status
            res_beta_promoted = client_beta.get("/api/v1/ha/status")
            assert res_beta_promoted.status_code == 200
            data_beta_promoted = res_beta_promoted.json()["data"]
            assert data_beta_promoted["is_leader"] is True
            assert data_beta_promoted["current_leader"] == "inst_beta"
            assert data_beta_promoted["status"] == "leader"

            # All V3 features continue to serve under the new leader
            res_mw = client_beta.get("/api/v1/projects/proj_l2_scroll/multi-wallet-strategy", headers=auth_headers)
            assert res_mw.status_code == 200
            res_tm = client_beta.get("/api/v1/projects/proj_l2_scroll/timeline", headers=auth_headers)
            assert res_tm.status_code == 200
            res_an = client_beta.get("/api/v1/anomalies", headers=auth_headers)
            assert res_an.status_code == 200



class TestV3CoreEdgeCases:
    """Edge cases, graceful fallbacks, and boundary conditions for V3."""

    def test_cold_start_and_missing_resources(self):
        """Verify graceful fallbacks on an empty database."""
        app = create_app()
        headers = {"X-API-Key": "test-admin-secret-api-key"}
        with TestClient(app) as client:
            # 1. Nonexistent project multi-wallet strategy -> 404
            res_mw = client.get("/api/v1/projects/nonexistent-proj/multi-wallet-strategy", headers=headers)
            assert res_mw.status_code == 404

            # 2. Nonexistent project timeline -> 404
            res_tm = client.get("/api/v1/projects/nonexistent-proj/timeline", headers=headers)
            assert res_tm.status_code == 404

            # 3. Anomaly scan on empty database -> healthy, 0 anomalies
            res_an = client.get("/api/v1/anomalies", headers=headers)
            assert res_an.status_code == 200
            assert res_an.json()["data"]["total_anomalies"] == 0

    def test_standalone_mode_ha_compatibility(self, monkeypatch):
        """Verify ha_enabled=False operates in standalone mode without errors."""
        monkeypatch.setattr(settings, "ha_enabled", False)
        app = create_app()
        with TestClient(app) as client:
            res = client.get("/api/v1/ha/status")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["ha_enabled"] is False
            assert data["is_leader"] is True
            assert data["status"] == "standalone"
