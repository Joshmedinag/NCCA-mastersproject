from pathlib import Path
from types import SimpleNamespace

import Imath
import numpy as np
import OpenEXR
import pytest

from aovguard.core.analysis import analyze
from aovguard.core.models import AOVCategory, AOVDescriptor, AnalysisOptions
from aovguard.io.reader import (
    OpenEXRReader,
    _inspection_from_file,
    _ordered_channels,
    _size_from_header,
)


def _channel(value: float, width: int, height: int) -> bytes:
    return (np.ones((height, width), dtype=np.float32) * value).tobytes()


def _write_exr(path: Path, width: int, height: int, channels: dict[str, float]) -> None:
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(width, height)
    header["channels"] = {name: Imath.Channel(pixel_type) for name in channels}
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {
                name: _channel(value, width, height)
                for name, value in channels.items()
            }
        )
    finally:
        output.close()


def _multichannel_exr(path: Path) -> Path:
    _write_exr(
        path,
        2,
        2,
        {
            "R": 1.0,
            "G": 2.0,
            "B": 3.0,
            "diffuse.R": 4.0,
            "diffuse.G": 5.0,
            "diffuse.B": 6.0,
            "Z": 10.0,
            "N.X": 0.0,
            "N.Y": 1.0,
            "N.Z": 0.0,
        },
    )
    return path


def _arnold_technical_exr(path: Path) -> Path:
    _write_exr(
        path,
        2,
        2,
        {
            "R": 1.0,
            "G": 2.0,
            "B": 3.0,
            "N.R": 0.0,
            "N.G": 1.0,
            "N.B": 0.0,
            "P.R": 4.0,
            "P.G": 5.0,
            "P.B": 6.0,
            "Z.R": 10.0,
            "Z.G": 10.0,
            "Z.B": 10.0,
        },
    )
    return path


def _multipart_exr(path: Path) -> Path:
    pixels = np.ones((2, 2), dtype=np.float32)
    parts = [
        OpenEXR.Part(
            {},
            {"R": pixels, "G": pixels, "B": pixels},
            "beauty",
        ),
        OpenEXR.Part(
            {},
            {"R": pixels * 2, "G": pixels * 2, "B": pixels * 2},
            "secondary",
        ),
    ]
    OpenEXR.File(parts).write(str(path))
    return path


def test_openexr_reader_inspects_channels_and_aovs(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    inspection = reader.inspect(path)
    by_name = {aov.name: aov for aov in inspection.aovs}

    assert inspection.width == 2
    assert inspection.height == 2
    assert {"R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B", "Z"}.issubset(
        set(inspection.channels)
    )
    assert by_name["beauty"].category is AOVCategory.COLOR
    assert by_name["diffuse"].category is AOVCategory.COLOR
    assert by_name["Z"].category is AOVCategory.DEPTH
    assert by_name["N"].category is AOVCategory.VECTOR


def test_openexr_reader_reads_color_aovs_as_rgb_by_default(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    frame = reader.read_frame(path)

    assert set(frame.aovs) == {"beauty", "diffuse"}
    np.testing.assert_allclose(frame.aovs["beauty"][0, 0, :], [1.0, 2.0, 3.0])
    np.testing.assert_allclose(frame.aovs["diffuse"][0, 0, :], [4.0, 5.0, 6.0])


def test_openexr_reader_reads_scalar_and_vector_aovs_when_requested(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    frame = reader.read_frame(path, requested_aovs=["Z", "N"])

    assert set(frame.aovs) == {"Z", "N"}
    assert frame.aovs["Z"].shape == (2, 2)
    np.testing.assert_allclose(frame.aovs["Z"], np.ones((2, 2), dtype=np.float32) * 10)
    assert frame.aovs["N"].shape == (2, 2, 3)
    np.testing.assert_allclose(frame.aovs["N"][0, 0, :], [0.0, 1.0, 0.0])


def test_openexr_reader_reports_missing_requested_aov(tmp_path: Path) -> None:
    path = _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    with pytest.raises(RuntimeError, match="Requested AOV"):
        reader.read_frame(path, requested_aovs=["not_present"])


def test_openexr_reader_excludes_arnold_technical_aovs_by_default(
    tmp_path: Path,
) -> None:
    path = _arnold_technical_exr(tmp_path / "arnold.1001.exr")
    reader = OpenEXRReader()

    inspection = reader.inspect(path)
    frame = reader.read_frame(path)
    by_name = {aov.name: aov for aov in inspection.aovs}

    assert by_name["N"].category is AOVCategory.VECTOR
    assert by_name["P"].category is AOVCategory.VECTOR
    assert by_name["Z"].category is AOVCategory.DEPTH
    assert set(frame.aovs) == {"beauty"}


def test_openexr_reader_reads_arnold_technical_aovs_when_requested(
    tmp_path: Path,
) -> None:
    path = _arnold_technical_exr(tmp_path / "arnold.1001.exr")
    reader = OpenEXRReader()

    frame = reader.read_frame(path, requested_aovs=["N", "P", "Z"])

    np.testing.assert_allclose(frame.aovs["N"][0, 0, :], [0.0, 1.0, 0.0])
    np.testing.assert_allclose(frame.aovs["P"][0, 0, :], [4.0, 5.0, 6.0])
    assert frame.aovs["Z"].shape == (2, 2)
    np.testing.assert_allclose(frame.aovs["Z"], 10.0)


def test_core_analyze_can_use_openexr_reader(tmp_path: Path) -> None:
    _multichannel_exr(tmp_path / "shot.1001.exr")
    reader = OpenEXRReader()

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert report.frame_count == 1
    assert set(report.metrics_by_aov) == {"beauty", "diffuse"}
    assert report.metrics_by_aov["beauty"].pixel_count == 4
    assert report.metrics_by_aov["beauty"].avg_luminance == pytest.approx(1.8596)
    assert report.metrics_by_aov["diffuse"].avg_luminance == pytest.approx(4.8596)
    assert report.findings == ()


def test_core_analysis_opens_each_frame_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _multichannel_exr(tmp_path / "shot.1001.exr")
    original_file = OpenEXR.File
    opened: list[str] = []

    def counting_file(*args, **kwargs):
        opened.append(str(args[0]))
        return original_file(*args, **kwargs)

    monkeypatch.setattr(OpenEXR, "File", counting_file)

    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert report.frame_count == 1
    assert len(opened) == 1


def test_openexr_reader_detects_multipart_structure(tmp_path: Path) -> None:
    path = _multipart_exr(tmp_path / "multipart.exr")
    reader = OpenEXRReader()

    inspection = reader.inspect(path)
    frame = reader.read_frame(path)

    assert inspection.part_count == 2
    assert not inspection.is_deep
    assert inspection.unsupported_reason is not None
    assert frame.inspection.part_count == 2
    assert frame.aovs == {}


def test_reader_validates_backend_metadata_and_channel_layout() -> None:
    data_window = SimpleNamespace(
        min=SimpleNamespace(x=2, y=3),
        max=SimpleNamespace(x=5, y=7),
    )
    assert _size_from_header({"dataWindow": data_window}) == (4, 5)

    incomplete = AOVDescriptor(
        "diffuse",
        ("diffuse.R", "diffuse.G"),
        AOVCategory.COLOR,
    )
    with pytest.raises(RuntimeError, match="missing channel suffix"):
        _ordered_channels(incomplete, ("R", "G", "B"))

    with pytest.raises(RuntimeError, match="no image parts"):
        _inspection_from_file(SimpleNamespace(parts=[]), Path("empty.exr"))


def test_reader_reports_missing_malformed_and_unsupported_channel_data() -> None:
    reader = OpenEXRReader()
    missing_part = SimpleNamespace(channels={})
    with pytest.raises(RuntimeError, match="channel not found"):
        reader._read_channel(missing_part, "R", 2, 2)

    malformed_part = SimpleNamespace(
        channels={"R": SimpleNamespace(pixels=np.ones((1, 4), dtype=np.float32))}
    )
    with pytest.raises(RuntimeError, match="unsupported sampled shape"):
        reader._read_channel(malformed_part, "R", 2, 2)

    unsupported = AOVDescriptor(
        "custom",
        ("custom.foo", "custom.bar"),
        AOVCategory.UNKNOWN,
    )
    with pytest.raises(RuntimeError, match="unsupported channel structure"):
        reader._read_descriptor(missing_part, unsupported, 2, 2)
