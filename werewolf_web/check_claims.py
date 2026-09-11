"""Public-only, derived ledger of explicit Seer-report lines.

Not an NLP extractor: ambiguous prose, quotations and third-party paraphrases
are not converted into checks. Raw public speech remains the source of truth.
No engine, private results or brain is accepted by this module.
"""
import re

EN = re.compile(r"Seer report: night ([1-9][0-9]{0,3}), seat ([1-9][0-9]{0,3}), (good|wolf)\.", re.I)
ZH = re.compile(r"预言家查验声明：第([1-9][0-9]{0,3})夜，([1-9][0-9]{0,3})号，(好人|狼人)。")


def report_line(night, target, result, locale):
    if locale == "en":
        return f"Seer report: night {night}, seat {target}, {result}."
    return f"预言家查验声明：第{night}夜，{target}号，{'好人' if result == 'good' else '狼人'}。"


def parse_reports(text):
    if not isinstance(text, str):
        return []
    reports = []
    # The explicit protocol is a trailing block, not a line extracted from a
    # quotation, code fence or paraphrase embedded in surrounding prose.
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        match = EN.fullmatch(line) or ZH.fullmatch(line)
        if not match:
            break
        night, target, result = match.groups()
        reports.append({"night": int(night), "target": int(target),
                        "result": {"好人": "good", "狼人": "wolf"}.get(result, result.lower()),
                        "line": line})
    return list(reversed(reports))


def audit(entries, *, limit=16):
    if type(limit) is not int or limit < 1:
        raise ValueError("Audit limit must be positive")
    # Role metadata describes public rules, not any seat's unrevealed identity.
    from .game.engine import ROLE_META
    from .game.models import WOLF_ROLES
    from .i18n import role_name, SUPPORTED_LOCALES
    aliases = {}
    for role, meta in ROLE_META.items():
        for label in (role, meta["cn"], *(role_name(loc, role, meta["cn"]) for loc in SUPPORTED_LOCALES)):
            aliases.setdefault(label, set()).add(role)
    reports, findings = [], []
    by_night, by_target, seen, flips = {}, {}, set(), {}
    for row in entries:
        ev = row["event"]
        number = ev.get("event_no")
        if type(number) is not int or number < 1:
            continue  # Legacy unknown references stay prose, not fabricated IDs.
        if ev.get("type") == "flip" and type(ev.get("seat")) is int:
            candidates = aliases.get(ev.get("role") or ev.get("role_cn"), set())
            if len(candidates) == 1:
                role = next(iter(candidates))
                flips[ev["seat"]] = {"event_no": number, "role": role,
                                      "result": "wolf" if role in WOLF_ROLES and role != "hidden_wolf" else "good"}
        if ev.get("type") != "speech" or type(ev.get("seat")) is not int:
            continue
        actor = ev["seat"]
        if not 1 <= actor <= 12:
            continue
        for report in parse_reports(ev.get("text")):
            item = dict(report, actor=actor, name=ev.get("name"), event_no=number)
            key = actor, report["night"], report["target"], report["result"]
            if key in seen:
                continue
            seen.add(key)
            reports.append(item)
            def flag(kind, previous=None):
                findings.append({"kind": kind, "report": dict(item),
                                 "previous_report": dict(previous) if previous else None})
            if not 1 <= report["target"] <= 12:
                flag("invalid_target")
                continue
            current_night = row.get("night")
            if type(current_night) is int and report["night"] > current_night:
                flag("future_night")
            prior = by_night.get((actor, report["night"]))
            if prior and (prior["target"], prior["result"]) != (report["target"], report["result"]):
                flag("conflicting_same_night", prior)
            by_night.setdefault((actor, report["night"]), item)
            prior = by_target.get((actor, report["target"]))
            if prior and prior["result"] != report["result"]:
                flag("changed_result", prior)
            by_target.setdefault((actor, report["target"]), item)
    for report in reports:
        flip = flips.get(report["target"])
        if flip:
            findings.append({"kind": "compatible_with_flip" if report["result"] == flip["result"] else "contradicted_by_flip",
                             "report": dict(report), "flip": dict(flip)})
    return {"reports": reports[-limit:], "findings": findings[-limit:],
            "truncated": len(reports) > limit or len(findings) > limit,
            "coverage": "Explicit trailing Seer report lines only; unstructured and unnumbered history is not audited.",
            "boundary": "A contradiction concerns a claim, not proof of the speaker's faction. "
                        "Compatibility with a flip does not establish a real check. Hidden wolves read good."}


def finding_text(finding, locale):
    r = finding["report"]
    labels = {
        "invalid_target": ("目标座位不合法", "invalid target seat"),
        "future_night": ("声称查验尚未到来的夜晚", "reports a future night"),
        "conflicting_same_night": ("同一夜的目标或结果前后不同", "different targets/results for the same night"),
        "changed_result": ("对同一目标的结果前后不同", "changed result for the same target"),
        "compatible_with_flip": ("与公开翻牌相容，但不证明真实查验", "compatible with the public flip, not proof of a real check"),
        "contradicted_by_flip": ("与公开翻牌的查验规则不符", "inconsistent with the public flip's check result"),
    }
    en = locale == "en"
    refs = [r["event_no"]]
    other = finding.get("previous_report") or finding.get("flip")
    if other:
        refs.append(other["event_no"])
    reference = "/".join(map(str, refs))
    detail = labels[finding["kind"]][en]
    if en:
        return f"Records {reference}: #{r['actor']}'s night {r['night']} report about #{r['target']}: {detail}. This does not prove the speaker is a wolf."
    return f"记录{reference}：{r['actor']}号对第{r['night']}夜查验{r['target']}号的声明，{detail}；这不直接证明发言者是狼人。"


def query_text(entries, locale):
    result = audit(entries)
    en = locale == "en"
    lines = [(f"Record {r['event_no']}, #{r['actor']}: {r['line']}" if en else
              f"记录{r['event_no']}，{r['actor']}号：{r['line']}") for r in result["reports"]]
    lines.extend(finding_text(f, locale) for f in result["findings"])
    if result["truncated"]:
        lines.append("Showing a bounded recent audit; use public history for originals." if en else "仅显示最近的有限条目，原文请查询公开记录。")
    return "\n".join(lines) or ("No explicit report lines yet; free text is not automatically audited." if en else "尚无标准格式的查验声明；自由文本未自动对账。")
