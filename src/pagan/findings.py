"""Findings (errors and warnings) reported by PAGAN, and the exception that carries them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning"]

# Every error rule (warnings: pagan.lint.WARNING_RULES). The generated docs list these.
ERROR_RULES = {
    "E000": "command or usage error (no pagan.toml found, project already exists, ...): not a source-file rule",
    "E001": "YAML syntax or a field problem (unknown, missing or wrong type)",
    "E002": "unknown pixel key: not `.` and not a palette key",
    "E003": "grid or size mismatch (rows, row widths, a size that isn't a multiple of `supersample`)",
    "E004": "an animation names a frame that doesn't exist",
    "E005": "palette problem (unknown palette, bad colour or ramp)",
    "E006": "variant problem",
    "E007": "outline or shadow would be clipped at the canvas edge",
    "E008": "pivot or point outside the canvas, or malformed",
    "E009": "inline palette in strict mode",
    "E010": "derived frame problem (unknown source, cycle, pixels pushed off the canvas)",
    "E011": "outline required by `[lint] require_outline`",
    "E012": "duplicate asset name across sprites, tilesets and models",
    "E013": "3D model problem (parts, materials, poses, camera)",
    "E014": "rig or mesh problem (unknown rig id or parent, parent cycle, a hidden carving part with meshes)",
    "E015": "translucent colour with `[lint] require_opaque`",
    "E016": "timeline preview problem (`scenes/*.timeline.yaml`)",
}


def display_path(path: Path) -> str:
    """Show a path relative to the working directory (with ../ when needed); absolute if on another drive."""
    try:
        return os.path.relpath(path.resolve(), Path.cwd().resolve())
    except ValueError:
        return str(path.resolve())


@dataclass(frozen=True)
class Finding:
    """One problem in a source file. Rule ids starting with E are errors, W are warnings."""

    rule: str
    message: str
    path: Path | None = None
    line: int | None = None
    where: str | None = None  # e.g. "colors.5.hex" or "frames.idle_0 row 3 col 7"

    @property
    def severity(self) -> Severity:
        return "error" if self.rule.startswith("E") else "warning"

    def format(self) -> str:
        where = f" [{self.where}]" if self.where else ""
        if self.path is None and self.line is None:
            return f"{self.severity} {self.rule}{where}: {self.message}"
        location = display_path(self.path) if self.path is not None else "<input>"
        if self.line is not None:
            location += f":{self.line}"
        return f"{location}: {self.severity} {self.rule}{where}: {self.message}"

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "path": display_path(self.path) if self.path is not None else None,
            "line": self.line,
            "where": self.where,
        }


class PaganError(Exception):
    """Raised when an operation can't continue; carries the findings that explain why."""

    def __init__(self, findings: list[Finding]) -> None:
        super().__init__("\n".join(f.format() for f in findings))
        self.findings = findings


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == "error" for f in findings)
