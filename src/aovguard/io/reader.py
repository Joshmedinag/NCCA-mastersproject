from __future__ import annotations

from pathlib import Path
from typing import Collection, Iterable

import Imath
import numpy as np
import OpenEXR

from aovguard.core.models import AOVCategory, AOVDescriptor, FileInspection, FrameData
from aovguard.io.inspector import build_file_inspection


def _size_from_header(header) -> tuple[int, int]:
    data_window = header["dataWindow"]
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


class OpenEXRReader:
    """OpenEXR-backed reader implementing the EXRReader protocol."""

    def inspect(self, path: Path) -> FileInspection:
        exr_path = Path(path)
        exr = OpenEXR.InputFile(str(exr_path))
        try:
            header = exr.header()
            width, height = _size_from_header(header)
            channels = tuple(header["channels"].keys())
        finally:
            exr.close()

        return build_file_inspection(
            path=exr_path,
            width=width,
            height=height,
            channels=channels,
            part_count=1,
            is_deep=False,
        )

    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ) -> FrameData:
        exr_path = Path(path)
        inspection = self.inspect(exr_path)
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
                if descriptor.category is AOVCategory.COLOR
            }

        exr = OpenEXR.InputFile(str(exr_path))
        try:
            header = exr.header()
            width, height = _size_from_header(header)
            aovs = {
                name: self._read_descriptor(exr, descriptor, width, height)
                for name, descriptor in descriptors.items()
            }
        finally:
            exr.close()

        return FrameData(
            path=exr_path,
            width=inspection.width,
            height=inspection.height,
            channels=inspection.channels,
            aovs=aovs,
        )

    def _read_channel(self, exr, channel_name: str, width: int, height: int) -> np.ndarray:
        pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
        raw = exr.channel(channel_name, pixel_type)
        return np.frombuffer(raw, dtype=np.float32).reshape((height, width))

    def _read_descriptor(
        self,
        exr,
        descriptor: AOVDescriptor,
        width: int,
        height: int,
    ) -> np.ndarray:
        if descriptor.category is AOVCategory.COLOR:
            channels = _ordered_channels(descriptor, ("R", "G", "B"))
            return np.stack(
                [self._read_channel(exr, channel, width, height) for channel in channels],
                axis=-1,
            )

        if descriptor.category is AOVCategory.VECTOR:
            suffixes = {_suffix(channel) for channel in descriptor.channels}
            order = ("X", "Y", "Z") if {"X", "Y", "Z"}.issubset(suffixes) else ("R", "G", "B")
            channels = _ordered_channels(descriptor, order)
            return np.stack(
                [self._read_channel(exr, channel, width, height) for channel in channels],
                axis=-1,
            )

        if descriptor.category in {
            AOVCategory.DEPTH,
            AOVCategory.MASK,
            AOVCategory.SCALAR,
        } and len(descriptor.channels) > 1:
            by_suffix = _channels_by_suffix(descriptor.channels)
            channel = by_suffix.get("R") or descriptor.channels[0]
            return self._read_channel(exr, channel, width, height)

        if len(descriptor.channels) == 1:
            return self._read_channel(exr, descriptor.channels[0], width, height)

        raise RuntimeError(f"AOV {descriptor.name!r} has unsupported channel structure.")
