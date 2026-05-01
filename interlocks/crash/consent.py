"""Consent gate that resolves whether crash reports may surface via transport.

Pure function of inputs: callers pass the env mapping explicitly so resolution
stays deterministic and testable. Precedence (highest first):

1. ``INTERLOCKS_CRASH_REPORTS`` env var (``"off"`` / ``"on"``).
2. ``cfg.crash_reports`` (``"off"`` / ``"on"`` / ``"auto"``).
3. Default rule: suppress when ``CI=true``; otherwise allow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from interlocks.config import InterlockConfig


class ConsentGate:
    """Resolve whether the crash transport is allowed for this invocation."""

    @staticmethod
    def allow_transport(cfg: InterlockConfig, env: Mapping[str, str]) -> bool:
        env_override = env.get("INTERLOCKS_CRASH_REPORTS")
        if env_override == "off":
            return False
        if env_override == "on":
            return True
        if cfg.crash_reports == "off":
            return False
        if cfg.crash_reports == "on":
            return True
        # auto: default rule — only the literal string "true" suppresses, so
        # CI=1 / CI=yes / CI=anything-else still allows local-friendly flow.
        return env.get("CI") != "true"
