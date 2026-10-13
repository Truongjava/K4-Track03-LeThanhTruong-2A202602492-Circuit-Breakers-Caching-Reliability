"""Part E — Multi-window, multi-burn-rate alerting (Google SRE Workbook, ch. 5).

Input: per-minute ``total`` and ``bad`` request counts for a 30-day window.

burn_rate(window) = error_ratio(window) / (1 - SLO)

A rule fires at minute i when BOTH its long and its short window (ending at i,
inclusive) burn at least ``burn_rate``. The long window says "this is
significant"; the short window says "it is still happening" (so the alert
resets quickly after recovery).

Tests: tests/test_alerting.py, then `make slo`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRule:
    name: str
    severity: str  # "page" or "ticket"
    long_min: int
    short_min: int
    burn_rate: float


# SRE Workbook defaults for a 30-day SLO window
DEFAULT_RULES: tuple[AlertRule, ...] = (
    AlertRule("fast_burn_2pct_1h", "page", 60, 5, 14.4),
    AlertRule("slow_burn_5pct_6h", "page", 360, 30, 6.0),
    AlertRule("budget_leak_10pct_3d", "ticket", 4320, 360, 1.0),
)


@dataclass(frozen=True)
class AlertEvent:
    rule: str
    severity: str
    start_min: int  # first minute the rule fired
    end_min: int  # first minute it stopped firing (exclusive)


class WindowSums:
    """O(1) sum of any window, via prefix sums. Build once, query many times.

    43,200 minutes x 6 windows: recomputing every window with sum() is far too slow.
    """

    def __init__(self, values: list[int]) -> None:
        """Build the prefix-sum list (prefix[0] = 0)."""
        prefix = [0] * (len(values) + 1)
        acc = 0
        for i, v in enumerate(values):
            acc += v
            prefix[i + 1] = acc
        self.prefix = prefix

    def sum(self, end_inclusive: int, length: int) -> int:
        """Sum of values[end_inclusive - length + 1 .. end_inclusive],
        clipped at index 0 when the window starts before the data."""
        if end_inclusive < 0 or length <= 0:
            return 0
        hi = min(end_inclusive + 1, len(self.prefix) - 1)
        lo = max(0, end_inclusive - length + 1)
        return self.prefix[hi] - self.prefix[lo]


class BurnRateAlerter:
    def __init__(self, slo: float = 0.995, rules: tuple[AlertRule, ...] = DEFAULT_RULES) -> None:
        if not 0 < slo < 1:
            raise ValueError("slo must be in (0, 1)")
        self.slo = slo
        self.rules = rules

    def burn_rate(self, total: WindowSums, bad: WindowSums, end: int, length: int) -> float:
        """(bad / total over the window) / (1 - slo); 0.0 if total is 0."""
        total_sum = total.sum(end, length)
        if total_sum <= 0:
            return 0.0
        return (bad.sum(end, length) / total_sum) / (1.0 - self.slo)

    def evaluate(self, total: list[int], bad: list[int]) -> list[AlertEvent]:
        """One AlertEvent per contiguous firing episode of each rule.

        For each rule, the rule fires at minute i when
        burn(long) >= rule.burn_rate AND burn(short) >= rule.burn_rate.
        An episode starts at the first firing minute and ends (exclusive) at the
        first minute it stops firing (or len(total)). Sorted by start_min.
        """
        totals = WindowSums(total)
        bads = WindowSums(bad)
        events: list[AlertEvent] = []
        for rule in self.rules:
            start: int | None = None
            for i in range(len(total)):
                firing = (self.burn_rate(totals, bads, i, rule.long_min) >= rule.burn_rate
                          and self.burn_rate(totals, bads, i, rule.short_min) >= rule.burn_rate)
                if firing and start is None:
                    start = i
                elif not firing and start is not None:
                    events.append(AlertEvent(rule.name, rule.severity, start, i))
                    start = None
            if start is not None:
                events.append(AlertEvent(rule.name, rule.severity, start, len(total)))
        return sorted(events, key=lambda e: e.start_min)


def error_budget_report(total: list[int], bad: list[int], slo: float = 0.995) -> dict[str, float | bool]:
    """How much of the 30-day error budget is spent?"""
    requests = sum(total)
    bad_sum = sum(bad)
    allowed_bad = (1.0 - slo) * requests
    availability = 1.0 - bad_sum / requests if requests else 1.0
    budget_consumed = bad_sum / allowed_bad if allowed_bad else 0.0
    budget_remaining = 1.0 - budget_consumed
    return {
        "requests": requests,
        "allowed_bad": round(allowed_bad, 1),
        "bad": bad_sum,
        "availability": round(availability, 6),
        "budget_consumed": round(budget_consumed, 4),
        "budget_remaining": round(budget_remaining, 4),
        "freeze_releases": budget_remaining <= 0,
    }
