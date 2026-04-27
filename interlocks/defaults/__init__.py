"""Bundled default configs (ruff, coverage, pyright, deptry, import-linter, mutmut).

These ship inside the wheel and are the lowest-priority layer of the precedence
cascade: project [tool.<x>] or sidecar files > ~/.config/interlocks/* > these.
"""
