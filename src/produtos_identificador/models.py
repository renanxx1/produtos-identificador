from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrazilProduct:
    source: str
    title: str
    price_brl: float
    url: str
    sold_quantity: int = 0
    rating: float | None = None
    reviews: int = 0
    brand: str | None = None
    model: str | None = None
    query: str | None = None
    page: int | None = None
    position: int | None = None
    is_ad: bool = False
    mlb_id: str | None = None


@dataclass(frozen=True)
class VietnamProduct:
    marketplace: str
    title: str
    price_vnd: float
    shipping_vnd: float
    url: str
    brand: str | None = None
    model: str | None = None
    rating: float | None = None
    sold_quantity: int = 0


@dataclass(frozen=True)
class CostConfig:
    brl_per_vnd: float = 0.00022
    import_tax_rate: float = 0.60
    icms_rate: float = 0.17
    ml_fee_rate: float = 0.16
    payment_fee_rate: float = 0.0499
    fixed_cost_brl: float = 12.0
    target_margin_rate: float = 0.25


@dataclass(frozen=True)
class MatchResult:
    is_same_product: bool
    confidence: float
    reason: str


@dataclass(frozen=True)
class Opportunity:
    br_product: BrazilProduct
    vn_product: VietnamProduct
    match: MatchResult
    landed_cost_brl: float
    marketplace_fees_brl: float
    total_cost_brl: float
    gross_profit_brl: float
    margin_rate: float
    score: int
