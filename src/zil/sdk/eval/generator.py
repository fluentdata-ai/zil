"""Generate eval cases from agent identity using an LLM."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from zil.sdk.eval.models import EvalCase, EvalEngineConfig

_SYSTEM_PROMPT = """\
You are an evaluation engineer. Given an AI agent's specification, generate \
diverse eval test cases to thoroughly test the agent.

Each test case must be a JSON object with these fields:
- "input": the user message to send to the agent
- "expected_contains": list of keywords/phrases the response SHOULD contain
- "context": list of relevant context strings (optional, can be empty)
- "metrics": list of metrics to apply, choose from: \
answer_relevancy, hallucination, faithfulness, toxicity, bias (or empty for deterministic-only)

Return a JSON array of test case objects. Only output the JSON array, nothing else.

Guidelines:
- Cover happy paths, edge cases, boundary conditions, and potential failure modes.
- Include cases that test the agent's stated guardrails and behavioral rules.
- Vary complexity: simple queries, multi-step reasoning, ambiguous inputs, off-topic requests.
- For each case, expected_contains should list 1-3 keywords that a correct response must include.
- If a category is specified, focus on that area.
"""


def generate_cases(
    project_dir: Path,
    engine_config: EvalEngineConfig,
    *,
    count: int = 10,
    category: str | None = None,
) -> list[EvalCase]:
    """Use the judge LLM to synthesise eval cases from agent identity.

    Args:
        project_dir: Zil project root.
        engine_config: The loaded engine config (provides judge LLM).
        count: Number of cases to generate.
        category: Optional focus area (e.g., "accuracy", "guardrails").

    Returns:
        A list of EvalCase objects parsed from the LLM response.
    """
    identity_text = _load_identity_text(project_dir)
    existing_text = _load_existing_cases_text(project_dir)

    user_prompt = f"Generate {count} eval test cases for this agent.\n\n"
    user_prompt += f"## Agent Specification\n{identity_text}\n\n"
    if existing_text:
        user_prompt += (
            f"## Existing Cases (avoid duplicates)\n{existing_text}\n\n"
        )
    if category:
        user_prompt += f"## Focus Area\nConcentrate on: {category}\n\n"

    raw_response = _call_judge_llm(engine_config, user_prompt)
    return _parse_cases(raw_response)


def _load_identity_text(project_dir: Path) -> str:
    """Read persona, instructions, and guardrails into a single text block."""
    parts: list[str] = []
    identity_dir = project_dir / "identity"

    for filename in ("persona.md", "instructions.md"):
        path = identity_dir / filename
        if path.is_file():
            parts.append(f"### {filename}\n{path.read_text(encoding='utf-8')}")

    guardrails_path = identity_dir / "guardrails.yaml"
    if guardrails_path.is_file():
        parts.append(
            f"### guardrails.yaml\n```yaml\n"
            f"{guardrails_path.read_text(encoding='utf-8')}```"
        )

    return "\n\n".join(parts) if parts else "(no identity files found)"


def _load_existing_cases_text(project_dir: Path) -> str:
    """Read existing case files to provide dedup context."""
    cases_dir = project_dir / "evals" / "cases"
    if not cases_dir.is_dir():
        return ""

    snippets: list[str] = []
    for f in sorted(cases_dir.glob("*.yaml")):
        content = f.read_text(encoding="utf-8")
        # Truncate long files to save tokens
        if len(content) > 2000:
            content = content[:2000] + "\n... (truncated)"
        snippets.append(f"# {f.name}\n{content}")

    return "\n\n".join(snippets)


def _call_judge_llm(config: EvalEngineConfig, user_prompt: str) -> str:
    """Call the configured judge LLM and return the raw text response."""
    provider = config.judge.provider
    model = config.judge.model
    api_key = os.environ.get(config.judge.api_key_env, "")

    if provider in ("gemini", "vertex-ai", "google"):
        return _call_gemini(model, api_key, user_prompt)
    elif provider in ("openai", "gpt"):
        return _call_openai(model, api_key, user_prompt)
    elif provider == "anthropic":
        return _call_anthropic(model, api_key, user_prompt)
    else:
        raise ValueError(f"Unsupported judge provider for generation: {provider}")


def _call_gemini(model: str, api_key: str, prompt: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=f"{_SYSTEM_PROMPT}\n\n{prompt}",
    )
    return response.text or ""


def _call_openai(model: str, api_key: str, prompt: str) -> str:
    import openai

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or ""


def _call_anthropic(model: str, api_key: str, prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _parse_cases(raw: str) -> list[EvalCase]:
    """Parse the LLM JSON array response into EvalCase objects."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON array in the response
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            data = json.loads(text[start : end + 1])
        else:
            raise ValueError(f"Could not parse LLM response as JSON: {text[:200]}")

    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of test cases")

    cases: list[EvalCase] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cases.append(
            EvalCase(
                input=item.get("input", ""),
                expected_output=item.get("expected_output"),
                expected_contains=item.get("expected_contains", []),
                expected_tool=item.get("expected_tool"),
                expected_action=item.get("expected_action"),
                context=item.get("context", []),
                metrics=item.get("metrics", []),
            )
        )
    return cases
