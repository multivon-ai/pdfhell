"""pdfhell CLI.

Four subcommands keep the surface minimal:

    pdfhell list-traps                       list available trap families
    pdfhell make --trap X --seed N [--out P] generate one case (pdf + json)
    pdfhell build --suite mini --out cases/  materialise a named suite
    pdfhell run --suite mini --model ...     evaluate a model against the suite
    pdfhell report runs/<name>.json          print summary + optional share card

Everything else (scoring, provider dispatch, audit packaging) is pulled
from :mod:`multivon_eval`. The CLI is glue.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .auditpack import build_audit_pack
from .case import HellCase
from .generators import TRAP_FAMILIES, generate_case
from .junit import report_to_junit
from .runner import parse_model_spec, run_suite
from .scorer import SuiteReport
from .suite import SUITES, build_suite


def _cmd_list_traps(args: argparse.Namespace) -> int:
    for family in TRAP_FAMILIES:
        print(family)
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    """Print the machine-readable pdfhell capability catalog as JSON.

    Same shape an agent gets via the multivon-mcp ``eval_discover`` tool —
    surfaced as a CLI command so agents that don't speak MCP can pipe
    ``pdfhell discover --json | jq ...`` to plan a run.
    """
    from .generators import GENERATORS
    catalog = {
        "package": "pdfhell",
        "version": __version__,
        "traps": [],
        "suites": [],
    }
    for trap in TRAP_FAMILIES:
        _, example_case = GENERATORS[trap](seed=1)
        catalog["traps"].append({
            "name": trap,
            "example_question": example_case.question,
            "example_expected_answer": example_case.expected_answer,
        })
    for name, spec in SUITES.items():
        catalog["suites"].append({
            "name": name,
            "version": spec.version,
            "suite_hash": spec.suite_hash,
            "total_cases": spec.total_cases,
            "trap_seeds": {trap: list(seeds) for trap, seeds in spec.traps.items()},
        })
    json.dump(catalog, sys.stdout, indent=2 if not args.compact else None)
    print()
    return 0


def _cmd_make(args: argparse.Namespace) -> int:
    try:
        pdf_bytes, case = generate_case(args.trap, args.seed)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        print(f"available trap families: {', '.join(TRAP_FAMILIES)}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{case.id}.pdf"
    json_path = out_dir / f"{case.id}.json"
    pdf_path.write_bytes(pdf_bytes)
    case.pdf_path = pdf_path.name
    case.dump_json(json_path)
    print(f"wrote {pdf_path}  ({len(pdf_bytes):,} bytes)")
    print(f"wrote {json_path}")
    print(f"expected answer: {case.expected_answer}")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    if args.suite not in SUITES:
        print(f"unknown suite {args.suite!r}; available: {', '.join(SUITES)}", file=sys.stderr)
        return 2
    spec = SUITES[args.suite]
    out_dir = Path(args.out).resolve()
    print(f"building suite {spec.name!r} ({spec.total_cases} cases) → {out_dir}")
    cases = build_suite(spec, out_dir)
    print(f"wrote {len(cases)} cases")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    # Default cases dir tracks the suite name so `--suite smoke` doesn't
    # silently run the mini suite.
    cases_dir = Path(args.cases_dir).resolve() if args.cases_dir else Path(f"./cases/{args.suite}").resolve()
    if not cases_dir.is_dir():
        if args.suite in SUITES:
            print(f"cases dir {cases_dir} not found; building {args.suite} suite first ...")
            cases_dir.mkdir(parents=True, exist_ok=True)
            build_suite(SUITES[args.suite], cases_dir)
        else:
            print(f"cases dir {cases_dir} not found and suite {args.suite!r} is unknown",
                  file=sys.stderr)
            return 2

    print(f"running {args.model} against {args.suite} suite at {cases_dir}")
    report = run_suite(
        cases_dir=cases_dir,
        model_spec=args.model,
        workers=args.workers,
        progress=not args.quiet,
        suite_name=args.suite,
    )
    out_path = Path(args.out).resolve() if args.out else _default_run_path(args.model, args.suite)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print()
    _print_report(report)
    print()
    print(f"wrote {out_path}")
    if args.junit:
        junit_path = Path(args.junit).resolve()
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        junit_path.write_text(report_to_junit(report), encoding="utf-8")
        print(f"wrote {junit_path}")
    if args.audit_pack:
        zip_path = Path(args.audit_pack).resolve()
        build_audit_pack(report, cases_dir, zip_path)
        print(f"wrote {zip_path}")
    if args.fail_threshold is not None and report.pass_rate < args.fail_threshold:
        print(
            f"\nFAIL: pass_rate {report.pass_rate:.1%} below --fail-threshold "
            f"{args.fail_threshold:.1%}"
        )
        return 1
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.run).read_text(encoding="utf-8"))
    report = SuiteReport(
        model=raw["model"],
        suite=raw["suite"],
        n=raw["n"],
        pass_rate=raw["pass_rate"],
        per_trap_pass=raw["per_trap_pass"],
        per_trap_fell_for_trap=raw["per_trap_fell_for_trap"],
        refused_rate=raw["refused_rate"],
        cases=[],  # not needed for printing the summary
    )
    _print_report(report)
    return 0


def _print_report(report: SuiteReport) -> None:
    print(f"PDF Hell {report.suite} suite — n={report.n}")
    print()
    print(f"model: {report.model}")
    print(f"pass: {sum(1 for _ in report.cases if _.correct) if report.cases else int(report.pass_rate * report.n)}/{report.n}  ({report.pass_rate:.1%})")
    print(f"refused: {report.refused_rate:.1%}")
    print()
    print("per-trap pass rate:")
    for trap, rate in sorted(report.per_trap_pass.items()):
        fell = report.per_trap_fell_for_trap.get(trap, 0.0)
        print(f"  {trap:30s}  pass={rate:.0%}  fell-for-trap={fell:.0%}")


def _default_run_path(model_spec: str, suite: str) -> Path:
    safe = model_spec.replace("/", "-").replace(":", "-")
    return Path(f"runs/{suite}-{safe}.json").resolve()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdfhell",
        description="PDF Hell — adversarial PDFs that break AI document readers.",
    )
    p.add_argument("--version", action="version", version=f"pdfhell {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    p_list = sub.add_parser("list-traps", help="list available trap families")
    p_list.set_defaults(func=_cmd_list_traps)

    p_discover = sub.add_parser(
        "discover",
        help="emit pdfhell capability catalog as JSON (for agents that don't speak MCP)",
    )
    p_discover.add_argument("--compact", action="store_true", help="single-line JSON, no indent")
    p_discover.set_defaults(func=_cmd_discover)

    p_make = sub.add_parser("make", help="generate one case (pdf + json)")
    p_make.add_argument("--trap", required=True, choices=TRAP_FAMILIES)
    p_make.add_argument("--seed", required=True, type=int)
    p_make.add_argument(
        "--out", "--output-dir",
        dest="out",
        default="./cases",
        help="output directory (default: ./cases) — alias: --output-dir",
    )
    p_make.set_defaults(func=_cmd_make)

    p_build = sub.add_parser("build", help="materialise a named suite to disk")
    p_build.add_argument("--suite", default="mini", choices=tuple(SUITES.keys()))
    p_build.add_argument(
        "--out", "--output-dir",
        dest="out",
        default="./cases/mini",
        help="output directory (default: ./cases/mini) — alias: --output-dir",
    )
    p_build.set_defaults(func=_cmd_build)

    p_run = sub.add_parser("run", help="evaluate a model against a suite")
    p_run.add_argument("--model", required=True,
                       help="provider:model, e.g. anthropic:claude-sonnet-4-6")
    p_run.add_argument("--suite", default="mini", choices=tuple(SUITES.keys()))
    p_run.add_argument(
        "--cases-dir",
        default=None,
        help="dir with materialised cases (default: ./cases/<suite>; built on demand if missing)",
    )
    p_run.add_argument("--workers", type=int, default=4)
    p_run.add_argument("--quiet", action="store_true")
    p_run.add_argument("--out", help="output JSON path (default: runs/<suite>-<model>.json)")
    p_run.add_argument(
        "--junit",
        help="also write a JUnit XML report to this path (renders in GitHub Actions / GitLab CI)",
    )
    p_run.add_argument(
        "--audit-pack",
        help=(
            "also write a complete, hash-chained audit ZIP to this path "
            "(PDFs + answer keys + run JSON + JUnit XML + SHA-256 manifest)"
        ),
    )
    p_run.add_argument(
        "--fail-threshold",
        type=float,
        help="exit nonzero if pass_rate is below this fraction (0.0–1.0); for CI gates",
    )
    p_run.set_defaults(func=_cmd_run)

    p_report = sub.add_parser("report", help="print summary from a run JSON")
    p_report.add_argument("run", help="path to runs/<suite>-<model>.json")
    p_report.set_defaults(func=_cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
