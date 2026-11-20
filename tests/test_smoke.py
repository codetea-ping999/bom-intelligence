from __future__ import annotations

import pytest

import bom_intelligence
from bom_intelligence.cli import main


def test_version() -> None:
    assert bom_intelligence.__version__


def test_cli_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "bom" in capsys.readouterr().out


def test_cli_without_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out
