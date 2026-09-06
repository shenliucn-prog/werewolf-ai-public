"""Export blind requests or score saved responses; never calls an API."""

import argparse
from collections import Counter
import json

from .judgment import InvalidReport, _unique_object, build_request, parse_report
from .judgment_cases import load_cases


def evaluate(cases, responses: dict[str, str]) -> dict:
    """Score against authored labels, separately reporting abstention and failures.

    Exact quote validation is provenance checking; required-ID coverage is a
    coarse rubric, NOT semantic proof that the explanation is supported.
    """
    cases = tuple(cases)
    if type(responses) is not dict:
        raise ValueError("responses must map request IDs to raw JSON strings")
    ids = {c.context.request_id for c in cases}
    if len(ids) != len(cases) or not set(responses) <= ids:
        raise ValueError("duplicate cases or response IDs outside selected split")
    rows = []
    errors = Counter()
    confusion = Counter()
    for case in cases:
        row = {"request_id": case.context.request_id, "locale": case.context.locale,
               "expected": case.expected, "verdict": None, "valid": False,
               "confidence": None, "correct": False, "required_evidence_covered": False}
        if case.context.request_id not in responses:
            row["error"] = "missing_response"
        else:
            try:
                report = parse_report(case.context, responses[case.context.request_id])
                row.update(valid=True, verdict=report.verdict,
                           confidence=report.confidence,
                           correct=report.verdict == case.expected,
                           required_evidence_covered=set(case.required_evidence) <=
                           {c.event_id for c in report.citations})
            except InvalidReport as exc:
                row["error"] = exc.code
        if not row["valid"]:
            errors[row["error"]] += 1
        confusion[(case.expected, row["verdict"] or "INVALID_OR_MISSING")] += 1
        rows.append(row)

    def summarize(items):
        total = len(items)
        valid = sum(r["valid"] for r in items)
        correct = sum(r["correct"] for r in items)
        severe = [r for r in items if r["expected"] == "unresolved_contradiction"]
        negative = [r for r in items if r["expected"] != "unresolved_contradiction"]
        false_positives = sum(r["verdict"] == "unresolved_contradiction" for r in negative)
        misses = sum(r["verdict"] != "unresolved_contradiction" for r in severe)
        return {
            "total": total, "valid": valid, "invalid_or_missing": total - valid,
            "correct": correct, "accuracy_all": correct / total if total else None,
            "accuracy_valid_only": correct / valid if valid else None,
            "abstentions": sum(r["verdict"] == "insufficient_evidence" for r in items),
            "required_evidence_covered": sum(r["required_evidence_covered"] for r in items),
            "false_positive_contradictions": false_positives,
            "noncontradiction_cases": len(negative),
            "false_positive_rate": false_positives / len(negative) if negative else None,
            "missed_contradictions_including_invalid": misses,
            "contradiction_cases": len(severe),
            "miss_rate_including_invalid": misses / len(severe) if severe else None,
        }

    return {"summary": summarize(rows), "errors": dict(errors),
            "by_locale": {locale: summarize([r for r in rows if r["locale"] == locale])
                          for locale in sorted({r["locale"] for r in rows})},
            "confusion": [{"expected": expected, "predicted": predicted, "count": count}
                          for (expected, predicted), count in sorted(confusion.items())],
            "rows": rows,
            "caveat": "Authored labels and evidence-ID coverage; not semantic validation or calibrated confidence."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("requests", "score"))
    parser.add_argument("--split", choices=("dev", "heldout"), default="dev")
    parser.add_argument("--responses", help="JSON mapping request IDs to raw model response strings")
    args = parser.parse_args()
    cases = load_cases(args.split)
    if args.operation == "requests":
        if args.responses:
            parser.error("--responses is only valid for scoring")
        output = [build_request(c.context) for c in cases]
    else:
        if not args.responses:
            parser.error("score requires --responses")
        with open(args.responses, encoding="utf-8") as handle:
            # Bounded local artifact input; no environment credentials are read.
            raw = handle.read(2_000_001)
        if len(raw) > 2_000_000:
            parser.error("response file exceeds size limit")
        output = evaluate(cases, json.loads(raw, object_pairs_hook=_unique_object))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
