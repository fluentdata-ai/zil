"""Tests for the cost tracking module (v0.1.11)."""

from __future__ import annotations

import threading

from zil.sdk.cost import CostStatus, CostTracker, TokenCounts, UsageRecord
from zil.sdk.cost_callback import CostCallback

# ---------------------------------------------------------------------------
# CostTracker — basic recording
# ---------------------------------------------------------------------------


class TestCostTrackerBasic:
    """Basic token recording without budget limits."""

    def test_uninitialized_repr(self):
        tracker = CostTracker()
        assert "not initialized" in repr(tracker)

    def test_initialize_empty_config(self):
        tracker = CostTracker()
        tracker._initialize(None)
        assert tracker.total_tokens == 0
        assert tracker.request_count == 0
        assert tracker.budget_remaining is None

    def test_record_single_usage(self):
        tracker = CostTracker()
        tracker._initialize({})
        result = tracker.record_usage(100, 200, model="gemini-2.0-flash")
        assert result.status == CostStatus.ALLOWED
        assert result.total_tokens == 300
        assert tracker.total_tokens == 300
        assert tracker.total_input_tokens == 100
        assert tracker.total_output_tokens == 200
        assert tracker.request_count == 1

    def test_record_multiple_usage(self):
        tracker = CostTracker()
        tracker._initialize({})
        tracker.record_usage(100, 200, model="gemini-2.0-flash")
        tracker.record_usage(50, 100, model="gemini-2.0-flash")
        assert tracker.total_tokens == 450
        assert tracker.total_input_tokens == 150
        assert tracker.total_output_tokens == 300
        assert tracker.request_count == 2

    def test_by_model_breakdown(self):
        tracker = CostTracker()
        tracker._initialize({"track_by_model": True})
        tracker.record_usage(100, 200, model="gemini-2.0-flash")
        tracker.record_usage(50, 50, model="gpt-4o")
        tracker.record_usage(30, 70, model="gemini-2.0-flash")

        by_model = tracker.by_model
        assert "gemini-2.0-flash" in by_model
        assert "gpt-4o" in by_model
        assert by_model["gemini-2.0-flash"].total_tokens == 400
        assert by_model["gemini-2.0-flash"].request_count == 2
        assert by_model["gpt-4o"].total_tokens == 100
        assert by_model["gpt-4o"].request_count == 1

    def test_track_by_model_disabled(self):
        tracker = CostTracker()
        tracker._initialize({"track_by_model": False})
        tracker.record_usage(100, 200, model="gemini-2.0-flash")
        assert tracker.by_model == {}

    def test_requests_list(self):
        tracker = CostTracker()
        tracker._initialize({})
        tracker.record_usage(10, 20, model="m1")
        tracker.record_usage(30, 40, model="m2")
        requests = tracker.requests
        assert len(requests) == 2
        assert requests[0].input_tokens == 10
        assert requests[1].model == "m2"

    def test_reset(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_session": 10000})
        tracker.record_usage(100, 200, model="m1")
        tracker.reset()
        assert tracker.total_tokens == 0
        assert tracker.request_count == 0
        assert tracker.by_model == {}
        assert tracker.requests == []
        assert tracker.budget_remaining == 10000

    def test_repr_initialized(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_session": 5000})
        tracker.record_usage(100, 200, model="m1")
        r = repr(tracker)
        assert "tokens=300" in r
        assert "budget=5000" in r


# ---------------------------------------------------------------------------
# CostTracker — budget enforcement
# ---------------------------------------------------------------------------


class TestCostTrackerBudget:
    """Budget enforcement tests."""

    def test_per_request_block(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_request": 500})
        result = tracker.record_usage(300, 300, model="m1")
        assert result.status == CostStatus.BLOCKED
        assert "max_tokens_per_request" in result.message
        # Should not have been recorded
        assert tracker.total_tokens == 0

    def test_per_request_allow(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_request": 500})
        result = tracker.record_usage(200, 200, model="m1")
        assert result.status == CostStatus.ALLOWED
        assert tracker.total_tokens == 400

    def test_per_session_block(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_session": 1000})
        tracker.record_usage(400, 400, model="m1")  # 800 used
        result = tracker.record_usage(150, 150, model="m1")  # 300 more would be 1100
        assert result.status == CostStatus.BLOCKED
        assert "max_tokens_per_session" in result.message
        assert tracker.total_tokens == 800  # Not incremented

    def test_per_session_allow_near_limit(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_session": 1000})
        result = tracker.record_usage(200, 200, model="m1")  # 400, under 1000 and under 80%
        assert result.status == CostStatus.ALLOWED
        assert tracker.budget_remaining == 600

    def test_alert_threshold(self):
        tracker = CostTracker()
        tracker._initialize({
            "max_tokens_per_session": 1000,
            "alert_threshold_pct": 80,
        })
        # First request: 500 tokens (50%) — no alert
        result1 = tracker.record_usage(250, 250, model="m1")
        assert result1.status == CostStatus.ALLOWED

        # Second request: 350 tokens (total 850, 85%) — alert fires
        result2 = tracker.record_usage(175, 175, model="m1")
        assert result2.status == CostStatus.WARNED
        assert "alert" in result2.message.lower()

        # Third request: alert already fired, should be ALLOWED (no double-fire)
        result3 = tracker.record_usage(50, 50, model="m1")
        assert result3.status == CostStatus.ALLOWED

    def test_budget_remaining(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_session": 5000})
        tracker.record_usage(1000, 1000, model="m1")
        assert tracker.budget_remaining == 3000

    def test_no_budget_remaining_is_none(self):
        tracker = CostTracker()
        tracker._initialize({})
        tracker.record_usage(1000, 1000, model="m1")
        assert tracker.budget_remaining is None


# ---------------------------------------------------------------------------
# CostTracker — thread safety
# ---------------------------------------------------------------------------


class TestCostTrackerThreadSafety:
    """Verify thread-safe accumulation."""

    def test_concurrent_recording(self):
        tracker = CostTracker()
        tracker._initialize({})

        def worker():
            for _ in range(100):
                tracker.record_usage(10, 10, model="m1")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracker.total_tokens == 20000  # 10 threads × 100 calls × 20 tokens
        assert tracker.request_count == 1000


# ---------------------------------------------------------------------------
# CostCallback
# ---------------------------------------------------------------------------


class TestCostCallback:
    """CostCallback wraps CostTracker with model context."""

    def test_record_basic(self):
        tracker = CostTracker()
        tracker._initialize({})
        cb = CostCallback(tracker, model="gemini-2.0-flash")
        result = cb.record(100, 200)
        assert result.status == CostStatus.ALLOWED
        assert tracker.total_tokens == 300
        assert tracker.by_model["gemini-2.0-flash"].total_tokens == 300

    def test_record_model_override(self):
        tracker = CostTracker()
        tracker._initialize({})
        cb = CostCallback(tracker, model="default-model")
        cb.record(50, 50, model="override-model")
        assert "override-model" in tracker.by_model
        assert "default-model" not in tracker.by_model

    def test_record_from_response_gemini(self):
        """Simulate Gemini-style response with usage_metadata."""
        tracker = CostTracker()
        tracker._initialize({})
        cb = CostCallback(tracker, model="gemini-2.0-flash")

        class FakeUsageMeta:
            prompt_token_count = 150
            candidates_token_count = 350

        class FakeResponse:
            usage_metadata = FakeUsageMeta()

        result = cb.record_from_response(FakeResponse())
        assert result is not None
        assert result.status == CostStatus.ALLOWED
        assert tracker.total_tokens == 500

    def test_record_from_response_openai(self):
        """Simulate OpenAI-style response with usage."""
        tracker = CostTracker()
        tracker._initialize({})
        cb = CostCallback(tracker, model="gpt-4o")

        class FakeUsage:
            prompt_tokens = 200
            completion_tokens = 400

        class FakeResponse:
            usage_metadata = None
            usage = FakeUsage()

        result = cb.record_from_response(FakeResponse())
        assert result is not None
        assert tracker.total_tokens == 600

    def test_record_from_response_no_usage(self):
        """Response without usage data returns None."""
        tracker = CostTracker()
        tracker._initialize({})
        cb = CostCallback(tracker, model="m1")

        class FakeResponse:
            pass

        result = cb.record_from_response(FakeResponse())
        assert result is None
        assert tracker.total_tokens == 0

    def test_blocked_request(self):
        tracker = CostTracker()
        tracker._initialize({"max_tokens_per_request": 100})
        cb = CostCallback(tracker, model="m1")
        result = cb.record(80, 80)  # 160 > 100
        assert result.status == CostStatus.BLOCKED
        assert tracker.total_tokens == 0


# ---------------------------------------------------------------------------
# TokenCounts dataclass
# ---------------------------------------------------------------------------


class TestTokenCounts:
    """TokenCounts accumulation."""

    def test_add(self):
        tc = TokenCounts()
        record = UsageRecord(input_tokens=10, output_tokens=20, total_tokens=30, model="m1")
        tc.add(record)
        assert tc.input_tokens == 10
        assert tc.output_tokens == 20
        assert tc.total_tokens == 30
        assert tc.request_count == 1


# ---------------------------------------------------------------------------
# Validate — _check_cost
# ---------------------------------------------------------------------------


class TestValidateCost:
    """Tests for the _check_cost validation function."""

    def test_no_cost_config_warns(self, tmp_path):
        """Missing spec.cost produces a warning."""
        from zil.schema.loader import ValidationResult, _check_cost

        manifest = {"spec": {"runtime": {}}}
        result = ValidationResult()
        _check_cost(manifest, result)
        assert any("not configured" in c.message for c in result.checks)
        assert result.checks[-1].status == "warn"

    def test_cost_config_present(self, tmp_path):
        """Configured spec.cost produces a pass."""
        from zil.schema.loader import ValidationResult, _check_cost

        manifest = {"spec": {"runtime": {}, "cost": {
            "max_tokens_per_request": 4096,
            "max_tokens_per_session": 100000,
            "alert_threshold_pct": 90,
        }}}
        result = ValidationResult()
        _check_cost(manifest, result)
        assert any("configured" in c.message and c.status == "pass" for c in result.checks)

    def test_cost_exceeds_resource_limits(self):
        """Warn when cost budget > resource_limits.max_tokens_per_request."""
        from zil.schema.loader import ValidationResult, _check_cost

        manifest = {"spec": {
            "runtime": {"resource_limits": {"max_tokens_per_request": 4096}},
            "cost": {"max_tokens_per_request": 8192},
        }}
        result = ValidationResult()
        _check_cost(manifest, result)
        assert any("exceeds" in c.message and c.status == "warn" for c in result.checks)

    def test_session_less_than_request(self):
        """Warn when session limit < per-request limit."""
        from zil.schema.loader import ValidationResult, _check_cost

        manifest = {"spec": {
            "runtime": {},
            "cost": {"max_tokens_per_request": 8192, "max_tokens_per_session": 4096},
        }}
        result = ValidationResult()
        _check_cost(manifest, result)
        assert any("less than" in c.message and c.status == "warn" for c in result.checks)


# ---------------------------------------------------------------------------
# Schema validation — spec.cost accepted
# ---------------------------------------------------------------------------


class TestSchemaCost:
    """Manifest schema accepts spec.cost field."""

    def test_manifest_with_cost_validates(self, tmp_path):
        """A valid manifest with spec.cost passes schema validation."""
        import yaml

        from zil.schema.loader import validate_project

        manifest = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "cost-test-agent", "version": "0.1.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    "llm": {"adapter": "./adapters/llm.yaml"},
                },
                "identity": "./identity",
                "cost": {
                    "max_tokens_per_request": 8192,
                    "max_tokens_per_session": 500000,
                    "alert_threshold_pct": 80,
                    "track_by_model": True,
                },
            },
        }

        # Write manifest
        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))

        # Create minimal required files
        (tmp_path / "identity").mkdir()
        (tmp_path / "identity" / "persona.md").write_text("Persona")
        (tmp_path / "identity" / "instructions.md").write_text("Instructions")
        (tmp_path / "identity" / "guardrails.yaml").write_text(
            "detection:\n  prompt_injection: true\n  pii_output: true\n"
        )
        (tmp_path / "adapters").mkdir()
        (tmp_path / "adapters" / "llm.yaml").write_text(
            "provider: gemini\nmodel: gemini-2.0-flash\n"
        )

        result = validate_project(tmp_path)
        # Schema must pass (no fail on spec.cost)
        schema_checks = [c for c in result.checks if "schema" in c.message]
        assert all(c.status == "pass" for c in schema_checks)

    def test_manifest_with_invalid_cost_fails(self, tmp_path):
        """Invalid spec.cost (negative value) fails schema validation."""
        import yaml

        from zil.schema.loader import validate_project

        manifest = {
            "apiVersion": "zil/v1",
            "kind": "Agent",
            "metadata": {"name": "cost-test-agent", "version": "0.1.0"},
            "spec": {
                "runtime": {
                    "framework": "adk",
                    "language": "python",
                    "llm": {"adapter": "./adapters/llm.yaml"},
                },
                "identity": "./identity",
                "cost": {
                    "max_tokens_per_request": -1,  # Invalid
                },
            },
        }

        (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
        result = validate_project(tmp_path)
        assert result.exit_code == 1  # Schema validation should fail
