"""#13: reference docs are generated from the code's registries and must stay in sync with it."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pagan.docs import ACCEPTED, main, notation_drift
from pagan.findings import ERROR_RULES
from pagan.lint import WARNING_RULES
from pagan.settings import SETTINGS

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = (ROOT / "src" / "pagan" / "skill" / "reference.md").read_text(encoding="utf-8")


def test_generated_docs_are_up_to_date() -> None:
    assert main(["--check", "--docs", str(ROOT / "docs")]) == 0, "run `python -m pagan.docs` and commit docs/"


def test_every_accepted_field_is_documented() -> None:
    assert notation_drift() == []


def test_every_rule_in_the_code_is_registered() -> None:
    used = set()
    for path in (ROOT / "src" / "pagan").rglob("*.py"):
        used |= set(re.findall(r'"([EW]\d{3})"', path.read_text(encoding="utf-8")))
    assert used == set(ERROR_RULES) | set(WARNING_RULES)


def test_skill_reference_covers_every_rule_setting_and_field() -> None:
    rules = REFERENCE.split("## Lint rules", 1)[1].split("\n## ", 1)[0]
    assert [r for r in [*ERROR_RULES, *WARNING_RULES] if r not in rules] == []
    block = REFERENCE.split("## `pagan.toml`", 1)[1].split("```toml\n", 1)[1].split("```", 1)[0]
    example = tomllib.loads(block)
    missing_settings = [s.key for s in SETTINGS if s.name not in (example.get(s.table, {}) if s.table else example)]
    assert missing_settings == []
    missing = [f"{kind}.{f}" for kind, fields in ACCEPTED.items() for f in fields if not re.search(rf"\b{f}\b", REFERENCE)]
    assert missing == []
