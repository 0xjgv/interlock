"""Single-source budget-gate evaluator shared by ``ci`` and ``check`` stages.

The gate compares the current set of untraced public symbols (computed from
``cfg.src_dir`` minus the trace-map index) against the recorded budget. Per
spec ``required-acceptance-coverage`` (Sections "Budget gate runs after
runnable", "CI stage fails on budget rise", "CI stage rewrites budget on
shrink") the diff is asymmetric on the **set** — closing one symbol while
opening another no-ops the count but still flips the diff and fails listing
the new symbol. Design refs: D6 (gate logic), D7 (anti-evasion signature),
D11 (behave gap), D13 (enforcement gating).

The function is pure-ish: it mutates the budget file on shrink (atomic write +
re-sign) but never prints. Stages call it and emit messages — that keeps the
gate testable in-process and decoupled from ``ui`` / stderr ordering.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from interlocks.acceptance_budget import (
    compute_signature,
    compute_untraced,
    derive_repo_secret,
    load_budget,
    prune_stale,
    verify_signature,
    write_budget,
)
from interlocks.acceptance_symbols import iter_public_symbols

if TYPE_CHECKING:
    from interlocks.acceptance_budget import Budget
    from interlocks.config import InterlockConfig


GateKind = Literal["pass", "skip", "fail", "shrink_passed"]

_BEHAVE_NUDGE = "behave runner: trace recording unavailable (pytest-bdd only)"
_TAMPER_MESSAGE = (
    "budget tampering detected; run `interlocks acceptance baseline --force` "
    "after writing scenarios"
)
_MISSING_SIGNATURE_MESSAGE = "budget signature missing; run `interlocks acceptance baseline`"
_MAX_RISE_LISTED = 20


@dataclass(frozen=True)
class GateOutcome:
    """Result of a single budget-gate evaluation.

    ``message`` is empty when ``kind == "pass"`` (silent pass). For ``skip``
    only the ``behave_skip`` variant carries a message — other skips (no
    budget file, ``enforce_acceptance_budget = false``) are silent.
    """

    kind: GateKind
    message: str = ""
    rises: tuple[str, ...] = ()
    behave_skip: bool = False


def evaluate_acceptance_budget(cfg: InterlockConfig) -> GateOutcome:
    """Evaluate the budget gate against the current trace map.

    Returns a :class:`GateOutcome` describing what the caller should do:
    ``pass`` / ``skip`` (no action), ``shrink_passed`` (caller logs the
    decrement), ``fail`` (caller prints the message + rises and exits).

    Side effect: on shrink, this function rewrites ``cfg.acceptance_budget_path``
    atomically with the pruned + re-signed budget. That mutation lives here so
    both ``ci`` and ``check`` get the same anti-skew behaviour.
    """
    precheck = _precheck_gate(cfg)
    if isinstance(precheck, GateOutcome):
        return precheck
    budget, repo_secret = precheck
    return _diff_against_budget(cfg, budget, repo_secret)


def apply_budget_gate(outcome: GateOutcome) -> None:
    """Print outcome message + ``sys.exit(1)`` on fail; silent on pass/skip.

    Stages call this after :func:`evaluate_acceptance_budget`. Centralized so
    ``ci`` and ``check`` cannot drift in their reporting semantics.
    """
    if outcome.kind == "pass":
        return
    if outcome.kind == "skip":
        if outcome.behave_skip and outcome.message:
            print(outcome.message, file=sys.stderr)
        return
    if outcome.kind == "shrink_passed":
        print(outcome.message, file=sys.stderr)
        return
    print(outcome.message, file=sys.stderr)
    sys.exit(1)


def _precheck_gate(cfg: InterlockConfig) -> GateOutcome | tuple[Budget, str]:
    """Return either an early skip/fail outcome or the loaded ``(budget, secret)``."""
    if cfg.acceptance_runner == "behave":
        return GateOutcome(kind="skip", message=_BEHAVE_NUDGE, behave_skip=True)
    if not cfg.enforce_acceptance_budget or not cfg.acceptance_budget_path.exists():
        return GateOutcome(kind="skip")
    budget = load_budget(cfg.acceptance_budget_path)
    if budget is None:
        # Path existed but unreadable — same outcome as missing budget.
        return GateOutcome(kind="skip")
    repo_secret = derive_repo_secret(cfg.project_root)
    verdict = _signature_verdict(budget, repo_secret)
    if verdict is not None:
        return verdict
    return budget, repo_secret


def _signature_verdict(budget: Budget, repo_secret: str) -> GateOutcome | None:
    """Map ``verify_signature`` to a fail outcome (or ``None`` when valid)."""
    verdict = verify_signature(budget, repo_secret)
    if verdict == "mismatch":
        return GateOutcome(kind="fail", message=_TAMPER_MESSAGE)
    if verdict == "missing":
        return GateOutcome(kind="fail", message=_MISSING_SIGNATURE_MESSAGE)
    return None


def _diff_against_budget(cfg: InterlockConfig, budget: Budget, repo_secret: str) -> GateOutcome:
    """Compute current_untraced, diff against ``budget``, return rise/shrink/pass."""
    traced_index = _read_traced_index(cfg)
    public_symbols = list(iter_public_symbols(cfg))
    current_untraced = compute_untraced(public_symbols, traced_index)

    current_set = _flatten(current_untraced)
    budget_set = _flatten(budget.untraced)

    rises = sorted(current_set - budget_set)
    if rises:
        return GateOutcome(
            kind="fail",
            message=_rise_message(rises),
            rises=tuple(rises[:_MAX_RISE_LISTED]),
        )
    drops = budget_set - current_set
    if drops:
        _rewrite_shrunk_budget(cfg, budget, current_untraced, public_symbols, repo_secret)
        return GateOutcome(kind="shrink_passed", message=_shrink_message(sorted(drops)))
    return GateOutcome(kind="pass")


def _flatten(untraced: dict[str, list[str]]) -> set[str]:
    """Collapse ``module -> [attr, ...]`` to the flat ``"module:attr"`` set."""
    return {f"{module}:{attr}" for module, attrs in untraced.items() for attr in attrs}


def _read_traced_index(cfg: InterlockConfig) -> list[str]:
    """Read ``traced_symbols_index`` from ``cfg.acceptance_trace_path``.

    Returns an empty list when the trace file is absent or malformed —
    matching the behave/pre-trace path: every public symbol falls into the
    "untraced" set, mirroring the budget at baseline time.
    """
    path = cfg.acceptance_trace_path
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = payload.get("traced_symbols_index")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _rewrite_shrunk_budget(
    cfg: InterlockConfig,
    budget: Budget,
    current_untraced: dict[str, list[str]],
    public_symbols: list[tuple[str, str]],
    repo_secret: str,
) -> None:
    """Replace the budget's ``untraced`` with the freshly-shrunk set, re-sign, write.

    Defensively passes the result through :func:`prune_stale` so any symbols that
    were also deleted from source (e.g. the trace and the source change in the
    same edit) do not slip back in via the snapshot.
    """
    snapshot = replace(
        budget,
        untraced=current_untraced,
        untraced_count=sum(len(attrs) for attrs in current_untraced.values()),
        signature=None,
    )
    pruned = prune_stale(snapshot, public_symbols)
    signed = replace(pruned, signature=compute_signature(pruned, repo_secret))
    write_budget(cfg.acceptance_budget_path, signed)


def _rise_message(rises: list[str]) -> str:
    listed = rises[:_MAX_RISE_LISTED]
    suffix = ""
    if len(rises) > _MAX_RISE_LISTED:
        suffix = f" (+{len(rises) - _MAX_RISE_LISTED} more)"
    return (
        f"acceptance budget: {len(rises)} new untraced public symbol(s){suffix}; "
        "add a covering scenario or run "
        "`interlocks acceptance baseline --force` after writing scenarios:\n"
        + "\n".join(f"  - {symbol}" for symbol in listed)
    )


def _shrink_message(drops: list[str]) -> str:
    sample = ", ".join(drops[:5])
    suffix = "" if len(drops) <= 5 else f" (+{len(drops) - 5} more)"
    return (
        f"acceptance budget: shrunk by {len(drops)} symbol(s) — {sample}{suffix}; rewrote budget."
    )


__all__ = [
    "GateKind",
    "GateOutcome",
    "apply_budget_gate",
    "evaluate_acceptance_budget",
]
