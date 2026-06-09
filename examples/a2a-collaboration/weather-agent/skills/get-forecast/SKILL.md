---
name: get-forecast
description: >
  Return a concise weather forecast for a given location and (optional) date,
  including a one-line piece of practical advice. This is the skill the
  trip-planner agent invokes over A2A.
license: Apache-2.0
---

# get-forecast

## Overview

Produce a short, practical weather forecast for a location. This skill is
advertised on the agent's A2A Agent Card (id: `get-forecast`) so callers can
discover and invoke it.

## Inputs

- **location** (required): city or place name.
- **date** (optional): the day to forecast; defaults to today.

## Steps

1. Identify the location (ask if missing).
2. Produce the headline forecast: condition, temperature, wind.
3. Add one line of practical advice (clothing / umbrella / sun protection).
4. If live data is unavailable, label the forecast as illustrative.

## Output

A short text forecast (under 120 words) suitable for returning as an A2A
artifact to the calling agent.
