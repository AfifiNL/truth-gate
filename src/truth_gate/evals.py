"""Eval corpus runner and gate.

Metrics (per scope: all, dev, test):
  catch_rate         share of error cases the checker fails FOR THE INJECTED REASON (a wrong
                     number must fail on a number finding, not on a stray tone or skill hit);
  false_alarm_rate   share of clean cases that fail.
The checker is deterministic, so any change in a metric is a real change: the gate fails when a
floor in gate.json is broken or when a metric moves the wrong way against baseline.json.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from truth_gate.checker import Checker
from truth_gate.facts import load_facts

EXPECTED_CHECK = {
    "wrong_number": "number",
    "out_of_context": "number",
    "invented_skill": "skill",
    "blocked_phrase": "blocked",
}


def evaluate(root: Path) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    checker = Checker(load_facts(root / "facts.yaml"))
    cases = [
        json.loads(ln) for ln in (root / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows: list[dict[str, Any]] = []
    for c in cases:
        report = checker.check(c["doc"])
        error_checks = sorted({f.check for f in report.findings if f.severity == "error"})
        ok = report.passed if c["kind"] == "clean" else EXPECTED_CHECK[c["kind"]] in error_checks
        rows.append({**c, "ok": ok, "passed": report.passed, "error_checks": error_checks})
    scores: dict[str, dict[str, float]] = {}
    for scope in ("all", "dev", "test"):
        sel = [r for r in rows if scope == "all" or r["split"] == scope]
        errs = [r for r in sel if r["kind"] != "clean"]
        clean = [r for r in sel if r["kind"] == "clean"]
        s: dict[str, float] = {
            "cases": len(sel),
            "catch_rate": round(sum(r["ok"] for r in errs) / len(errs), 3) if errs else 1.0,
            "false_alarm_rate": (
                round(sum(not r["ok"] for r in clean) / len(clean), 3) if clean else 0.0
            ),
        }
        by_kind: dict[str, list[bool]] = defaultdict(list)
        for r in errs:
            by_kind[r["kind"]].append(r["ok"])
        for kind, oks in sorted(by_kind.items()):
            s[f"catch_{kind}"] = round(sum(oks) / len(oks), 3)
        scores[scope] = s
    return scores, rows


def gate(
    scores: dict[str, dict[str, float]],
    floors: dict[str, Any],
    baseline: dict[str, dict[str, float]] | None,
) -> list[str]:
    problems: list[str] = []
    tol = float(floors.get("tolerance", 0.0))
    for scope, s in scores.items():
        if s["catch_rate"] < floors["min_catch_rate"]:
            problems.append(f"{scope}: catch_rate {s['catch_rate']} < {floors['min_catch_rate']}")
        if s["false_alarm_rate"] > floors["max_false_alarm_rate"]:
            problems.append(
                f"{scope}: false_alarm_rate {s['false_alarm_rate']} > "
                f"{floors['max_false_alarm_rate']}"
            )
        if baseline and scope in baseline:
            b = baseline[scope]
            for key, value in s.items():
                if key == "cases" or key not in b:
                    continue
                worse = value > b[key] + tol if key == "false_alarm_rate" else value < b[key] - tol
                if worse:
                    problems.append(f"{scope}: {key} regressed {b[key]} -> {value}")
    return problems


def run_eval(root: Path, split: str, update_baseline: bool, out: Path | None) -> int:
    scores, rows = evaluate(root)
    shown = scores if split == "all" else {split: scores[split]}
    for scope, s in shown.items():
        print(scope + ": " + ", ".join(f"{k} {v}" for k, v in s.items()))
    misses = [r for r in rows if not r["ok"] and (split == "all" or r["split"] == split)]
    for r in misses:
        tag = " (hard case)" if r["hard"] else ""
        print(f"  miss {r['id']} {r['split']} {r['kind']}{tag}: errors={r['error_checks']}")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_markdown(scores, misses), encoding="utf-8")
    baseline_path = root / "baseline.json"
    if update_baseline:
        baseline_path.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written to {baseline_path}; review the diff before committing")
        return 0
    floors = json.loads((root / "gate.json").read_text(encoding="utf-8"))
    baseline = (
        json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    )
    problems = gate(shown, floors, baseline)
    for p in problems:
        print("GATE FAIL " + p)
    print("gate: " + ("FAIL" if problems else "PASS"))
    return 1 if problems else 0


def _markdown(scores: dict[str, dict[str, float]], misses: list[dict[str, Any]]) -> str:
    keys = sorted({k for s in scores.values() for k in s})
    lines = ["| scope | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
    for scope, s in scores.items():
        lines.append(f"| {scope} | " + " | ".join(str(s.get(k, "")) for k in keys) + " |")
    lines += ["", "Misses:", ""]
    lines += [f"- {r['id']} ({r['split']}, {r['kind']}, hard={r['hard']})" for r in misses]
    return "\n".join(lines) + "\n"
