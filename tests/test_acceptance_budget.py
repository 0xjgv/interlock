"""Unit tests for ``interlocks.acceptance_budget``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from interlocks.acceptance_budget import (
    Budget,
    compute_signature,
    compute_untraced,
    derive_repo_secret,
    load_budget,
    prune_stale,
    verify_signature,
    write_budget,
)


def _make_budget(
    untraced: dict[str, list[str]] | None = None,
    *,
    signature: str | None = None,
    baseline_at: str = "2026-04-28T12:00:00Z",
) -> Budget:
    untraced = untraced or {"interlocks.tasks.audit": ["cmd_audit", "task_audit"]}
    return Budget(
        version=1,
        baseline_at=baseline_at,
        untraced=untraced,
        untraced_count=sum(len(v) for v in untraced.values()),
        signature=signature,
    )


def test_load_budget_missing_returns_none(tmp_path: Path) -> None:
    assert load_budget(tmp_path / "does-not-exist.json") is None


def test_load_budget_round_trip(tmp_path: Path) -> None:
    budget = _make_budget(signature="sha256:abc")
    path = tmp_path / "budget.json"
    write_budget(path, budget)
    loaded = load_budget(path)
    assert loaded is not None
    assert loaded.version == 1
    assert loaded.baseline_at == "2026-04-28T12:00:00Z"
    assert loaded.untraced == {"interlocks.tasks.audit": ["cmd_audit", "task_audit"]}
    assert loaded.untraced_count == 2
    assert loaded.signature == "sha256:abc"


def test_compute_untraced_subtracts() -> None:
    public = [("m", "a"), ("m", "b"), ("n", "c")]
    traced = [("m", "a")]
    assert compute_untraced(public, traced) == {"m": ["b"], "n": ["c"]}


def test_compute_untraced_accepts_flat_strings() -> None:
    public = [("m", "a"), ("m", "b"), ("n", "c")]
    traced = ["m:a", "n:c"]
    assert compute_untraced(public, traced) == {"m": ["b"]}


def test_compute_untraced_sorts_attrs() -> None:
    public = [("m", "z"), ("m", "a"), ("m", "m")]
    traced: list[tuple[str, str]] = []
    result = compute_untraced(public, traced)
    assert result == {"m": ["a", "m", "z"]}


def test_prune_stale_drops_deleted_symbols() -> None:
    budget = _make_budget(
        {"m": ["a", "b"], "n": ["c"]},
        signature="sha256:original",
    )
    public = [("m", "a"), ("n", "c")]  # "m:b" is gone
    pruned = prune_stale(budget, public)
    assert pruned.untraced == {"m": ["a"], "n": ["c"]}
    assert pruned.untraced_count == 2
    assert pruned.signature is None


def test_prune_stale_drops_empty_modules() -> None:
    budget = _make_budget({"m": ["a"], "n": ["c"]}, signature="sha256:x")
    public = [("m", "a")]
    pruned = prune_stale(budget, public)
    assert pruned.untraced == {"m": ["a"]}


def test_write_budget_deterministic(tmp_path: Path) -> None:
    """Equal Budgets produce byte-identical files (insertion order independent)."""
    untraced_a = {
        "z.module": ["beta", "alpha"],
        "a.module": ["foo", "bar"],
    }
    untraced_b = {
        "a.module": ["bar", "foo"],
        "z.module": ["alpha", "beta"],
    }
    budget_a = _make_budget(untraced_a, signature="sha256:1")
    budget_b = _make_budget(untraced_b, signature="sha256:1")

    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    write_budget(path_a, budget_a)
    write_budget(path_b, budget_b)
    assert path_a.read_bytes() == path_b.read_bytes()


def test_write_budget_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    write_budget(path, _make_budget(signature="sha256:x"))
    assert path.exists()
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"tempfile leaked: {leftovers}"


def test_write_budget_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "subdir" / "budget.json"
    write_budget(path, _make_budget(signature="sha256:x"))
    assert path.exists()


def test_write_budget_key_order(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    write_budget(path, _make_budget(signature="sha256:order"))
    raw = path.read_text(encoding="utf-8")
    keys_in_order = ["version", "baseline_at", "untraced", "untraced_count", "signature"]
    indices = [raw.index(f'"{k}"') for k in keys_in_order]
    assert indices == sorted(indices)


def test_compute_signature_deterministic() -> None:
    budget = _make_budget()
    s1 = compute_signature(budget, "secret-x")
    s2 = compute_signature(budget, "secret-x")
    assert s1 == s2
    assert s1.startswith("sha256:")
    # sha256 hex digest is 64 chars; with prefix, total length 71. The contract
    # only requires "16+ chars".
    assert len(s1) > 16


def test_compute_signature_differs_across_secrets() -> None:
    budget = _make_budget()
    assert compute_signature(budget, "alpha") != compute_signature(budget, "beta")


def test_compute_signature_ignores_existing_signature_field() -> None:
    """Signature recomputation must not be affected by the stored signature value."""
    b1 = _make_budget(signature=None)
    b2 = _make_budget(signature="sha256:stale")
    assert compute_signature(b1, "secret") == compute_signature(b2, "secret")


def test_verify_signature_ok_round_trip() -> None:
    budget = _make_budget()
    sig = compute_signature(budget, "repo-secret")
    signed = Budget(
        version=budget.version,
        baseline_at=budget.baseline_at,
        untraced=budget.untraced,
        untraced_count=budget.untraced_count,
        signature=sig,
    )
    assert verify_signature(signed, "repo-secret") == "ok"


def test_verify_signature_missing() -> None:
    budget = _make_budget(signature=None)
    assert verify_signature(budget, "repo-secret") == "missing"


def test_verify_signature_missing_empty_string() -> None:
    budget = _make_budget(signature="")
    assert verify_signature(budget, "repo-secret") == "missing"


def test_verify_signature_hand_grow_detected(tmp_path: Path) -> None:
    """Mutate untraced after signing -> mismatch (anti-evasion contract)."""
    budget = _make_budget({"m": ["a"]})
    sig = compute_signature(budget, "secret")
    signed = Budget(
        version=budget.version,
        baseline_at=budget.baseline_at,
        untraced=budget.untraced,
        untraced_count=budget.untraced_count,
        signature=sig,
    )
    path = tmp_path / "budget.json"
    write_budget(path, signed)

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["untraced"]["m"].append("b")
    raw["untraced_count"] = 2
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    loaded = load_budget(path)
    assert loaded is not None
    assert verify_signature(loaded, "secret") == "mismatch"


def test_verify_signature_distinguishes_missing_from_mismatch() -> None:
    """Missing must not collide with mismatch (different remediation messages)."""
    budget = _make_budget()
    assert verify_signature(budget, "secret") == "missing"

    bogus = Budget(
        version=budget.version,
        baseline_at=budget.baseline_at,
        untraced=budget.untraced,
        untraced_count=budget.untraced_count,
        signature="sha256:" + "0" * 64,
    )
    assert verify_signature(bogus, "secret") == "mismatch"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],  # noqa: S607
        cwd=str(cwd),
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "PATH": __import__("os").environ.get("PATH", ""),
            "HOME": str(cwd),
            "GIT_CONFIG_GLOBAL": str(cwd / ".gitconfig-empty"),
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )


def test_derive_repo_secret_returns_first_commit_hash(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    (tmp_path / "x.txt").write_text("hello", encoding="utf-8")
    _git(tmp_path, "add", "x.txt")
    _git(tmp_path, "commit", "-m", "first")

    secret = derive_repo_secret(tmp_path)
    # First commit hash: 40 hex chars.
    assert len(secret) == 40
    assert all(c in "0123456789abcdef" for c in secret)


def test_derive_repo_secret_falls_back_when_no_git(tmp_path: Path) -> None:
    secret = derive_repo_secret(tmp_path)
    assert secret == f"interlocks-acceptance-budget:{tmp_path.resolve()}"


def test_derive_repo_secret_falls_back_on_empty_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    secret = derive_repo_secret(tmp_path)
    assert secret == f"interlocks-acceptance-budget:{tmp_path.resolve()}"


def test_load_budget_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_budget(path)


def test_load_budget_missing_field_raises(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(KeyError):
        load_budget(path)
