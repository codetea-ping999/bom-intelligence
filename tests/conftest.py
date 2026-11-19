from __future__ import annotations

from pathlib import Path

import pytest

from bom_intelligence.synthetic import build_fixtures


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("synthetic")
    build_fixtures(root)
    return root
