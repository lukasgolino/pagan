import subprocess
import sys

import pytest

from pagan import __version__
from pagan.cli import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"pagan {__version__}"


def test_runs_as_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pagan", "--version"], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == f"pagan {__version__}"
