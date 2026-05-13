"""Eval runner — orchestrates loading, agent invocation, and scoring."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from zil.sdk.eval.adapters import get_adapter
from zil.sdk.eval.loader import load_eval_engine_config, load_eval_suite
from zil.sdk.eval.models import (
    CaseResult,
    CaseVerdict,
    EvalCase,
    EvalEngineConfig,
    GroupResult,
    SuiteResult,
)

logger = logging.getLogger(__name__)


def run_eval_suite(
    project_dir: Path | str,
    *,
    suite_name: str = "baseline",
    agent_fn: Callable[[str], str] | None = None,
    threshold_override: float | None = None,
) -> SuiteResult:
    """Run an eval suite against an agent and return scored results.

    Args:
        project_dir: Path to the Zil project root.
        suite_name: Name of the suite file (without .yaml extension).
        agent_fn: A callable that takes a user input string and returns
            the agent's response. If None, uses a default ADK runner.
        threshold_override: Override the suite's pass_threshold.

    Returns:
        A SuiteResult with scores, verdicts, and pass/fail status.
    """
    root = Path(project_dir).resolve()

    # Load configuration
    engine_config = load_eval_engine_config(root)
    suite_config = load_eval_suite(root, suite_name)

    threshold = threshold_override or suite_config.pass_threshold

    # Get the adapter for the configured framework
    adapter = get_adapter(engine_config.framework)
    adapter.configure(engine_config)

    # Resolve agent function
    invoke = agent_fn or _build_default_agent_fn(root)

    concurrency = engine_config.execution.concurrency
    retries = engine_config.execution.retries
    timeout = engine_config.execution.timeout

    # Run each group
    group_results: list[GroupResult] = []
    for group in suite_config.groups:
        if concurrency > 1:
            case_results = _run_group_parallel(
                group.cases, suite_config.metrics, invoke, adapter,
                engine_config, concurrency, retries, timeout,
            )
        else:
            case_results = _run_group_sequential(
                group.cases, suite_config.metrics, invoke, adapter,
                retries, timeout,
            )

        # Calculate group pass rate
        if case_results:
            passed = sum(1 for r in case_results if r.verdict == CaseVerdict.PASS)
            pass_rate = passed / len(case_results)
        else:
            pass_rate = 0.0

        group_results.append(
            GroupResult(
                name=group.name,
                weight=group.weight,
                pass_rate=pass_rate,
                case_results=case_results,
            )
        )

    # Calculate overall weighted score
    total_weight = sum(g.weight for g in group_results)
    if total_weight > 0:
        score = sum(g.pass_rate * g.weight for g in group_results) / total_weight
    else:
        score = 0.0

    return SuiteResult(
        suite_name=suite_config.name,
        score=score,
        passed=score >= threshold,
        threshold=threshold,
        group_results=group_results,
    )


def _eval_single_case(
    case: EvalCase,
    metrics: list[str],
    invoke: Callable[[str], str],
    adapter: object,
    retries: int,
    timeout: int,
) -> CaseResult:
    """Invoke agent + evaluate a single case with retry and timeout."""
    effective_metrics = case.metrics or metrics
    last_error: str = ""

    for attempt in range(1 + retries):
        start = time.monotonic()
        try:
            actual_output = invoke(case.input)
        except Exception as e:
            last_error = str(e)
            logger.debug("Case %r attempt %d invoke error: %s", case.input[:40], attempt, e)
            continue

        elapsed = time.monotonic() - start
        if elapsed > timeout:
            last_error = f"Timeout: agent took {elapsed:.1f}s (limit: {timeout}s)"
            logger.debug("Case %r timed out after %.1fs", case.input[:40], elapsed)
            continue

        try:
            return adapter.evaluate_case(case, actual_output, effective_metrics)  # type: ignore[union-attr]
        except Exception as e:
            last_error = str(e)
            logger.debug("Case %r attempt %d eval error: %s", case.input[:40], attempt, e)
            continue

    return CaseResult(
        case=case,
        verdict=CaseVerdict.ERROR,
        actual_output="",
        score=0.0,
        error=last_error,
    )


def _run_group_sequential(
    cases: list[EvalCase],
    suite_metrics: list[str],
    invoke: Callable[[str], str],
    adapter: object,
    retries: int,
    timeout: int,
) -> list[CaseResult]:
    """Run cases sequentially."""
    return [
        _eval_single_case(case, suite_metrics, invoke, adapter, retries, timeout)
        for case in cases
    ]


def _run_group_parallel(
    cases: list[EvalCase],
    suite_metrics: list[str],
    invoke: Callable[[str], str],
    adapter: object,
    engine_config: EvalEngineConfig,
    concurrency: int,
    retries: int,
    timeout: int,
) -> list[CaseResult]:
    """Run cases in parallel using a thread pool."""
    results: dict[int, CaseResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        future_to_idx = {
            pool.submit(
                _eval_single_case, case, suite_metrics, invoke, adapter,
                retries, timeout,
            ): idx
            for idx, case in enumerate(cases)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = CaseResult(
                    case=cases[idx],
                    verdict=CaseVerdict.ERROR,
                    actual_output="",
                    score=0.0,
                    error=str(e),
                )
    # Return in original order
    return [results[i] for i in range(len(cases))]


def _build_default_agent_fn(project_dir: Path) -> Callable[[str], str]:
    """Build a default agent invocation function using the Zil SDK."""
    import asyncio
    import uuid

    try:
        from google.adk.runners import InMemoryRunner
        from google.genai import types
    except ImportError:
        raise ImportError(
            "google-adk is required to run evals against an agent. "
            "Install it with: pip install 'zil-ai[adk]'"
        ) from None

    from zil.sdk.agent import create_agent

    agent = create_agent(project_dir=project_dir, enable_telemetry=False)
    runner = InMemoryRunner(agent=agent, app_name="zil_eval")
    user_id = "eval_user"

    # Use a persistent event loop to avoid repeated creation/teardown
    # which triggers noisy cleanup errors from the Google GenAI client.
    loop = asyncio.new_event_loop()

    # Suppress the GenAI async client cleanup noise
    def _quiet_exception_handler(
        loop: asyncio.AbstractEventLoop, context: dict,
    ) -> None:
        exc = context.get("exception")
        if exc and "async_httpx_client" in str(exc):
            return  # Suppress known GenAI cleanup noise
        loop.default_exception_handler(context)

    loop.set_exception_handler(_quiet_exception_handler)

    def _invoke(user_input: str) -> str:
        session_id = f"eval_{uuid.uuid4().hex[:8]}"

        async def _run() -> str:
            # Create a fresh session for each eval case
            await runner.session_service.create_session(
                app_name="zil_eval",
                user_id=user_id,
                session_id=session_id,
            )
            content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_input)],
            )
            response_parts: list[str] = []
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content,
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            response_parts.append(part.text)
            return "".join(response_parts)

        return loop.run_until_complete(_run())

    return _invoke
