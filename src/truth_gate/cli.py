"""truth-gate command line.

truth-gate check DOC --facts FACTS [--json] [--strict]   exit 0 pass, 1 fail, 2 bad input
truth-gate facts FACTS                                    validate a facts file
truth-gate serve --facts FACTS                            MCP server on stdio
truth-gate eval [--split dev|test|all] [--update-baseline]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from truth_gate.checker import Checker, DocumentTooLarge
from truth_gate.facts import FactsError, load_facts


def _check(args: argparse.Namespace) -> int:
    facts = load_facts(args.facts)
    try:
        document = Path(args.document).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {args.document}: {exc.strerror}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"error: {args.document} is not valid UTF-8", file=sys.stderr)
        return 2
    try:
        report = Checker(facts).check(document)
    except DocumentTooLarge as exc:
        print(f"error: {args.document}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
    else:
        print(report.render())
    failed = not report.passed or (args.strict and report.warnings > 0)
    return 1 if failed else 0


def _facts(args: argparse.Namespace) -> int:
    facts = load_facts(args.facts)
    checker = Checker(facts)
    numbers = sum(len(f.quantities()) for f in facts.facts)
    print(
        f"OK: {len(facts.facts)} facts about {facts.subject}, {numbers} numbers, "
        f"{len(checker.vocabulary.allowed)} allowed skills, "
        f"{len(facts.blocked_phrases)} blocked phrases"
    )
    for f in facts.facts:
        labels = ", ".join(q.label() for q in f.quantities()) or "-"
        print(f"  {f.id}: numbers {labels}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    from truth_gate.mcp_server import build_server

    build_server(load_facts(args.facts)).run("stdio")
    return 0


def _eval(args: argparse.Namespace) -> int:
    from truth_gate.evals import run_eval

    return run_eval(
        root=Path(args.root),
        split=args.split,
        update_baseline=args.update_baseline,
        out=Path(args.out) if args.out else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="truth-gate", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="check a document against a facts file")
    p.add_argument("document")
    p.add_argument("--facts", required=True)
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--strict", action="store_true", help="warnings fail too")
    p.set_defaults(fn=_check)
    p = sub.add_parser("facts", help="validate a facts file and list its numbers")
    p.add_argument("facts")
    p.set_defaults(fn=_facts)
    p = sub.add_parser("serve", help="run the MCP server on stdio")
    p.add_argument("--facts", required=True)
    p.set_defaults(fn=_serve)
    p = sub.add_parser("eval", help="run the labelled eval corpus and its gate")
    p.add_argument("--root", default="evals")
    p.add_argument("--split", choices=["dev", "test", "all"], default="all")
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--out", help="write a Markdown report here")
    p.set_defaults(fn=_eval)
    args = parser.parse_args(argv)
    try:
        code: int = args.fn(args)
    except FactsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
