from __future__ import annotations

from pathlib import Path
from typing import Collection, Iterable

import numpy as np
import OpenEXR

from aovguard.core.models import AOVCategory, AOVDescriptor, FileInspection, FrameData
from aovguard.io.inspector import build_file_inspection


def _size_from_header(header) -> tuple[int, int]:
    data_window = header["dataWindow"]
    if isinstance(data_window, tuple):
        minimum, maximum = data_window
        width = int(maximum[0] - minimum[0] + 1)
        height = int(maximum[1] - minimum[1] + 1)
        return width, height
    width = data_window.max.x - data_window.min.x + 1
    height = data_window.max.y - data_window.min.y + 1
    return width, height


def _suffix(channel: str) -> str:
    if "." not in channel:
        return channel.upper()
    return channel.rsplit(".", 1)[1].upper()


def _channels_by_suffix(channels: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for channel in channels:
        mapping.setdefault(_suffix(channel), channel)
    return mapping


def _ordered_channels(
    descriptor: AOVDescriptor,
    suffixes: tuple[str, ...],
) -> tuple[str, ...]:
    by_suffix = _channels_by_suffix(descriptor.channels)
    missing = [suffix for suffix in suffixes if suffix not in by_suffix]
    if missing:
        raise RuntimeError(
            f"AOV {descriptor.name!r} is missing channel suffix(es): {', '.join(missing)}"
        )
    return tuple(by_suffix[suffix] for suffix in suffixes)


def _inspection_from_file(exr, path: Path) -> FileInspection:
    if not exr.parts:
        raise RuntimeError(f"EXR contains no image parts: {path}")

    first_part = exr.parts[0]
    header = first_part.header
    width, height = _size_from_header(header)
    channels = tuple(channel.name for channel in header["channels"])
    deep_types = {OpenEXR.deepscanline, OpenEXR.deeptile}
    is_deep = any(part.type() in deep_types for part in exr.parts)
    warnings: tuple[str, ...] = ()
    if len(exr.parts) > 1:
        warnings = (
            "Multipart EXR data was detected; the MVP backend does not analyze it.",
        )

    return build_file_inspection(
        path=path,
        width=width,
        height=height,
        channels=channels,
        part_count=len(exr.parts),
        is_deep=is_deep,
        warnings=warnings,
    )


class OpenEXRReader:
    """OpenEXR-backed reader implementing the EXRReader protocol."""

    def inspect(self, path: Path) -> FileInspection:
        exr_path = Path(path)
        exr = OpenEXR.File(
            str(exr_path),
            separate_channels=True,
            header_only=True,
        )
        return _inspection_from_file(exr, exr_path)

    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ) -> FrameData:
        exr_path = Path(path)
        exr = OpenEXR.File(str(exr_path), separate_channels=True)
        inspection = _inspection_from_file(exr, exr_path)
        if inspection.unsupported_reason is not None:
            return FrameData(
                path=exr_path,
                width=inspection.width,
                height=inspection.height,
                inspection=inspection,
                channels=inspection.channels,
                aovs={},
            )

        requested = set(requested_aovs) if requested_aovs is not None else None
        descriptors = {
            descriptor.name: descriptor
            for descriptor in inspection.aovs
            if requested is None or descriptor.name in requested
        }

        if requested is not None:
            missing = sorted(requested - set(descriptors))
            if missing:
                raise RuntimeError(f"Requested AOV(s) not found: {', '.join(missing)}")

        if requested is None:
            descriptors = {
                name: descriptor
                for name, descriptor in descriptors.items()
                if descriptor.category is not AOVCategory.UNKNOWN
            }

        first_part = exr.parts[0]
        aovs = {
            name: self._read_descriptor(
                first_part,
                descriptor,
                inspection.width,
                inspection.height,
            )
            for name, descriptor in descriptors.items()
        }

        return FrameData(
            path=exr_path,
            width=inspection.width,
            height=inspection.height,
            inspection=inspection,
            channels=inspection.channels,
            aovs=aovs,
        )

    def _read_channel(self, part, channel_name: str, width: int, height: int) -> np.ndarray:
        try:
            pixels = part.channels[channel_name].pixels
        except KeyError as exc:
            raise RuntimeError(f"EXR channel not found: {channel_name}") from exc
        array = np.array(pixels, dtype=np.float32, copy=True)
        if array.shape != (height, width):
            raise RuntimeError(
                f"Channel {channel_name!r} has unsupported sampled shape "
                f"{array.shape}; expected {(height, width)}."
            )
        return array

    def _read_descriptor(
        self,
        part,
        descriptor: AOVDescriptor,
        width: int,
        height: int,
    ) -> np.ndarray:
        if descriptor.category is AOVCategory.COLOR:
            channels = _ordered_channels(descriptor, ("R", "G", "B"))
            return np.stack(
                [self._read_channel(part, channel, width, height) for channel in channels],
                axis=-1,
            )

        if descriptor.category is AOVCategory.VECTOR:
            suffixes = {_suffix(channel) for channel in descriptor.channels}
            order = ("X", "Y", "Z") if {"X", "Y", "Z"}.issubset(suffixes) else ("R", "G", "B")
            channels = _ordered_channels(descriptor, order)
            return np.stack(
                [self._read_channel(part, channel, width, height) for channel in channels],
                axis=-1,
            )

        if descriptor.category in {
            AOVCategory.DEPTH,
            AOVCategory.MASK,
            AOVCategory.SCALAR,
        } and len(descriptor.channels) > 1:
            by_suffix = _channels_by_suffix(descriptor.channels)
            channel = by_suffix.get("R") or descriptor.channels[0]
            return self._read_channel(part, channel, width, height)

        if len(descriptor.channels) == 1:
            return self._read_channel(part, descriptor.channels[0], width, height)

        raise RuntimeError(f"AOV {descriptor.name!r} has unsupported channel structure.")
