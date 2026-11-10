"""Sweep PRD 7.3 / 8.6 / 10 / F5 / F6 invariants over every report built earlier in this session.

Runs last (file name). If run alone it skips.
"""

from __future__ import annotations

import pytest

from app.schemas import RULE_NAMES
from verify_helpers import BANNED, COLLECTED, DISCLAIMER, EMOJI_RE, RULE_IDS, all_texts, expected_overall


def _reports():
    if not COLLECTED:
        pytest.skip("no reports collected (run the whole tests_verify folder)")
    return COLLECTED


def _fail(problems):
    if problems:
        sample = "\n".join(problems[:15])
        pytest.fail(f"{len(problems)} problem(s), first ones:\n{sample}")


def test_sweep_structure_counts_overall():
    problems = []
    for req, rep in _reports():
        ids = [r.id for r in rep.results]
        if sorted(ids) != sorted(RULE_IDS):
            problems.append(f"ids {ids}")
            continue
        for r in rep.results:
            if r.name != RULE_NAMES[r.id]:
                problems.append(f"{r.id} name {r.name!r}")
        for k in ("red", "yellow", "unknown", "green"):
            if getattr(rep.counts, k) != sum(r.level == k for r in rep.results):
                problems.append(f"counts.{k}")
        exp = expected_overall(rep.results)
        got = (rep.overall.level, rep.overall.title, rep.overall.message, rep.overall.unknown_note)
        if got != exp:
            problems.append(f"overall {got} != {exp}")
        if rep.today != (req.today or rep.today):
            problems.append("today not echoed")
        if rep.mode != req.mode:
            problems.append("mode not echoed")
    _fail(problems)


def test_sweep_evidence_and_reasons():
    problems = []
    for _, rep in _reports():
        for r in rep.results:
            if r.level in ("red", "yellow"):
                if not (r.title and r.summary and r.action):
                    problems.append(f"{r.id} {r.level} missing text")
                if not r.evidence or not all(e.text.strip() for e in r.evidence):
                    problems.append(f"{r.id} {r.level} without evidence")
            if r.level == "unknown" and not (r.unknown_reason or "").strip():
                problems.append(f"{r.id} unknown without reason")
    _fail(problems)


def test_sweep_banned_phrases_emoji_disclaimer():
    problems = []
    for _, rep in _reports():
        if rep.disclaimer != DISCLAIMER:
            problems.append("disclaimer differs")
        for t in all_texts(rep):
            for b in BANNED:
                if b in t:
                    problems.append(f"banned {b!r} in {t!r}")
            if EMOJI_RE.search(t):
                problems.append(f"emoji in {t!r}")
            for bad in ("None", "{", "}", "  "):
                if bad in t and "\n" not in t:
                    problems.append(f"template residue {bad!r} in {t!r}")
    _fail(problems)


def test_sweep_ordering():
    problems = []
    rank = {"red": 0, "yellow": 1, "unknown": 2, "green": 2}
    for _, rep in _reports():
        for level in ("red", "yellow", "unknown", "green"):
            seq = [int(r.id[1:]) for r in rep.results if r.level == level]
            if seq != sorted(seq):
                problems.append(f"{level} order {seq}")
        ranks = [rank[r.level] for r in rep.results]
        plain = [int(r.id[1:]) for r in rep.results] == list(range(1, 14))
        if not plain and ranks != sorted(ranks):
            problems.append("level order " + ",".join(f"{r.id}:{r.level}" for r in rep.results))
    _fail(problems)


def test_sweep_size():
    """Not a PRD check: documents how many reports the sweep covered (493 on a full run of tests_verify)."""
    print(f"\nreports swept: {len(_reports())}")
    assert len(_reports()) > 0


def test_sweep_rrn_masking():
    """PRD 7.4 공통 (line 464) and §10 (line 665): no 주민등록번호 형태 in screen text; evidence quotes mask it."""
    from verify_helpers import RRN_MASK, RRN_RE

    problems = []
    for _, rep in _reports():
        screen = [rep.overall.title, rep.overall.message, rep.overall.unknown_note or "", rep.request_message or ""]
        screen += list(rep.special_terms) + [c.title for c in rep.checklist]
        for r in rep.results:
            screen += [r.title, r.summary, r.action, r.unknown_reason or ""]
            for e in r.evidence:
                bad = [m for m in RRN_RE.findall(e.text) if m != RRN_MASK]
                if bad:
                    problems.append(f"{r.id} evidence not masked: {bad} in {e.text!r}")
        for t in screen:
            if RRN_RE.search(t):
                problems.append(f"RRN on screen: {t!r}")
    _fail(problems)
