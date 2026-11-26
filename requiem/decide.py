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

    def __post_init__(self) -> None:
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
