from __future__ import annotations

import pytest

from spotvm_tool import reporting


@pytest.fixture(autouse=True)
def restore_reporting_colors():
    original = reporting._COLORS_ENABLED
    yield
    reporting._COLORS_ENABLED = original
