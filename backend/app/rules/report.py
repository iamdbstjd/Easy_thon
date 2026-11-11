"""리포트 조립: 규칙 결과, 종합 판정, 계약서·등기부 대조표, 수정 요청서, 문구."""

from __future__ import annotations

from app.schemas import CheckRequest, Counts, Report

from . import content, crosscheck, engine
from .common import now_kst, today_kst


def build_report(req: CheckRequest) -> Report:
    """CheckRequest를 받아 R1–R13 규칙을 모두 계산하고 Report를 돌려준다.

    - AI나 외부 API를 부르지 않는다 (같은 입력이면 generated_at 말고는 같은 결과).
    - req.today가 없으면 현재 한국 날짜를 쓴다.
    """
    today = req.today or today_kst()
    ctx = engine.make_context(req, today)
    results = sorted((engine.run_rule(rid, fn, ctx) for rid, fn in engine.RULES), key=engine.sort_key)
    counts = Counts(**{lvl: sum(1 for r in results if r.level == lvl) for lvl in engine.LEVEL_ORDER})
    levels = {r.id: r.level for r in results}

    c = ctx.contract
    lease_type = c.lease_type if c else None
    mortgage_amount = engine.mortgage_amount(ctx)
    documents = content.request_items(
        levels,
        has_agent=bool(c and (c.agent_name or "").strip()),
        has_mortgage=mortgage_amount is not None,
    )
    terms = content.build_special_terms(levels, lease_type, mortgage_amount)
    return Report(
        mode=req.mode,
        generated_at=now_kst(),
        today=today,
        overall=content.build_overall(levels, req.registry.unreadable),
        counts=counts,
        results=results,
        comparison=crosscheck.build_comparison(ctx, levels),
        amendment=crosscheck.build_amendment(ctx, levels, terms, content.amendment_documents(documents)),
        request_message=content.build_request_message(engine.message_address(ctx), documents),
        special_terms=terms,
        checklist=content.build_checklist(
            contract_date=(c.contract_date if c else None) or ctx.manual.contract_date,
            balance_date=c.balance_date if c else None,
            move_in_date=c.move_in_date if c else None,
            lease_type=lease_type,
        ),
        disclaimer=content.DISCLAIMER,
    )
