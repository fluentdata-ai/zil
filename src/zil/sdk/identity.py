"""Compose identity files into a single instruction string for the LLM agent."""

from __future__ import annotations

from typing import Any


def compose_instruction(
    persona: str | None,
    instructions: str | None,
    guardrails: dict[str, Any] | None,
) -> str:
    """Build a unified instruction from persona + instructions + guardrails.

    The composed instruction follows this structure:
      1. Persona (who the agent is)
      2. Instructions (how the agent behaves)
      3. Guardrails (hard rules, output constraints)
    """
    sections: list[str] = []

    if persona:
        sections.append(persona.strip())

    if instructions:
        sections.append(instructions.strip())

    if guardrails:
        sections.append(_guardrails_to_instruction(guardrails))

    if not sections:
        return "You are a helpful AI assistant."

    return "\n\n---\n\n".join(sections)


def _guardrails_to_instruction(guardrails: dict[str, Any]) -> str:
    """Convert guardrails YAML into natural-language rules for the LLM."""
    lines: list[str] = ["# Guardrails — Hard Rules"]
    lines.append("")
    lines.append("You MUST follow these rules at all times. They are non-negotiable.")

    # Hard blocks
    hard_blocks = guardrails.get("hard_blocks", [])
    if hard_blocks:
        lines.append("")
        lines.append("## Blocked topics")
        for block in hard_blocks:
            desc = block.get("description", block.get("topic", ""))
            lines.append(f"- {desc}")

    # Escalation triggers
    triggers = guardrails.get("escalation_triggers", [])
    if triggers:
        lines.append("")
        lines.append("## Escalation")
        for trigger in triggers:
            condition = trigger.get("condition", "")
            message = trigger.get("message", "Escalate to a human.")
            lines.append(f"- When **{condition}**: {message}")

    # Output constraints
    constraints = guardrails.get("output_constraints", {})
    if constraints:
        lines.append("")
        lines.append("## Output constraints")
        max_len = constraints.get("max_response_length")
        if max_len:
            lines.append(f"- Maximum response length: {max_len} characters.")
        fmt = constraints.get("format")
        if fmt:
            lines.append(f"- Response format: {fmt}.")
        citation = constraints.get("citation_required")
        if citation is not None:
            lines.append(
                f"- Citations: {'required' if citation else 'not required'}."
            )

    return "\n".join(lines)
