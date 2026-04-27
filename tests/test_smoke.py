"""Smoke test — verifies the package is importable."""

import unittest

import interlocks


class TestSmoke(unittest.TestCase):
    def test_package_importable(self) -> None:
        self.assertIsNotNone(interlocks)
