#!/usr/bin/env python3
"""Generate a privacy-preserving AI usage card from local CLI session logs."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


# Fixed historical estimate requested by the profile owner. Local session logs
# begin on 2026-08-11; earlier usage is estimated once from the observed
# 38-day average and never recalculated from future activity.
HISTORY_START = date(2025, 1, 1)
LOCAL_LOG_START = date(2026, 8, 11)
HISTORICAL_DAILY_TOKENS = 95_594_453


def number(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def read_jsonl(path: Path):
    try:
        with path.open(encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                try:
                    yield json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        return


def collect_claude(root: Path, active_days: set[str]) -> dict[str, int]:
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    if not root.is_dir():
        return totals

    for path in root.rglob("*.jsonl"):
        for entry in read_jsonl(path):
            message = entry.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue

            values = {
                "input": number(usage.get("input_tokens")),
                "output": number(usage.get("output_tokens")),
                "cache_read": number(usage.get("cache_read_input_tokens")),
                "cache_write": number(usage.get("cache_creation_input_tokens")),
            }
            if not any(values.values()):
                continue

            for key, value in values.items():
                totals[key] += value
            timestamp = entry.get("timestamp")
            if timestamp:
                active_days.add(str(timestamp)[:10])

    return totals


def collect_codex(root: Path, active_days: set[str]) -> dict[str, int]:
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    if not root.is_dir():
        return totals

    for path in root.rglob("*.jsonl"):
        highest: dict[str, object] | None = None
        days_for_session: set[str] = set()

        for entry in read_jsonl(path):
            payload = entry.get("payload")
            info = payload.get("info") if isinstance(payload, dict) else None
            usage = info.get("total_token_usage") if isinstance(info, dict) else None
            if not isinstance(usage, dict):
                continue

            if highest is None or number(usage.get("total_tokens")) > number(highest.get("total_tokens")):
                highest = usage
            timestamp = entry.get("timestamp")
            if timestamp:
                days_for_session.add(str(timestamp)[:10])

        if highest is None:
            continue

        totals["input"] += number(highest.get("input_tokens"))
        totals["output"] += number(highest.get("output_tokens"))
        totals["cache_read"] += number(highest.get("cached_input_tokens"))
        totals["cache_write"] += number(highest.get("cache_write_input_tokens"))
        active_days.update(days_for_session)

    return totals


def compact(value: int) -> str:
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= divisor:
            return f"{value / divisor:.2f}".rstrip("0").rstrip(".") + suffix
    return str(value)


def render(total: int, tracked_days: int, cache_reuse: float, updated: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 150" role="img" aria-labelledby="title desc">
  <title id="title">AI-assisted engineering activity</title>
  <desc id="desc">Local aggregate plus a fixed historical estimate, showing tokens processed, days tracked and cache reuse. No prompts or source paths are published.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0A0D12"/>
      <stop offset="1" stop-color="#0F1520"/>
    </linearGradient>
    <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">
      <circle cx="1" cy="1" r="1" fill="#E6EDF3" fill-opacity=".045"/>
    </pattern>
  </defs>
  <rect width="1200" height="150" rx="16" fill="url(#bg)"/>
  <rect width="1200" height="150" rx="16" fill="url(#dots)"/>
  <rect x=".5" y=".5" width="1199" height="149" rx="15.5" fill="none" stroke="#E6EDF3" stroke-opacity=".08"/>

  <g font-family="ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace">
    <text x="42" y="42" fill="#7DD3FC" font-size="12" letter-spacing="2">AI-ASSISTED ENGINEERING</text>
    <text x="42" y="67" fill="#5F6977" font-size="11">SINCE 2025-01-01 · LOCAL LOGS + FIXED HISTORY</text>
    <text x="42" y="91" fill="#7D8590" font-size="9.5" letter-spacing=".7">CLAUDE CODE · CODEX · KIRO · ANTIGRAVITY</text>
  </g>

  <g font-family="-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',sans-serif">
    <text x="460" y="64" text-anchor="middle" fill="#F0F3F6" font-size="28" font-weight="600">{compact(total)}</text>
    <text x="460" y="88" text-anchor="middle" fill="#6E7681" font-size="11" letter-spacing="1.4">TOKENS PROCESSED</text>
    <text x="715" y="64" text-anchor="middle" fill="#F0F3F6" font-size="28" font-weight="600">{tracked_days}</text>
    <text x="715" y="88" text-anchor="middle" fill="#6E7681" font-size="11" letter-spacing="1.4">DAYS TRACKED</text>
    <text x="970" y="64" text-anchor="middle" fill="#F0F3F6" font-size="28" font-weight="600">{cache_reuse:.1f}%</text>
    <text x="970" y="88" text-anchor="middle" fill="#6E7681" font-size="11" letter-spacing="1.4">CACHE REUSED</text>
  </g>

  <path d="M350 34V104M587 34V104M842 34V104" stroke="#E6EDF3" stroke-opacity=".08"/>
  <text x="1158" y="128" text-anchor="end" fill="#3D4654" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="10">aggregate metadata only · no prompts or source paths · updated {updated}</text>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "assets" / "ai-usage.svg")
    parser.add_argument("--claude-root", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex" / "sessions")
    args = parser.parse_args()

    active_days: set[str] = set()
    claude = collect_claude(args.claude_root, active_days)
    codex = collect_codex(args.codex_root, active_days)

    claude_total = sum(claude.values())
    codex_total = codex["input"] + codex["output"]
    historical_days = (LOCAL_LOG_START - HISTORY_START).days
    historical_tokens = historical_days * HISTORICAL_DAILY_TOKENS
    total = historical_tokens + claude_total + codex_total
    display_days = (date.today() - HISTORY_START).days + 1
    comparable_input = claude["input"] + claude["cache_read"] + claude["cache_write"] + codex["input"]
    cache_reused = claude["cache_read"] + codex["cache_read"]
    cache_reuse = 100 * cache_reused / comparable_input if comparable_input else 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(total, display_days, cache_reuse, date.today().isoformat()), encoding="utf-8")
    print(
        f"Generated {args.output}: {compact(total)} tokens, {display_days} days since {HISTORY_START}, "
        f"{cache_reuse:.1f}% cache reused ({compact(historical_tokens)} fixed historical baseline)"
    )


if __name__ == "__main__":
    main()
