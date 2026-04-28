"""Content-derived stable identity for Gherkin scenarios.

The identity is a 16-character SHA-256 prefix over normalized step lines.
Title is excluded so renames preserve identity; comment + blank lines are
excluded so cosmetic edits don't invalidate trace credit; ``Background:``
blocks and ``Examples:`` rows are excluded from the per-scenario hash so
shared setup and outline data churn don't bleed into identity.

Consumed by the trace plugin (subprocess recorder) and the budget gate.
Stdlib-only by design (D4): no external Gherkin parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

_STEP_KEYWORDS: tuple[str, ...] = ("Given", "When", "Then", "And", "But")


@dataclass(frozen=True)
class Scenario:
    """A single Gherkin scenario or scenario outline.

    ``identity`` is derived from ``steps`` via :func:`scenario_identity`.
    ``steps`` preserves the raw step text as it appeared in the file
    (lstripped to drop indentation but otherwise unchanged) so downstream
    consumers can render the scenario without re-reading the source.
    """

    identity: str
    title: str
    feature_path: Path
    steps: tuple[str, ...]


def scenario_identity(steps: list[str]) -> str:
    """Return the 16-char SHA-256 prefix identity for a list of step lines.

    Per spec D4: each line is stripped + lowercased; blank lines and ``#``
    comments are dropped; survivors are joined with ``"\\n"``.
    """
    normalized = [
        stripped.lower()
        for stripped in (raw.strip() for raw in steps)
        if stripped and not stripped.startswith("#")
    ]
    payload = "\n".join(normalized).encode("utf-8")
    return sha256(payload).hexdigest()[:16]


def _is_step_line(stripped: str) -> bool:
    """Return True if ``stripped`` starts with a Gherkin step keyword."""
    for kw in _STEP_KEYWORDS:
        if stripped.startswith(kw):
            tail = stripped[len(kw) :]
            # Keyword must be followed by whitespace or end of line so we don't
            # match identifiers like ``Andrew``.
            if not tail or tail[0].isspace():
                return True
    return False


def iter_scenarios(feature_path: Path) -> Iterable[Scenario]:
    """Yield one :class:`Scenario` per ``Scenario:`` or ``Scenario Outline:`` block.

    Parser is stdlib-only and intentionally lenient: it recognizes the four
    block headers (``Feature:``, ``Rule:``, ``Background:``, ``Scenario:``,
    ``Scenario Outline:``, ``Examples:``) and step keywords. Anything else is
    treated as descriptive prose and ignored.

    Hash semantics (per spec):
    - ``Background:`` step lines are NEVER fed into the hash.
    - ``Examples:`` table rows are NEVER fed into the hash.
    - For ``Scenario Outline:``, identity is computed once over the Outline's
      step block. Adding/removing Examples rows preserves identity.
    """
    return _iter_scenarios_impl(feature_path)


def _classify_header(stripped: str) -> str | None:
    """Return a header tag for a Gherkin block opener, or ``None``.

    Tags:
    - ``"reset"``: Feature/Rule — clears any open scenario, no new title.
    - ``"background"``: opens a Background block (steps discarded).
    - ``"scenario"``: opens a Scenario or Scenario Outline (steps recorded).
    - ``"examples"``: Examples/Scenarios row block (rows discarded).
    """
    if stripped.startswith(("Feature:", "Rule:")):
        return "reset"
    if stripped.startswith("Background:"):
        return "background"
    if stripped.startswith(("Scenario Outline:", "Scenario Template:", "Scenario:")):
        return "scenario"
    if stripped.startswith(("Examples:", "Scenarios:")):
        return "examples"
    return None


class _ScenarioParser:
    """Streaming parser that yields one ``Scenario`` per closed block.

    Pulled out of ``_iter_scenarios_impl`` to keep the iterator's CCN below the
    project gate; behavior is identical to the previous in-line state machine.
    """

    def __init__(self, feature_path: Path) -> None:
        self.feature_path = feature_path
        self.title: str | None = None
        self.steps: list[str] = []
        # "scenario" → record steps; "background"/"examples" → discard;
        # ``None`` → between blocks (header or feature description).
        self.state: str | None = None

    def flush(self) -> Scenario | None:
        if self.title is None:
            return None
        steps_tuple = tuple(self.steps)
        return Scenario(
            identity=scenario_identity(list(steps_tuple)),
            title=self.title,
            feature_path=self.feature_path,
            steps=steps_tuple,
        )

    def open_block(self, header: str, stripped: str) -> Scenario | None:
        """Transition to the new block; flush + return the prior scenario when needed.

        ``Examples:`` does NOT close the open Outline — the Outline stays open
        so a later ``Scenario:`` (or EOF) flushes it normally and so that
        Examples-row churn cannot influence the identity hash.
        """
        if header == "examples":
            self.state = "examples"
            return None
        scenario = self.flush()
        if header == "scenario":
            self.title = stripped.split(":", 1)[1].strip()
            self.steps = []
            self.state = "scenario"
        else:
            # reset / background — drop any accumulated title/steps.
            self.title = None
            self.steps = []
            self.state = None if header == "reset" else "background"
        return scenario

    def add_step_if_recording(self, raw_line: str, stripped: str) -> None:
        if self.state == "scenario" and _is_step_line(stripped):
            # Preserve original text minus leading indentation; identity
            # normalization happens in ``scenario_identity``.
            self.steps.append(raw_line.lstrip())


def _iter_scenarios_impl(feature_path: Path) -> Iterator[Scenario]:
    parser = _ScenarioParser(feature_path)
    for raw_line in feature_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        header = _classify_header(stripped)
        if header is not None:
            scenario = parser.open_block(header, stripped)
            if scenario is not None:
                yield scenario
            continue
        parser.add_step_if_recording(raw_line, stripped)

    final = parser.flush()
    if final is not None:
        yield final
