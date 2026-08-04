from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FrameDiscoveryResult:
    """The exact EXR frames selected for processing."""

    source: Path
    frames: tuple[Path, ...]
    direct_frames: tuple[Path, ...]
    nested_frames: tuple[Path, ...]
    warnings: tuple[str, ...] = ()

    @property
    def frame_count(self) -> int:
        return len(self.frames)


def _natural_name_key(path: Path) -> tuple[tuple[int, object], ...]:
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.lower())
        for part in re.split(r"(\d+)", path.name)
    )


def _path_sort_key(path: Path) -> tuple[str, tuple[tuple[int, object], ...]]:
    return str(path.parent).lower(), _natural_name_key(path)


def _sorted_exr_files(folder: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() == ".exr"
            ),
            key=_path_sort_key,
        )
    )


def discover_frames(source: str | Path) -> FrameDiscoveryResult:
    """Discover the exact EXR files that should be processed.

    Policy for MVP:
    - a single EXR file is accepted directly;
    - direct EXRs in a folder take priority;
    - one-level nested EXRs are used only when no direct EXRs exist;
    - mixed direct and nested inputs produce a warning.
    """

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    if source_path.is_file():
        if source_path.suffix.lower() != ".exr":
            raise ValueError(f"Input file is not an EXR: {source_path}")
        resolved = (source_path,)
        return FrameDiscoveryResult(
            source=source_path,
            frames=resolved,
            direct_frames=resolved,
            nested_frames=(),
        )

    if not source_path.is_dir():
        raise NotADirectoryError(source_path)

    direct_frames = _sorted_exr_files(source_path)
    nested_frames = tuple(
        sorted(
            (
                frame
                for subfolder in source_path.iterdir()
                if subfolder.is_dir()
                for frame in _sorted_exr_files(subfolder)
            ),
            key=_path_sort_key,
        )
    )

    warnings: tuple[str, ...] = ()
    frames = direct_frames
    if direct_frames and nested_frames:
        warnings = (
            "Direct EXR files were found, so one-level nested EXR files were ignored.",
        )
    elif not direct_frames:
        frames = nested_frames

    return FrameDiscoveryResult(
        source=source_path,
        frames=frames,
        direct_frames=direct_frames,
        nested_frames=nested_frames,
        warnings=warnings,
    )
