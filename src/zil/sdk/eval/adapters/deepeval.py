"""DeepEval adapter — translates Zil eval cases into DeepEval test cases."""

from __future__ import annotations

import os
from typing import Any

from zil.sdk.eval.models import (
    CaseResult,
    CaseVerdict,
    EvalCase,
    EvalEngineConfig,
)

# Metric name → DeepEval metric class mapping
_METRIC_REGISTRY: dict[str, str] = {
    "hallucination": "HallucinationMetric",
    "faithfulness": "FaithfulnessMetric",
    "answer_relevancy": "AnswerRelevancyMetric",
    "contextual_relevancy": "ContextualRelevancyMetric",
    "toxicity": "ToxicityMetric",
    "bias": "BiasMetric",
    "summarization": "SummarizationMetric",
}


class DeepEvalAdapter:
    """Adapter that delegates evaluation to the DeepEval framework."""

    def __init__(self) -> None:
        self._judge_model: Any = None
        self._configured = False

    def configure(self, config: EvalEngineConfig) -> None:
        """Configure DeepEval with the judge LLM from Zil's eval config."""
        # Ensure the API key env var is available for DeepEval
        api_key_env = config.judge.api_key_env
        if api_key_env and not os.environ.get(api_key_env):
            self._missing_key_env = api_key_env
        else:
            self._missing_key_env = None

        # Defer judge model creation until metrics are actually needed
        self._config = config
        self._judge_model = None
        self._metric_thresholds = config.metric_thresholds
        self._configured = True

    def evaluate_case(
        self,
        case: EvalCase,
        actual_output: str,
        metrics: list[str],
    ) -> CaseResult:
        """Evaluate a single case using DeepEval metrics."""
        if not self._configured:
            raise RuntimeError("Adapter not configured. Call configure() first.")

        # Run deterministic checks first
        deterministic_pass = _check_deterministic(case, actual_output)

        # Run LLM-as-judge metrics (only if metrics are requested)
        metric_scores: dict[str, float] = {}
        llm_metrics_pass = True

        if metrics:
            if self._missing_key_env:
                raise RuntimeError(
                    f"LLM-as-judge metrics require {self._missing_key_env} to be set. "
                    f"Add it to your .env file or export it in your shell."
                )

            try:
                from deepeval.test_case import LLMTestCase
            except ImportError:
                raise ImportError(
                    "deepeval is required for LLM-as-judge evaluation. "
                    "Install it with: pip install 'zil-ai[eval]'"
                ) from None

            test_case = LLMTestCase(
                input=case.input,
                actual_output=actual_output,
                expected_output=case.expected_output or "",
                context=case.context if case.context else None,
                retrieval_context=case.context if case.context else None,
            )

            # Lazily resolve judge model on first use
            if self._judge_model is None:
                self._judge_model = _resolve_judge_model(self._config)

            metric_instances = _build_metrics(
                metrics, self._judge_model, self._metric_thresholds,
            )
            for metric in metric_instances:
                try:
                    metric.measure(test_case)
                    score = metric.score
                    metric_scores[metric.__class__.__name__] = score
                    if score < metric.threshold:
                        llm_metrics_pass = False
                except Exception:
                    metric_scores[metric.__class__.__name__] = 0.0
                    llm_metrics_pass = False

        # Combine verdicts
        overall_pass = deterministic_pass and llm_metrics_pass
        avg_score = (
            sum(metric_scores.values()) / len(metric_scores)
            if metric_scores
            else (1.0 if deterministic_pass else 0.0)
        )

        return CaseResult(
            case=case,
            verdict=CaseVerdict.PASS if overall_pass else CaseVerdict.FAIL,
            actual_output=actual_output,
            score=avg_score,
            metric_scores=metric_scores,
        )

    def available_metrics(self) -> list[str]:
        """Return the list of supported DeepEval metric names."""
        return list(_METRIC_REGISTRY.keys())


def _check_deterministic(case: EvalCase, actual_output: str) -> bool:
    """Run deterministic assertions (expected_contains, expected_tool, etc.)."""
    output_lower = actual_output.lower()

    # Check expected_contains
    if case.expected_contains:
        for expected in case.expected_contains:
            if expected.lower() not in output_lower:
                return False

    # expected_tool and expected_action are checked if present
    # These require structured output parsing — for now, check string presence
    if case.expected_tool:
        if case.expected_tool.lower() not in output_lower:
            return False

    if case.expected_action:
        if case.expected_action.lower() not in output_lower:
            return False

    return True


def _resolve_judge_model(config: EvalEngineConfig) -> Any:
    """Resolve the judge LLM model for DeepEval.

    DeepEval only accepts OpenAI model strings natively. For other providers
    (Gemini, Anthropic, etc.) we build a DeepEvalBaseLLM wrapper.
    """
    provider = config.judge.provider
    model = config.judge.model

    # OpenAI models are natively supported by DeepEval
    if provider in ("openai", "gpt"):
        return model

    # All other providers need a custom model wrapper
    if provider in ("gemini", "vertex-ai", "google"):
        return _build_gemini_judge(model, config.judge.api_key_env)
    elif provider == "anthropic":
        return _build_anthropic_judge(model, config.judge.api_key_env)
    else:
        return model


def _build_gemini_judge(model_name: str, api_key_env: str) -> Any:
    """Build a DeepEval-compatible Gemini judge model."""
    try:
        from deepeval.models import DeepEvalBaseLLM
    except ImportError:
        raise ImportError(
            "deepeval is required for LLM-as-judge evaluation. "
            "Install it with: pip install 'zil-ai[eval]'"
        ) from None

    class GeminiJudge(DeepEvalBaseLLM):
        """Wraps Google Gemini for DeepEval metrics."""

        def __init__(self) -> None:
            self._model_name = model_name
            self._client: Any = None

        def load_model(self) -> Any:
            if self._client is None:
                from google import genai

                api_key = os.environ.get(api_key_env, "")
                self._client = genai.Client(api_key=api_key)
            return self._client

        def generate(self, prompt: str) -> str:
            client = self.load_model()
            response = client.models.generate_content(
                model=self._model_name,
                contents=prompt,
            )
            return response.text or ""

        async def a_generate(self, prompt: str) -> str:
            return self.generate(prompt)

        def get_model_name(self) -> str:
            return self._model_name

    return GeminiJudge()


def _build_anthropic_judge(model_name: str, api_key_env: str) -> Any:
    """Build a DeepEval-compatible Anthropic judge model."""
    try:
        from deepeval.models import DeepEvalBaseLLM
    except ImportError:
        raise ImportError(
            "deepeval is required for LLM-as-judge evaluation. "
            "Install it with: pip install 'zil-ai[eval]'"
        ) from None

    class AnthropicJudge(DeepEvalBaseLLM):
        """Wraps Anthropic Claude for DeepEval metrics."""

        def __init__(self) -> None:
            self._model_name = model_name
            self._client: Any = None

        def load_model(self) -> Any:
            if self._client is None:
                import anthropic

                self._client = anthropic.Anthropic(
                    api_key=os.environ.get(api_key_env, ""),
                )
            return self._client

        def generate(self, prompt: str, **kwargs: Any) -> str:
            client = self.load_model()
            response = client.messages.create(
                model=self._model_name,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        async def a_generate(self, prompt: str, **kwargs: Any) -> str:
            return self.generate(prompt)

        def get_model_name(self) -> str:
            return self._model_name

    return AnthropicJudge()


def _build_metrics(
    metric_names: list[str],
    judge_model: Any,
    thresholds: dict[str, float] | None = None,
) -> list[Any]:
    """Instantiate DeepEval metric objects from metric names."""
    import deepeval.metrics as dm

    thresholds = thresholds or {}
    instances = []
    for name in metric_names:
        class_name = _METRIC_REGISTRY.get(name)
        if not class_name:
            continue

        metric_class = getattr(dm, class_name, None)
        if metric_class is None:
            continue

        kwargs: dict[str, Any] = {"model": judge_model}
        if name in thresholds:
            kwargs["threshold"] = thresholds[name]

        try:
            instance = metric_class(**kwargs)
            instances.append(instance)
        except TypeError:
            # Some metrics don't accept model kwarg
            instance = metric_class()
            instances.append(instance)

    return instances
