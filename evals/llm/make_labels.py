# ruff: noqa: E501  (the label table is data: one document per line)
"""Write evals/llm/labels.jsonl: my labels for the generated documents, made by reading each one
BEFORE running the checker on any of them. Labels cover what truth-gate checks (numbers,
skills, blocked phrases). `relation` notes a link the facts do not state (time, cause or
employer), which truth-gate does not check. `evidence` is what tests/test_llm_eval.py verifies
programmatically against the document and the facts. Documents are never edited; a document
that did not follow its instruction is labelled `dropped` and left out of the scores.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# id: (label, expected_check, evidence, reason). label: pass | fail | dropped.
L: dict[str, tuple[str, str | None, str | None, str]] = {
    "L01": ("pass", None, None, "all figures as in the facts; 'during this period' ties routing to 2017-2021"),
    "L02": ("fail", "number", "75", "75 help-centre articles; the fact says 60"),
    "L03": ("pass", None, None, "figures correct; claims the improvements caused the satisfaction rise"),
    "L04": ("fail", "number", "9", "first-response time 'to 9 hours'; 9 is the team size, the fact says 4 hours"),
    "L05": ("pass", None, None, "figures correct; 'later in their career' orders facts"),
    "L06": ("fail", "skill", "Tableau", "claims Tableau; also places the help-centre work at ExampleSoft Ltd (unchecked)"),
    "L07": ("pass", None, None, "figures correct; 'during this period' ties the satisfaction rise to 2017-2021"),
    "L08": ("fail", "blocked", "rockstar", "uses the blocked phrase 'rockstar'"),
    "L09": ("pass", None, None, "figures correct; claims the initiatives contributed to the satisfaction rise"),
    "L10": ("fail", "number", "95%", "satisfaction to 95%; the fact says 92%"),
    "L11": ("pass", None, None, "figures correct ('nine people'); 'earlier in their career' orders facts"),
    "L12": ("fail", "number", "22", "'within 22 months'; 22 is the repeat-question cut, the fact says 18 months"),
    "L13": ("pass", None, None, "figures correct; 'later' orders facts"),
    "L14": ("fail", "skill", "Tableau", "claims Tableau"),
    "L15": ("pass", None, None, "figures correct; claims documentation work caused the satisfaction rise"),
    "L16": ("fail", "blocked", "rockstar", "uses the blocked phrase 'rockstar'"),
    "L17": ("pass", None, None, "figures correct; claims routing automation caused the faster responses"),
    "L18": ("fail", "number", "2", "first-response time to 2 hours; the fact says 4 hours"),
    "L19": ("pass", None, None, "figures correct; claims the routing work raised satisfaction"),
    "L20": ("dropped", None, None, "asked to move a number unchanged; wrote '4 million' hours, a changed value"),
    "L21": ("pass", None, None, "figures correct; 'through dedicated leadership' is a causal claim"),
    "L22": ("fail", "skill", "Salesforce", "claims Salesforce"),
    "L23": ("pass", None, None, "figures correct; 'previously' orders facts"),
    "L24": ("fail", "blocked", "rockstar", "uses the blocked phrase 'rockstar'"),
    "L25": ("pass", None, None, "figures correct; places the satisfaction rise at ExampleParcel Co (prompt framed the service there)"),
    "L26": ("fail", "number", "40%", "repeat questions cut by 40%; the fact says 22%"),
    "L27": ("pass", None, None, "figures correct; credits the team under Jordan with the response-time cut"),
    "L28": ("fail", "number", "92%", "repeat questions cut by 92%; 92% is the satisfaction score, the fact says 22%"),
    "L29": ("pass", None, None, "figures correct ('22 percent'); 'previously' orders facts"),
    "L30": ("fail", "skill", "Docker", "claims Docker"),
    "L31": ("pass", None, None, "figures correct; causal and purpose links between facts"),
    "L32": ("fail", "blocked", "rockstar", "uses the blocked phrase 'rockstar'"),
    "L33": ("pass", None, None, "figures correct; 'during this time' ties the response-time cut to the ExampleSoft role"),
    "L34": ("fail", "number", "80", "80 help-centre articles; the fact says 60"),
    "L35": ("pass", None, None, "figures correct; credits the team and claims causes"),
    "L36": ("dropped", None, None, "asked to move exactly one number; swapped two (22 articles, 60 percent)"),
    "L37": ("pass", None, None, "figures correct; credits the team under Jordan"),
    "L38": ("fail", "skill", "Excel", "claims Excel"),
    "L39": ("pass", None, None, "figures correct; claims the gain contributed to annual results"),
    "L40": ("fail", "blocked", "rockstar", "uses the blocked phrase 'rockstar'"),
    "L41": ("pass", None, None, "figures correct; credits the team under Jordan with the satisfaction rise"),
    "L42": ("fail", "number", "$4.5", "revenue $4.5 million; the fact says $3.5 million"),
    "L43": ("pass", None, None, "figures correct; 'during this time' links routing to the ExampleSoft role"),
    "L44": ("fail", "number", "9", "Scrum certification 'in 9'; 9 is the team size, the fact says 2020"),
    "L45": ("pass", None, None, "figures correct; credits the team under Jordan"),
    "L46": ("fail", "skill", "Excel", "claims Excel"),
    "L47": ("pass", None, None, "figures correct ('22 percent'); 'during this period' links facts"),
    "L48": ("fail", "blocked", "rockstar", "uses the blocked phrase 'rockstar'"),
}  # fmt: skip


def main() -> None:
    rows = [
        json.loads(x) for x in (HERE / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    docs = {r["id"]: r for r in rows if "id" in r}
    if set(docs) != set(L):
        raise SystemExit("every document needs exactly one label")
    out = []
    for doc_id in sorted(docs):
        label, check, evidence, reason = L[doc_id]
        d = docs[doc_id]
        out.append(
            {
                "id": doc_id,
                "doc_sha256": hashlib.sha256(d["document"].encode()).hexdigest(),
                "requested": d["requested"],
                "label": label,
                "expected_check": check,
                "evidence": evidence,
                # Every clean document links facts by time, cause or employer (see README).
                "relation": label == "pass",
                "reason": reason,
            }
        )
    (HERE / "labels.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8"
    )
    print(f"wrote {len(out)} labels")


if __name__ == "__main__":
    main()
