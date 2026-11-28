"""The KILL decision, as pure functions so every rule is unit-tested.

Each check looks at one time window and gives, per variant, how many requests were served and
how many failed. A flag is killed when the treatment breaches its contract in `breach_windows`
windows in a row. A breach needs all three:
  1. enough traffic in the treatment to judge (`min_requests`),
  2. a treatment error rate above the contract's ceiling (`max_error_rate`),
  3. that rate above control's by at least `min_gap`, so an outage hitting everyone is not
     blamed on the new code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONTROL = "control"


@dataclass(frozen=True)
class Contract:
    flag: str
    experiment: str
    max_error_rate: float = 0.05
    min_requests: int = 20
    min_gap: float = 0.02
    breach_windows: int = 3
    window_seconds: int = 30
    on_breach: str = "kill"  # "kill" acts at once; "ask" only writes the incident note
    # Keys that only matter to other parts of Requiem. KILL reads and ignores them.
    owner: str | None = None  # who gets nagged (NAG)
    dies_on: str | None = None  # YYYY-MM-DD decide-or-delete date (NAG)
    retire: dict | None = None  # RETIRE: metric, win_probability, code, traffic (see requiem/retire.py)

    def __post_init__(self) -> None:
        if self.owner is not None and not isinstance(self.owner, str):
            raise ValueError("owner must be a string")
        if self.dies_on is not None:
            # YAML turns an unquoted 2026-12-15 into a date; keep it as the plain string.
            object.__setattr__(self, "dies_on", str(self.dies_on))
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.dies_on):
                raise ValueError("dies_on must look like YYYY-MM-DD")
        if self.retire is not None and not isinstance(self.retire, dict):
            raise ValueError("retire must be a mapping")
        if not 0 < self.max_error_rate < 1:
            raise ValueError("max_error_rate must be between 0 and 1")
        if self.breach_windows < 1 or self.min_requests < 1:
            raise ValueError("breach_windows and min_requests must be at least 1")
        if self.on_breach not in ("kill", "ask"):
            raise ValueError("on_breach must be 'kill' or 'ask'")


@dataclass(frozen=True)
class VariantWindow:
    requests: float
    errors: float

    @property
    def error_rate(self) -> float | None:
        return self.errors / self.requests if self.requests > 0 else None


@dataclass(frozen=True)
class WindowVerdict:
    breached: bool
    variant: str | None
    reason: str


def judge_window(contract: Contract, window: dict[str, VariantWindow]) -> WindowVerdict:
    """Is any treatment variant in breach in this one window?"""
    control = window.get(CONTROL)
    control_rate = control.error_rate if control else None
    worst: WindowVerdict | None = None
    for variant, w in sorted(window.items()):
        if variant == CONTROL:
            continue
        rate = w.error_rate
        if w.requests < contract.min_requests or rate is None:
            continue
        if rate <= contract.max_error_rate:
            continue
        if control_rate is not None and rate - control_rate < contract.min_gap:
            continue
        reason = (
            f"{variant}: {rate:.1%} errors over {w.requests:.0f} requests "
            f"(ceiling {contract.max_error_rate:.0%}"
            + (f", control {control_rate:.1%}" if control_rate is not None else ", no control traffic")
            + ")"
        )
        if worst is None or rate > (window[worst.variant].error_rate or 0):  # type: ignore[index]
            worst = WindowVerdict(True, variant, reason)
    if worst:
        return worst
    treated = sum(w.requests for v, w in window.items() if v != CONTROL)
    if treated < contract.min_requests:
        return WindowVerdict(False, None, f"not enough treatment traffic ({treated:.0f} < {contract.min_requests})")
    return WindowVerdict(False, None, "within contract")


@dataclass
class Tracker:
    """Counts consecutive breached windows for one contract."""

    contract: Contract
    streak: int = 0
    history: list[WindowVerdict] = field(default_factory=list)

    def observe(self, window: dict[str, VariantWindow]) -> WindowVerdict:
        v = judge_window(self.contract, window)
        self.history.append(v)
        self.streak = self.streak + 1 if v.breached else 0
        return v

    @property
    def should_act(self) -> bool:
        return self.streak >= self.contract.breach_windows
