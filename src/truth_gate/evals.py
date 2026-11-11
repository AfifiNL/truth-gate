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

from truth_gate.brand import load_brand
from truth_gate.checker import Checker
from truth_gate.facts import load_facts
from truth_gate.pair import PairChecker

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


# The rule a planted pair error must be caught by (pair corpus and localisation set).
EXPECTED_RULE = {
    "changed_number": "number",
    "source_format": "number",
    "dropped_number": "number",
    "added_number": "number",
    "percent_lost": "number",
    "changed_meaning": "number",
    "swapped_numbers": "number",
    "translated_name": "name",
    "missing_term": "term",
    "forbidden": "forbidden",
    "missing_line": "required-line",
    "address": "address",
}


def evaluate_pairs(
    root: Path, splits: tuple[str, ...] = ("dev", "test")
) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    """Score the hand-built pair corpus (root/pairs): an English source, a Dutch or Arabic
    target, clean or with one planted error."""
    brand = load_brand(root / "pairs" / "brand.yaml")
    checkers = {name: PairChecker(brand, name) for name in brand.markets}
    lines = (root / "pairs" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for c in map(json.loads, lines):
        if c["split"] not in splits:
            continue
        report = checkers[c["market"]].check(c["source"], c["target"])
        rules = sorted({f.rule for f in report.findings if f.severity == "error"})
        ok = report.passed if c["kind"] == "clean" else EXPECTED_RULE[c["kind"]] in rules
        rows.append(
            {
                "id": c["id"],
                "split": c["split"],
                "kind": c["kind"],
                "hard": c["hard"],
                "market": c["market"],
                "ok": ok,
                "passed": report.passed,
                "error_checks": rules,
            }
        )
    scores = {
        scope: _rates([r for r in rows if scope == "all" or r["split"] == scope])
        for scope in ("all", *splits)
    }
    return scores, rows


L10N_RULES = ("number", "name", "term", "forbidden", "required-line", "address")


def evaluate_l10n(
    root: Path, splits: tuple[str, ...] = ("dev", "test")
) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    """Score the localisation experiment (root/l10n): texts a live model localised, labelled
    by reading before the checker was run on them.

    Per document the checker's error rules are compared with the labelled rules. `ok` means
    they are the same set. `catch_rate` is the share of documents with a labelled violation
    where every labelled rule was reported; `false_alarm_rate` the share of all documents
    where a rule was reported that the label does not have. Per rule: `catch_<rule>` over the
    documents labelled with it, `extra_<rule>` the number of documents where it was reported
    without a label. Documents whose text no longer matches its label's hash are an error.
    """
    import hashlib

    brand = load_brand(root / "l10n" / "brand.yaml")
    checkers = {name: PairChecker(brand, name) for name in brand.markets}
    sources = {
        s["id"]: s["text"]
        for s in map(json.loads, (root / "l10n" / "sources.jsonl").read_text("utf-8").splitlines())
    }
    lines = (root / "l10n" / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    docs = {d["id"]: d for d in map(json.loads, lines) if "id" in d}
    rows: list[dict[str, Any]] = []
    for lab in map(json.loads, (root / "l10n" / "labels.jsonl").read_text("utf-8").splitlines()):
        doc = docs[lab["id"]]
        if doc["split"] not in splits:
            continue
        if hashlib.sha256(doc["target"].encode("utf-8")).hexdigest() != lab["sha256"]:
            raise ValueError(f"{lab['id']}: the text changed after it was labelled")
        report = checkers[doc["market"]].check(sources[doc["source_id"]], doc["target"])
        found = {f.rule for f in report.findings if f.severity == "error"} & set(L10N_RULES)
        labelled = set(lab["violations"])
        rows.append(
            {
                "id": lab["id"],
                "split": doc["split"],
                "market": doc["market"],
                "condition": doc["condition"],
                "kind": "violation" if labelled else "clean",
                "hard": False,
                "ok": found == labelled,
                "passed": report.passed,
                "labelled": sorted(labelled),
                "error_checks": sorted(found),
                "missed": sorted(labelled - found),
                "extra": sorted(found - labelled),
            }
        )
    scores = {
        scope: _l10n_rates([r for r in rows if scope == "all" or r["split"] == scope])
        for scope in ("all", *splits)
    }
    return scores, rows


def _l10n_rates(sel: list[dict[str, Any]]) -> dict[str, float]:
    bad = [r for r in sel if r["labelled"]]
    s: dict[str, float] = {
        "cases": len(sel),
        "agreement": round(sum(r["ok"] for r in sel) / len(sel), 3) if sel else 1.0,
        "catch_rate": round(sum(not r["missed"] for r in bad) / len(bad), 3) if bad else 1.0,
        "false_alarm_rate": round(sum(bool(r["extra"]) for r in sel) / len(sel), 3) if sel else 0.0,
    }
    for rule in L10N_RULES:
        with_rule = [r for r in sel if rule in r["labelled"]]
        if with_rule:
            s[f"catch_{rule}"] = round(
                sum(rule not in r["missed"] for r in with_rule) / len(with_rule), 3
            )
        s[f"extra_{rule}"] = sum(rule in r["extra"] for r in sel)
    return s


def l10n_violation_rates(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """From the labels alone: per market and prompt condition, the share of documents that
    break each rule, and the share that break any rule other than the required line."""
    out: dict[str, dict[str, float]] = {}
    for market in sorted({r["market"] for r in rows}):
        for condition in ("bare", "rules"):
            sel = [r for r in rows if r["market"] == market and r["condition"] == condition]
            if not sel:
                continue
            rates: dict[str, float] = {"documents": len(sel)}
            for rule in L10N_RULES:
                rates[rule] = round(sum(rule in r["labelled"] for r in sel) / len(sel), 3)
            rates["any_but_required_line"] = round(
                sum(bool(set(r["labelled"]) - {"required-line"}) for r in sel) / len(sel), 3
            )
            out[f"{market} {condition}"] = rates
    return out


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
    if (root / "pairs" / "cases.jsonl").exists():
        pair_splits = ("dev", "test") if split == "all" else (split,)
        print(f"hand-built pair set (evals/pairs; {', '.join(pair_splits)})")
        pair_scores, pair_rows = evaluate_pairs(root, pair_splits)
        pair_shown = pair_scores if split == "all" else {split: pair_scores[split]}
        _print(pair_shown, pair_rows)
        problems += _gate_or_record(
            root / "pairs", pair_shown, pair_rows, update_baseline, "pairs "
        )
    if (root / "l10n" / "labels.jsonl").exists():
        l10n_splits = ("dev", "test") if split == "all" else (split,)
        print(f"localisation experiment (evals/l10n; {', '.join(l10n_splits)})")
        l10n_scores, l10n_rows = evaluate_l10n(root, l10n_splits)
        l10n_shown = {k: v for k, v in l10n_scores.items() if v["cases"]}
        if split != "all":
            l10n_shown = {split: l10n_scores[split]} if l10n_scores[split]["cases"] else {}
        for scope, sc in l10n_shown.items():
            print("  " + scope + ": " + ", ".join(f"{k} {v}" for k, v in sc.items()))
        for r in l10n_rows:
            if not r["ok"]:
                print(
                    f"    differs {r['id']} {r['split']}: missed={r['missed']} extra={r['extra']}"
                )
        for key, rates in l10n_violation_rates(l10n_rows).items():
            print(f"  labelled {key}: " + ", ".join(f"{k} {v}" for k, v in rates.items()))
        problems += _gate_or_record(root / "l10n", l10n_shown, l10n_rows, update_baseline, "l10n ")
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
