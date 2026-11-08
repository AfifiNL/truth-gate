"""Build evals/cases.jsonl from hand-written sentences (deterministic; no model involved).

Each case is three sentences: two clean filler sentences and one target sentence that is either
clean or carries one injected error. `hard` marks cases written to show a known weakness; the
checker is expected to miss them, and the README reports them as misses.

    python evals/build_cases.py          # rewrite evals/cases.jsonl
    python evals/build_cases.py --check  # exit 1 if the committed file is stale
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

CLEAN = [
    "Jordan managed a support engineering team of nine people at ExampleParcel Co.",
    "From 2017 to 2021 Jordan led the support engineering team at ExampleParcel Co.",
    "Cut the average first-response time on support tickets from 26 hours to 4 hours.",
    "Average first response to support tickets dropped to 4 hours, from 26.",
    "Customer satisfaction rose from 81% to 92% in 18 months.",
    "Automated 35% of incoming ticket routing using Python and Zapier.",
    "About 35% of ticket routing now runs automatically, built in Python.",
    "Supported a product line with $3.5 million in annual revenue at ExampleSoft Ltd.",
    "Worked on a $3.5m-a-year product line at ExampleSoft Ltd.",
    "Completed a Scrum Master certification in 2020.",
    "BA in Economics from the University of Sampleton (2014).",
    "Wrote 60 help-centre articles, cutting repeat questions by 22%.",
    "Sixty help-centre articles later, repeat questions were down 22%.",
    "Tracks support work in Jira and reports in Looker with SQL.",
]

TARGETS: list[tuple[str, bool, str]] = [
    # (kind, hard, sentence)
    ("clean", False, "1. Managed a support engineering team of 9 people at ExampleParcel Co."),
    (
        "clean",
        False,
        "The routing rules are in `rules-v2.yaml`; see https://example.com/runbook/2019/7.",
    ),
    ("clean", False, "Revenue of the product line: USD 3,500,000 a year at ExampleSoft Ltd."),
    ("clean", True, "Lifted CSAT to 92%, up from 81%."),
    (
        "wrong_number",
        False,
        "Managed a support engineering team of 11 people at ExampleParcel Co.",
    ),
    ("wrong_number", False, "Cut first-response time on support tickets from 26 hours to 3 hours."),
    ("wrong_number", False, "Customer satisfaction rose from 81% to 94% in 18 months."),
    ("wrong_number", False, "Automated 40% of incoming ticket routing using Python and Zapier."),
    ("wrong_number", False, "Supported a product line with $4.5 million in annual revenue."),
    ("wrong_number", False, "BA in Economics from the University of Sampleton (2013)."),
    ("out_of_context", False, "Speaks 4 languages fluently."),
    ("out_of_context", False, "Holds 22% of the regional market for parcel software."),
    ("out_of_context", False, "Has run 18 marathons."),
    ("out_of_context", False, "Grew the company newsletter to 60 subscribers."),
    ("out_of_context", False, "Hired 9 contractors for the warehouse project."),
    ("out_of_context", True, "Answered 26 support tickets per day."),
    ("out_of_context", True, "Raised customer satisfaction across 18 product lines."),
    ("invented_skill", False, "Automated ticket routing with Python and Kafka."),
    ("invented_skill", False, "Built the support dashboards in Tableau."),
    ("invented_skill", False, "Deployed the routing service on Kubernetes."),
    ("invented_skill", False, "Wrote nightly ETL jobs in Apache Spark."),
    ("invented_skill", False, "Connected Zapier, Python and Salesforce for routing."),
    ("invented_skill", True, "Built a small react front end for the help centre."),
    ("blocked_phrase", False, "Runs the best in the industry support desk."),
    ("blocked_phrase", False, "We guarantee faster answers to every ticket."),
    ("blocked_phrase", False, "A rockstar support lead with a calm style."),
    ("blocked_phrase", False, "Known as the Best In The Industry for response times."),
    ("blocked_phrase", True, "Response times were guaranteed by contract."),
]


def build() -> list[dict[str, object]]:
    rng = random.Random(20261108)  # noqa: S311 - a fixed shuffle, not security
    cases: list[dict[str, object]] = []
    # Plain clean documents: overlapping windows of three shuffled paraphrases, stepping by two
    # and wrapping around, so every paraphrase appears in at least one clean document.
    order = CLEAN[:]
    rng.shuffle(order)
    for i in range(0, len(order), 2):
        window = [order[(i + k) % len(order)] for k in range(3)]
        cases.append({"kind": "clean", "hard": False, "doc": "\n".join(window)})
    for kind, hard, sentence in TARGETS:
        filler = rng.sample(CLEAN, 2)
        doc = "\n".join([filler[0], sentence, filler[1]])
        cases.append({"kind": kind, "hard": hard, "doc": doc})
    for i, c in enumerate(cases):
        c["id"] = f"c{i + 1:02d}"
        c["split"] = "dev" if i % 2 == 0 else "test"
    return [{k: c[k] for k in ("id", "split", "kind", "hard", "doc")} for c in cases]


def render(cases: list[dict[str, object]]) -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)


if __name__ == "__main__":
    out = Path(__file__).with_name("cases.jsonl")
    text = render(build())
    if "--check" in sys.argv:
        sys.exit(0 if out.exists() and out.read_text(encoding="utf-8") == text else 1)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({text.count(chr(10))} cases)")
