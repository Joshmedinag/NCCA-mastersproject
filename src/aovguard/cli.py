from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from aovguard.analysis_core import AOVResult, Thresholds, write_csv, write_json
from aovguard.config import load_thresholds, merge_threshold_overrides
from aovguard.core.analysis import analyze as analyze_backend
from aovguard.core.luminance import LuminanceWeights, REC601, REC709
from aovguard.core.models import AnalysisOptions, AnalysisReport, FileInspection
from aovguard.io.reader import OpenEXRReader
from aovguard.simple import analyze_simple
from aovguard.multilayer import analyze_multilayer, inspect_exr
from aovguard.reports.json_report import write_analysis_json
from aovguard.reports.html_report import write_analysis_html
from aovguard.rules.builtin import default_rule_definitions
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.loader import load_rule_preset
from aovguard.discovery.frame_discovery import discover_frames
from aovguard.sequence.sequence_checker import check_sequences, format_frame_ranges


def _print_results(results: list[AOVResult], input_folder: Path | None = None, total_frames: int | None = None) -> None:
    if input_folder is not None:
        print(f"Input folder: {input_folder.resolve()}")
    if total_frames is not None:
        print(f"Frames found: {total_frames}")
    print(f"AOVs analyzed: {len(results)}")
    print("-" * 80)
    for result in results:
        print(
            f"{result.aov_name:20} | {result.classification:18} | "
            f"ratio={result.non_black_ratio:.5f} | "
            f"avg={result.avg_luminance:.6f} | "
            f"max={result.max_luminance:.6f}"
        )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", dest="json_path", default=None, help="Write a structured JSON report.")
    parser.add_argument("--csv", dest="csv_path", default=None, help="Write a spreadsheet-friendly CSV report.")


def _add_threshold_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="Optional .toml or .json config file with analysis thresholds.")
    parser.add_argument("--empty-max-luminance", type=float, default=None)
    parser.add_argument("--empty-max-average", type=float, default=None)
    parser.add_argument("--nearly-empty-max-ratio", type=float, default=None)
    parser.add_argument("--nearly-empty-max-average", type=float, default=None)
    parser.add_argument("--review-max-ratio", type=float, default=None)
    parser.add_argument("--review-max-average", type=float, default=None)


def _add_backend_analysis_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", dest="json_path", default=None, help="Write the canonical JSON report.")
    parser.add_argument("--html", dest="html_path", default=None, help="Write a readable HTML report.")
    parser.add_argument("--preset", default=None, help="Preset name to record in report metadata.")
    parser.add_argument(
        "--luminance-model",
        choices=("rec709", "rec601"),
        default="rec709",
        help="Built-in luminance model for color AOV metrics.",
    )
    parser.add_argument(
        "--luminance-weights",
        nargs=3,
        type=float,
        metavar=("R", "G", "B"),
        default=None,
        help="Custom RGB luminance weights. Overrides --luminance-model.",
    )
    parser.add_argument("--non-black-threshold", type=float, default=1e-5)
    parser.add_argument(
        "--rules-config",
        default=None,
        help="Optional .toml or .json preset containing validation rules.",
    )


def _thresholds_from_args(args: argparse.Namespace) -> Thresholds:
    base = load_thresholds(getattr(args, "config", None))
    return merge_threshold_overrides(
        base,
        empty_max_luminance=getattr(args, "empty_max_luminance", None),
        empty_max_average=getattr(args, "empty_max_average", None),
        nearly_empty_max_ratio=getattr(args, "nearly_empty_max_ratio", None),
        nearly_empty_max_average=getattr(args, "nearly_empty_max_average", None),
        review_max_ratio=getattr(args, "review_max_ratio", None),
        review_max_average=getattr(args, "review_max_average", None),
    )


def _count_simple_frames(folder: Path) -> int:
    direct = len(list(folder.glob("*.exr")))
    nested = len(list(folder.glob("*/*.exr")))
    return direct if direct else nested


def _count_multilayer_frames(folder: Path) -> int:
    return len(list(folder.glob("*.exr")))


def _options_from_backend_args(args: argparse.Namespace) -> AnalysisOptions:
    if args.luminance_weights is not None:
        weights = LuminanceWeights.from_values(args.luminance_weights)
    elif args.luminance_model == "rec601":
        weights = REC601
    else:
        weights = REC709

    return AnalysisOptions(
        preset_name=args.preset,
        luminance_weights=(weights.r, weights.g, weights.b),
        non_black_threshold=args.non_black_threshold,
    )


def _rules_from_backend_args(
    args: argparse.Namespace,
    options: AnalysisOptions,
) -> tuple[AnalysisOptions, tuple[RuleDefinition, ...]]:
    if args.rules_config:
        preset = load_rule_preset(args.rules_config)
        definitions = preset.rules
        preset_name = args.preset or preset.name
    else:
        definitions = default_rule_definitions()
        preset_name = args.preset

    enabled_rules = tuple(definition.id for definition in definitions if definition.enabled)
    return (
        replace(
            options,
            preset_name=preset_name,
            enabled_rules=enabled_rules,
        ),
        definitions,
    )


def _print_backend_report(report: AnalysisReport) -> None:
    print(f"Input source: {Path(report.source).resolve()}")
    print(f"Frames discovered: {report.discovered_frame_count}")
    print(f"Frames processed: {report.frame_count}")
    print(f"Frames failed: {report.failed_frame_count}")
    print(f"AOVs analyzed: {len(report.metrics_by_aov)}")
    _print_sequence_check(report.sequence_check)
    if report.warnings:
        print("Warnings:")
        for warning in report.warnings:
            print(f"  - {warning}")
    print("-" * 80)
    for name, metrics in report.metrics_by_aov.items():
        print(
            f"{name:20} | "
            f"ratio={metrics.non_black_ratio:.5f} | "
            f"avg={metrics.avg_luminance:.6f} | "
            f"max={metrics.max_luminance:.6f} | "
            f"nan={metrics.nan_count} | "
            f"+inf={metrics.posinf_count} | "
            f"-inf={metrics.neginf_count}"
        )
    if report.findings:
        print("")
        print("Findings:")
        for finding in report.findings:
            target = finding.aov or finding.channel or finding.file or report.source
            print(f"  [{finding.severity.value}] {finding.rule_id}: {target} - {finding.message}")


def _print_sequence_check(result) -> None:
    print(f"Sequences detected: {len(result.sequences)}")
    for sequence in result.sequences:
        frame_range = (
            f"{sequence.start_frame}-{sequence.end_frame}"
            if sequence.start_frame != sequence.end_frame
            else str(sequence.start_frame)
        )
        missing = format_frame_ranges(sequence.missing_ranges) or "none"
        duplicates = ", ".join(map(str, sequence.duplicate_frames)) or "none"
        print(
            f"  {sequence.pattern} | range={frame_range} | present={sequence.frame_count} | "
            f"missing={missing} | duplicates={duplicates}"
        )
    if result.unnumbered_files:
        print(f"Unnumbered EXRs: {len(result.unnumbered_files)}")


def _print_structure(inspection: FileInspection) -> None:
    print(f"EXR file: {Path(inspection.path).resolve()}")
    print(f"Size: {inspection.width}x{inspection.height}")
    print(f"Parts: {inspection.part_count}")
    print(f"Deep: {inspection.is_deep}")
    print("")
    print("Channels:")
    for channel in inspection.channels:
        print(f"  - {channel}")
    print("")
    print("Detected AOVs:")
    for aov in inspection.aovs:
        channel_list = ", ".join(aov.channels)
        print(f"  - {aov.name}: {aov.category.value} ({aov.category_confidence}) [{channel_list}]")
    if inspection.warnings:
        print("")
        print("Warnings:")
        for warning in inspection.warnings:
            print(f"  - {warning}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="aovguard",
        description="Validate EXR light AOVs and report empty, near-empty, or review-worthy passes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="Analyze EXR files using automatic structure inspection.")
    p.add_argument("source")
    _add_backend_analysis_args(p)

    p = sub.add_parser("inspect-structure", help="Inspect EXR structure using the new backend inspector.")
    p.add_argument("path")

    p = sub.add_parser("check-sequence", help="Check EXR filename sequences without decoding pixels.")
    p.add_argument("source")

    p = sub.add_parser("analyze-simple", help="Analyze simple RGB/RGBA EXR files in one folder.")
    p.add_argument("input_folder")
    _add_output_args(p)
    _add_threshold_args(p)

    p = sub.add_parser("inspect", help="List channels and RGB AOV groups in one EXR file.")
    p.add_argument("path")

    p = sub.add_parser("analyze-multilayer", help="Analyze multilayer EXR files in one folder.")
    p.add_argument("input_folder")
    _add_output_args(p)
    _add_threshold_args(p)

    args = parser.parse_args(argv)

    if args.command == "analyze":
        reader = OpenEXRReader()
        try:
            options = _options_from_backend_args(args)
            options, rule_definitions = _rules_from_backend_args(args, options)
            report = analyze_backend(
                Path(args.source),
                options,
                reader,
                rule_definitions=rule_definitions,
            )
        except Exception as exc:
            parser.exit(1, f"aovguard analyze: error: {exc}\n")
        _print_backend_report(report)
        if args.json_path:
            write_analysis_json(report, args.json_path, options=options)
            print(f"JSON report written to: {args.json_path}")
        if args.html_path:
            write_analysis_html(report, args.html_path, options=options)
            print(f"HTML report written to: {args.html_path}")
        return

    if args.command == "inspect-structure":
        reader = OpenEXRReader()
        try:
            inspection = reader.inspect(Path(args.path))
        except Exception as exc:
            parser.exit(1, f"aovguard inspect-structure: error: {exc}\n")
        _print_structure(inspection)
        return

    if args.command == "check-sequence":
        try:
            discovery = discover_frames(Path(args.source))
            if not discovery.frames:
                raise FileNotFoundError(f"No EXR files found in {discovery.source}")
            result = check_sequences(discovery.frames, source=discovery.source)
        except Exception as exc:
            parser.exit(1, f"aovguard check-sequence: error: {exc}\n")
        _print_sequence_check(result)
        for warning in discovery.warnings + result.warnings:
            print(f"Warning: {warning}")
        return

    if args.command == "analyze-simple":
        folder = Path(args.input_folder)
        thresholds = _thresholds_from_args(args)
        results = analyze_simple(folder, thresholds=thresholds)
        total_frames = _count_simple_frames(folder)
        _print_results(results, input_folder=folder, total_frames=total_frames)
        if args.json_path:
            write_json(
                results,
                args.json_path,
                input_folder=folder,
                mode="simple",
                thresholds=thresholds,
                frames_analyzed=total_frames,
            )
            print(f"JSON report written to: {args.json_path}")
        if args.csv_path:
            write_csv(results, args.csv_path)
            print(f"CSV report written to: {args.csv_path}")
        return

    if args.command == "inspect":
        print(inspect_exr(args.path))
        return

    if args.command == "analyze-multilayer":
        folder = Path(args.input_folder)
        thresholds = _thresholds_from_args(args)
        total_frames = _count_multilayer_frames(folder)
        results = analyze_multilayer(folder, thresholds=thresholds)
        _print_results(results, input_folder=folder, total_frames=total_frames)
        if args.json_path:
            write_json(
                results,
                args.json_path,
                input_folder=folder,
                mode="multilayer",
                thresholds=thresholds,
                frames_analyzed=total_frames,
            )
            print(f"JSON report written to: {args.json_path}")
        if args.csv_path:
            write_csv(results, args.csv_path)
            print(f"CSV report written to: {args.csv_path}")
        return
