"""Test helper: every test gets a throwaway Mind root with both client stores."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import MemoryUpdater
import MindStores
import SemanticMemory


class TempMindTestCase(unittest.TestCase):
    """Points MindStores at a temp dir and starts each test without an active surface."""

    def setUp(self):
        super().setUp()
        self._mind_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.mind_root = Path(self._mind_tmp.name) / "Mind"
        self.mind_root.mkdir(parents=True)
        self._root_patch = patch.object(MindStores, "MIND_ROOT", self.mind_root)
        self._root_patch.start()
        MemoryUpdater.reset_engines()
        SemanticMemory.reset_clients()
        self._surface_token = MindStores._SURFACE.set(None)

    def tearDown(self):
        MindStores._SURFACE.reset(self._surface_token)
        MemoryUpdater.reset_engines()
        SemanticMemory.reset_clients()
        self._root_patch.stop()
        self._mind_tmp.cleanup()
        super().tearDown()

    def db(self, surface: str) -> Path:
        return MindStores.db_path(surface)
