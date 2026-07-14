import json

from aovguard.analysis_core import AOVResult, Thresholds, build_report_payload, write_json
from aovguard.config import load_thresholds, merge_threshold_overrides


def test_build_report_payload_contains_metadata() -> None:
    results = [AOVResult("keyLight", "Active", 0.2, 0.1, 0.8)]
    payload = build_report_payload(results, mode="multilayer", thresholds=Thresholds(), frames_analyzed=3)

    assert payload["metadata"]["tool"] == "AOVGuard"
    assert payload["metadata"]["summary"]["Active"] == 1
    assert payload["metadata"]["frames_analyzed"] == 3
    assert payload["results"][0]["aov_name"] == "keyLight"


def test_write_json_creates_structured_report(tmp_path) -> None:
    path = tmp_path / "report.json"
    results = [AOVResult("practicalLamp", "Empty", 0.0, 0.0, 0.0)]
    write_json(results, path, mode="simple", thresholds=Thresholds())

    data = json.loads(path.read_text())
    assert data["metadata"]["summary"]["Empty"] == 1
    assert data["results"][0]["classification"] == "Empty"


def test_load_thresholds_from_toml(tmp_path) -> None:
    path = tmp_path / "aovguard.toml"
    path.write_text("[analysis]\nreview_max_ratio = 0.12\nempty_max_luminance = 0.0002\n")

    thresholds = load_thresholds(path)

    assert thresholds.review_max_ratio == 0.12
    assert thresholds.empty_max_luminance == 0.0002


def test_merge_threshold_overrides() -> None:
    thresholds = merge_threshold_overrides(Thresholds(), review_max_average=0.2)
    assert thresholds.review_max_average == 0.2
