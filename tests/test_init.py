"""Smoke test — verifies the package is importable."""

import unittest

import harness


class TestSmoke(unittest.TestCase):
    def test_package_importable(self) -> None:
        self.assertIsNotNone(harness)


class TestTasks(unittest.TestCase):
    def test_cmd_mutation_importable(self) -> None:
        from harness.tasks.mutation import cmd_mutation

        self.assertTrue(callable(cmd_mutation))
