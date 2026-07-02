from __future__ import annotations

from .models import BrazilProduct, CostConfig, MatchResult, Opportunity, VietnamProduct


def calculate_opportunity(
    br: BrazilProduct,
    vn: VietnamProduct,
    match: MatchResult,
    config: CostConfig,
) -> Opportunity:
    purchase_brl = (vn.price_vnd + vn.shipping_vnd) * config.brl_per_vnd
    import_tax_brl = purchase_brl * config.import_tax_rate
    icms_brl = (purchase_brl + import_tax_brl) * config.icms_rate
    landed_cost_brl = purchase_brl + import_tax_brl + icms_brl + config.fixed_cost_brl
    marketplace_fees_brl = br.price_brl * (config.ml_fee_rate + config.payment_fee_rate)
    total_cost_brl = landed_cost_brl + marketplace_fees_brl
    gross_profit_brl = br.price_brl - total_cost_brl
    margin_rate = gross_profit_brl / br.price_brl if br.price_brl else 0.0
    score = opportunity_score(br, vn, match.confidence, margin_rate)

    return Opportunity(
        br_product=br,
        vn_product=vn,
        match=match,
        landed_cost_brl=round(landed_cost_brl, 2),
        marketplace_fees_brl=round(marketplace_fees_brl, 2),
        total_cost_brl=round(total_cost_brl, 2),
        gross_profit_brl=round(gross_profit_brl, 2),
        margin_rate=round(margin_rate, 4),
        score=score,
    )


def opportunity_score(br: BrazilProduct, vn: VietnamProduct, confidence: float, margin_rate: float) -> int:
    demand_score = min(1.0, br.sold_quantity / 500)
    rating_score = ((br.rating or 4.0) - 3.0) / 2.0
    supplier_score = min(1.0, (vn.sold_quantity / 1000) * 0.7 + (((vn.rating or 4.0) - 3.0) / 2.0) * 0.3)
    margin_score = max(0.0, min(1.0, margin_rate / 0.60))
    weighted = (
        demand_score * 0.30
        + margin_score * 0.35
        + confidence * 0.20
        + supplier_score * 0.10
        + max(0.0, min(1.0, rating_score)) * 0.05
    )
    return round(weighted * 100)

