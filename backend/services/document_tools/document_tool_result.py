from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DocumentToolResult:
    ok: bool
    operation: str
    source_paths: list[str] = field(default_factory=list)
    output_path: str | None = None
    output_filename: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        *,
        operation: str,
        source_paths: list[str | Path],
        output_path: str | Path,
        warnings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "DocumentToolResult":
        output = Path(output_path)
        return cls(
            ok=True,
            operation=operation,
            source_paths=[str(Path(p)) for p in source_paths],
            output_path=str(output),
            output_filename=output.name,
            warnings=warnings or [],
            errors=[],
            metadata=metadata or {},
        )

    @classmethod
    def failure(
        cls,
        *,
        operation: str,
        source_paths: list[str | Path] | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "DocumentToolResult":
        return cls(
            ok=False,
            operation=operation,
            source_paths=[str(Path(p)) for p in (source_paths or [])],
            output_path=None,
            output_filename=None,
            warnings=warnings or [],
            errors=errors or [],
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "source_paths": self.source_paths,
            "output_path": self.output_path,
            "output_filename": self.output_filename,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
        }
