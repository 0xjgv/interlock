"""Path/traceback redaction for crash payloads.

The crash boundary captures a traceback; the payload that ends up in a
``~/.cache`` file (and, with consent, a pre-filled GitHub issue body) must
not leak personally identifying paths or third-party frames. This module is
the single place that turns a live ``TracebackType`` into the redacted shape
written to disk.

Design notes:

* Replacement order in :func:`scrub_path` matters — ``Path.home()`` literal
  substitution runs first because home is the most user-identifying segment
  and may sit anywhere in the string. Generic ``/Users/<seg>`` and
  ``/home/<seg>`` patterns then catch *other* users' homes (CI bots, shared
  runners). Site-packages collapse drops virtual-env/install prefixes that
  would otherwise pin the user's machine. Project-root substitution runs
  last so its replacement applies only to the still-recognisable absolute
  string.
* Frames outside the ``interlocks/`` package are collapsed into a single
  ``ExternalFrames(count=N)`` marker. The crash boundary only ever fires on
  bugs that touch interlocks code; surrounding stdlib/third-party frames
  carry no actionable signal and risk leaking install paths.
"""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import interlocks

if TYPE_CHECKING:
    from types import TracebackType

_USER_PATH_RE = re.compile(r"(?P<root>/Users|/home)/[^/\s]+")
_SITE_PACKAGES_RE = re.compile(r".*?site-packages/")


@dataclass(frozen=True)
class ScrubbedFrame:
    """A traceback frame inside ``interlocks/`` after path redaction."""

    filename: str
    line_no: int
    function_name: str


@dataclass(frozen=True)
class ExternalFrames:
    """Marker that collapses a run of non-interlocks frames into a single count."""

    count: int


def scrub_path(p: str, project_root: Path | None) -> str:
    """Redact a filesystem path so it carries no user-identifying segments.

    Order is load-bearing: home substitution must run before the generic
    ``/Users``/``/home`` regex so the current user's path becomes ``~`` rather
    than ``/Users/<user>``. Empty home (``HOME`` unset, or a non-existent
    user) skips the literal step instead of crashing — the regex still runs.
    """
    result = p
    home = _safe_home_str()
    if home:
        result = result.replace(home, "~")
    result = _USER_PATH_RE.sub(lambda m: f"{m.group('root')}/<user>", result)
    result = _SITE_PACKAGES_RE.sub("<site-packages>/", result, count=1)
    if project_root is not None:
        result = result.replace(str(project_root), "<project>")
    return result


def is_interlocks_frame(filename: str) -> bool:
    """True iff ``filename`` lives under the installed ``interlocks/`` package dir."""
    pkg_root = _interlocks_package_root()
    if not pkg_root:
        return False
    return filename.startswith(pkg_root)


def normalize_traceback(
    tb: TracebackType | None, project_root: Path | None
) -> tuple[ScrubbedFrame | ExternalFrames, ...]:
    """Walk ``tb`` producing ``ScrubbedFrame`` for interlocks frames + collapsed externals.

    Adjacent non-interlocks frames merge into a single :class:`ExternalFrames`
    marker. The result is a tuple alternating frame markers; consumers can
    rely on ``isinstance`` to disambiguate.
    """
    items: list[ScrubbedFrame | ExternalFrames] = []
    external_run = 0
    cursor = tb
    while cursor is not None:
        filename = cursor.tb_frame.f_code.co_filename
        if is_interlocks_frame(filename):
            if external_run:
                items.append(ExternalFrames(count=external_run))
                external_run = 0
            items.append(
                ScrubbedFrame(
                    filename=scrub_path(filename, project_root),
                    line_no=cursor.tb_lineno,
                    function_name=cursor.tb_frame.f_code.co_name,
                )
            )
        else:
            external_run += 1
        cursor = cursor.tb_next
    if external_run:
        items.append(ExternalFrames(count=external_run))
    return tuple(items)


def _safe_home_str() -> str:
    """Return ``str(Path.home())`` or empty string when home cannot be resolved.

    ``Path.home()`` raises ``RuntimeError`` when ``HOME`` is unset on POSIX
    and the password-database lookup fails. The redactor must not crash the
    crash reporter — invariant I6.
    """
    try:
        return str(Path.home())
    except RuntimeError:
        return ""


@functools.cache
def _interlocks_package_root() -> str:
    """Absolute path prefix (with trailing separator) of the installed package."""
    pkg_file = interlocks.__file__
    if pkg_file is None:
        return ""
    return str(Path(pkg_file).resolve().parent) + os.sep
