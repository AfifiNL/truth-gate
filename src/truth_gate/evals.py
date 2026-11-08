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


def evaluate_llm(
    root: Path, splits: tuple[str, ...] = ("dev", "heldout")
) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    """Score the model-written set (evals/llm): documents a live model wrote from facts.yaml,
    labelled by a person before the checker was run on them. Dropped documents (the model did
    not follow its instruction) are not scored."""
    checker = Checker(load_facts(root / "facts.yaml"))
    lines = (root / "llm" / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    docs = {d["id"]: d for d in map(json.loads, lines) if "id" in d}
    labels = [
        json.loads(x) for x in (root / "llm" / "labels.jsonl").read_text("utf-8").splitlines()
    ]
    rows: list[dict[str, Any]] = []
    for lab in labels:
        doc = docs[lab["id"]]
        if lab["label"] == "dropped" or doc["split"] not in splits:
            continue
        report = checker.check(doc["document"])
        error_checks = sorted({f.check for f in report.findings if f.severity == "error"})
        ok = report.passed if lab["label"] == "pass" else lab["expected_check"] in error_checks
        rows.append(
            {
                "id": lab["id"],
                "split": doc["split"],
                "kind": "clean" if lab["label"] == "pass" else lab["requested"],
                "hard": False,
                "ok": ok,
                "passed": report.passed,
                "error_checks": error_checks,
            }
        )
    scores: dict[str, dict[str, float]] = {}
    for scope in ("all", *splits):
        sel = [r for r in rows if scope == "all" or r["split"] == scope]
        scores[scope] = _rates(sel)
    return scores, rows


def _rates(sel: list[dict[str, Any]]) -> dict[str, float]:
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
    return s


def gate(
    scores: dict[str, dict[str, float]],
    floors: dict[str, Any],
    baseline: dict[str, Any] | None,
    rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Problems that fail the gate (an empty list passes).

    Per scope: a floor broken, the number of cases changed (the corpus changed: re-record the
    baseline in a reviewed diff), or a metric worse than the baseline. Per document (when the
    baseline has `outcomes`): a case that was handled correctly is no longer, or a case the
    baseline does not know. An improvement passes until the baseline is re-recorded.
    """
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
            if b.get("cases") != s["cases"]:
                problems.append(f"{scope}: cases changed {b.get('cases')} -> {s['cases']}")
            for key, value in s.items():
                if key == "cases" or key not in b:
                    continue
                worse = value > b[key] + tol if key == "false_alarm_rate" else value < b[key] - tol
                if worse:
                    problems.append(f"{scope}: {key} regressed {b[key]} -> {value}")
    if baseline and rows is not None and "outcomes" in baseline:
        before: dict[str, bool] = baseline["outcomes"]
        for r in rows:
            if r["id"] not in before:
                problems.append(f"{r['id']}: not in the baseline (re-record it)")
            elif before[r["id"]] and not r["ok"]:
                problems.append(f"{r['id']}: handled correctly in the baseline, not any more")
    return problems


LLM_SPLITS = {"dev": ("dev",), "test": ("heldout",), "all": ("dev", "heldout")}


def run_eval(root: Path, split: str, update_baseline: bool, out: Path | None) -> int:
    """Both sets: the hand-built corpus (floors + baseline) and, when present, the model-written
    set in root/llm (baseline only: its results were first seen after the checker was frozen,
    so no floor was chosen from them). `split` selects dev, test (the model-written set's
    `heldout`) or all; a baseline update only rewrites the selected scopes and cases."""
    problems: list[str] = []
    print("hand-built set (evals/cases.jsonl)")
    scores, rows = evaluate(root)
    shown = scores if split == "all" else {split: scores[split]}
    rows = [r for r in rows if split == "all" or r["split"] == split]
    misses = _print(shown, rows)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_markdown(scores, misses), encoding="utf-8")
    problems += _gate_or_record(root, shown, rows, update_baseline, "")
    if (root / "llm" / "labels.jsonl").exists():
        splits = LLM_SPLITS[split]
        print(f"model-written set (evals/llm; {', '.join(splits)})")
        llm_scores, llm_rows = evaluate_llm(root, splits)
        llm_shown = llm_scores if split == "all" else {splits[0]: llm_scores[splits[0]]}
        _print(llm_shown, llm_rows)
        problems += _gate_or_record(root / "llm", llm_shown, llm_rows, update_baseline, "llm ")
    if update_baseline:
        return 0
    for p in problems:
        print("GATE FAIL " + p)
    print("gate: " + ("FAIL" if problems else "PASS"))
    return 1 if problems else 0


def _print(shown: dict[str, dict[str, float]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for scope, s in shown.items():
        print("  " + scope + ": " + ", ".join(f"{k} {v}" for k, v in s.items()))
    misses = [r for r in rows if not r["ok"]]
    for r in misses:
        tag = " (hard case)" if r["hard"] else ""
        print(f"    miss {r['id']} {r['split']} {r['kind']}{tag}: errors={r['error_checks']}")
    return misses


def _gate_or_record(
    where: Path,
    shown: dict[str, dict[str, float]],
    rows: list[dict[str, Any]],
    update_baseline: bool,
    prefix: str,
) -> list[str]:
    baseline_path = where / "baseline.json"
    baseline: dict[str, Any] = (
        json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    )
    if update_baseline:
        baseline.update(shown)
        baseline.setdefault("outcomes", {}).update({r["id"]: r["ok"] for r in rows})
        baseline["outcomes"] = dict(sorted(baseline["outcomes"].items()))
        baseline_path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(f"  baseline updated ({', '.join(shown)}) in {baseline_path}; review the diff")
        return []
    floors = json.loads((where / "gate.json").read_text(encoding="utf-8"))
    return [prefix + p for p in gate(shown, floors, baseline or None, rows)]


def _markdown(scores: dict[str, dict[str, float]], misses: list[dict[str, Any]]) -> str:
    keys = sorted({k for s in scores.values() for k in s})
    lines = ["| scope | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
    for scope, s in scores.items():
        lines.append(f"| {scope} | " + " | ".join(str(s.get(k, "")) for k in keys) + " |")
    lines += ["", "Misses:", ""]
    lines += [f"- {r['id']} ({r['split']}, {r['kind']}, hard={r['hard']})" for r in misses]
    return "\n".join(lines) + "\n"
