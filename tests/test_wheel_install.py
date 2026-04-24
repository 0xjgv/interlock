"""Wheel-install smoke test.

Builds the interlock wheel, installs it into a clean venv, and runs
`interlock help`. Guards the `pipx install interlock` promise from the README
against packaging regressions (e.g. missing `interlock/defaults/*` data files).

Marked `slow` because building a wheel and creating a fresh venv takes several
seconds; the `slow` marker is registered in pyproject.toml. Opt in with
`pytest -m slow`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX venv layout assumed")
def test_wheel_installs_and_interlock_help_runs(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv required")

    dist_dir = tmp_path / "dist"
    build_cmd = ["uv", "build", "--out-dir", str(dist_dir), str(REPO_ROOT)]
    subprocess.run(build_cmd, check=True, cwd=tmp_path)

    wheels = list(dist_dir.glob("*.whl"))
    assert wheels, f"no wheel produced in {dist_dir}"
    wheel = wheels[0]

    venv_cmd = ["uv", "venv", "venv"]
    subprocess.run(venv_cmd, check=True, cwd=tmp_path)

    venv_python = tmp_path / "venv" / "bin" / "python"
    install_cmd = ["uv", "pip", "install", str(wheel), "--python", str(venv_python)]
    subprocess.run(install_cmd, check=True, cwd=tmp_path)

    interlock_bin = tmp_path / "venv" / "bin" / "interlock"
    assert interlock_bin.exists(), f"interlock entry point missing at {interlock_bin}"
    assert interlock_bin.stat().st_mode & 0o111, "interlock entry point not executable"

    result = subprocess.run(
        [str(interlock_bin), "help"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    for expected in ("check", "pre-commit", "ci", "nightly"):
        assert expected in result.stdout, (
            f"`interlock help` output missing {expected!r}:\n{result.stdout}"
        )
