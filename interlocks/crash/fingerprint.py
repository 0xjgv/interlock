"""Stable 16-hex fingerprint of a crash for 30-day dedup.

We hash ``(filename, function_name)`` pairs plus the exception type — NOT line
numbers. A refactor that shifts a function down by ten lines is the same bug;
recomputing a different fingerprint would defeat dedup the first time anyone
edits the file. The fingerprint is short (16 hex) because it only needs to be
unique across one user's recent crashes, not globally.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# (filename, function_name). Line numbers are intentionally excluded; see
# the module docstring.
FrameTuple = tuple[str, str]


def compute(frames: Sequence[FrameTuple], exception_type: str) -> str:
    # Canonical JSON: sort_keys + tight separators ensure two equivalent inputs
    # produce byte-identical bytes regardless of dict insertion order or
    # whitespace. Lists preserve order, which is what we want — frame order is
    # part of the bug's identity.
    payload = [list(pairs) for pairs in frames], exception_type
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:16]
