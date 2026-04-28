"""Atomic write helper.

Writes bytes via a sibling tmpfile + ``Path.replace``. Preserves the destination
file's mode when one already exists (best-effort). Cleans up the tmpfile on any
exception, including ``KeyboardInterrupt`` / ``SystemExit``.

Stdlib only.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write ``data`` to ``path``.

    Creates parent directories as needed. Writes to a sibling tmpfile, copies
    the destination's existing mode (if any), then ``Path.replace``\\ s into
    place. On any exception the tmpfile is unlinked.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        with suppress(FileNotFoundError):
            Path(tmp_name).chmod(path.stat().st_mode)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


__all__ = ["atomic_write_bytes"]
