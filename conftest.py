"""Shared pytest setup for every test directory (pytest.ini testpaths)."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _no_ai_usage_writes(monkeypatch):
    """Tests never write ai_usage rows to the real database. Tests that check
    what would be recorded read this mock (ai_usage.recorder._insert)."""
    import ai_usage.recorder as recorder
    insert = MagicMock()
    monkeypatch.setattr(recorder, "_insert", insert)
    return insert
