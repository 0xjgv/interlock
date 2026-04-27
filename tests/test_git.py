"""Tests for interlocks.git — ref-scoped diff helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from interlocks import git as git_mod
from interlocks.git import changed_py_files_vs


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S607 — git on PATH


def _init_repo(root: Path) -> None:
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    _git("config", "commit.gpgsign", "false", cwd=root)
    _git("config", "core.hooksPath", "/dev/null", cwd=root)


def _commit_all(root: Path, message: str) -> None:
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", message, cwd=root)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _init_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.interlock]\nsrc_dir = "interlock"\ntest_dir = "tests"\n',
        encoding="utf-8",
    )
    (tmp_path / "interlock").mkdir()
    (tmp_path / "interlock" / "base.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_changed_py_files_vs_happy_path(repo: Path) -> None:
    (repo / "interlock" / "added.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(repo, "add file")

    assert changed_py_files_vs("HEAD~1") == {"interlock/added.py"}


def test_changed_py_files_vs_ignores_non_py(repo: Path) -> None:
    (repo / "interlock" / "added.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "interlock" / "notes.md").write_text("hi\n", encoding="utf-8")
    (repo / "interlock" / "data.txt").write_text("x\n", encoding="utf-8")
    _commit_all(repo, "mixed")

    assert changed_py_files_vs("HEAD~1") == {"interlock/added.py"}


def test_changed_py_files_vs_filters_out_of_tree_paths(repo: Path) -> None:
    """Files outside the configured src/test dirs are dropped (matches siblings)."""
    (repo / "interlock" / "in_src.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "helper.py").write_text("b = 2\n", encoding="utf-8")
    _commit_all(repo, "mixed dirs")

    assert changed_py_files_vs("HEAD~1") == {"interlock/in_src.py"}


def test_changed_py_files_vs_detects_renames(repo: Path) -> None:
    body = "def greet():\n    return 'hi there'\n" * 5
    (repo / "interlock" / "old_name.py").write_text(body, encoding="utf-8")
    _commit_all(repo, "seed file")
    _git("mv", "interlock/old_name.py", "interlock/new_name.py", cwd=repo)
    _commit_all(repo, "rename")

    result = changed_py_files_vs("HEAD~1")
    assert result == {"interlock/new_name.py"}


def test_changed_py_files_vs_missing_ref_returns_empty(repo: Path) -> None:
    assert changed_py_files_vs("does-not-exist") == set()


def test_changed_py_files_vs_main_wrapper(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapper delegates to changed_py_files_vs('origin/main')."""
    calls: list[str] = []

    def _fake(ref: str) -> set[str]:
        calls.append(ref)
        return {"sentinel.py"}

    monkeypatch.setattr(git_mod, "changed_py_files_vs", _fake)

    assert git_mod.changed_py_files_vs_main() == {"sentinel.py"}
    assert calls == ["origin/main"]


def _stub_cfg(monkeypatch: pytest.MonkeyPatch, src: str, test: str) -> None:
    stub = SimpleNamespace(src_dir_arg=src, test_dir_arg=test)
    monkeypatch.setattr(git_mod, "load_config", lambda: stub)


def test_src_test_prefixes_includes_both(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_cfg(monkeypatch, "src", "tests")
    assert git_mod._src_test_prefixes() == ("src/", "tests/")


def test_src_test_prefixes_skips_dot_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project root (`.`) is not a prefix — fall through to the `("",)` sentinel."""
    _stub_cfg(monkeypatch, ".", ".")
    assert git_mod._src_test_prefixes() == ("",)


def test_src_test_prefixes_skips_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty src/test dirs are skipped — fall through to the `("",)` sentinel."""
    _stub_cfg(monkeypatch, "", "")
    assert git_mod._src_test_prefixes() == ("",)
