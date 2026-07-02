from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .models import BrazilProduct
from .normalizer import normalize_text


BRAND_ALIASES = {
    "adata": "Adata",
    "ceamere": "Ceamere",
    "coretech": "Coretech",
    "corsair": "Corsair",
    "crucial": "Crucial",
    "darkplayer": "Darkplayer",
    "eletroyou": "EletroYou",
    "goldenfir": "Goldenfir",
    "good vision": "Good Vision",
    "hiksemi": "Hiksemi",
    "keepdata": "Keepdata",
    "kingston": "Kingston",
    "kingspec": "Kingspec",
    "lexar": "Lexar",
    "macrovip": "Macrovip",
    "micron": "Micron",
    "msi": "MSI",
    "puskill": "Puskill",
    "redragon": "Redragon",
    "samsung": "Samsung",
    "sandisk": "Sandisk",
    "safe gamer": "Safe Gamer",
    "seagate": "Seagate",
    "teamgroup": "Teamgroup",
    "up gamer": "Up Gamer",
    "western digital": "Western Digital",
    "wd": "Western Digital",
    "winmemory": "WinMemory",
    "xpg": "XPG",
}


MODEL_PATTERNS = [
    r"\b990\s+evo\s+plus\b",
    r"\b990\s+evo\b",
    r"\b990\s+pro\b",
    r"\b980\s+pro\b",
    r"\b970\s+evo\s+plus\b",
    r"\bmp700\s+pro\b",
    r"\bmp600\s+pro\s+lpx\b",
    r"\bmp600\s+pro\b",
    r"\bspatium\s+m371\b",
    r"\blegend\s+860\b",
    r"\blegend\s+710\b",
    r"\bspectrix\s+s20g\b",
    r"\bwd\s+green\s+sn3000\b",
    r"\bwd\s+green\s+sn350\b",
    r"\bgreen\s+sn3000\b",
    r"\bgreen\s+sn350\b",
    r"\bsn3000\b",
    r"\bsn350\b",
    r"\bnv3\s+mini\b",
    r"\bnv3\b",
    r"\bnv2\b",
    r"\bsnv3s(?:m3)?/?[0-9a-z]*\b",
    r"\bsnv2s/?[0-9a-z]*\b",
    r"\be100\b",
    r"\bpm9a1\b",
    r"\bplus\b",
    r"\boptimus\s+5100\b",
]


GENERIC_TOKENS = {
    "ssd",
    "hd",
    "disco",
    "solido",
    "interno",
    "externo",
    "m",
    "m2",
    "nvme",
    "pcie",
    "sata",
    "notebook",
    "desktop",
    "computador",
    "pc",
    "gamer",
    "preto",
    "azul",
    "verde",
    "branco",
    "novo",
    "lacrado",
    "original",
}


@dataclass(frozen=True)
class MlProductGroup:
    product_key: str
    search_query: str
    brand: str | None
    model: str | None
    capacity: str | None
    storage_type: str | None
    form_factor: str | None
    interface: str | None
    shopee_query: str
    ads_count: int
    best_price_brl: float
    avg_price_brl: float
    max_price_brl: float
    total_sold: int
    max_rating: float | None
    total_reviews: int
    best_title: str
    best_url: str
    best_mlb_id: str | None
    source_pages: str
    grouped_titles: str


@dataclass(frozen=True)
class ProductSignature:
    product_key: str
    brand: str | None
    model: str | None
    capacity: str | None
    storage_type: str | None
    form_factor: str | None
    interface: str | None
    shopee_query: str


def dedupe_ml_products(products: list[BrazilProduct]) -> list[MlProductGroup]:
    groups: dict[str, list[BrazilProduct]] = {}
    signatures: dict[str, ProductSignature] = {}
    for product in products:
        if not product.title or product.price_brl <= 0:
            continue
        signature = build_product_signature(product.title)
        groups.setdefault(signature.product_key, []).append(product)
        signatures.setdefault(signature.product_key, signature)

    cleaned: list[MlProductGroup] = []
    for key, group_products in groups.items():
        signature = signatures[key]
        best = min(group_products, key=_product_rank)
        prices = [product.price_brl for product in group_products if product.price_brl > 0]
        ratings = [product.rating for product in group_products if product.rating is not None]
        pages = sorted({str(product.page) for product in group_products if product.page})
        search_queries = sorted({str(product.query).strip() for product in group_products if product.query})
        titles = _compact_join(product.title for product in group_products)
        cleaned.append(
            MlProductGroup(
                product_key=key,
                search_query=";".join(search_queries),
                brand=signature.brand,
                model=signature.model,
                capacity=signature.capacity,
                storage_type=signature.storage_type,
                form_factor=signature.form_factor,
                interface=signature.interface,
                shopee_query=signature.shopee_query,
                ads_count=len(group_products),
                best_price_brl=best.price_brl,
                avg_price_brl=round(sum(prices) / len(prices), 2) if prices else 0.0,
                max_price_brl=max(prices) if prices else 0.0,
                total_sold=sum(product.sold_quantity for product in group_products),
                max_rating=max(ratings) if ratings else None,
                total_reviews=sum(product.reviews for product in group_products),
                best_title=best.title,
                best_url=best.url,
                best_mlb_id=best.mlb_id,
                source_pages=";".join(pages),
                grouped_titles=titles,
            )
        )

    return sorted(cleaned, key=lambda item: (-item.ads_count, item.best_price_brl, item.product_key))


def build_product_signature(title: str) -> ProductSignature:
    normalized = normalize_text(title)
    brand = _extract_brand(normalized)
    model = _extract_model(normalized)
    capacity = _extract_capacity(normalized)
    storage_type = _extract_storage_type(normalized)
    form_factor = _extract_form_factor(normalized)
    interface = _extract_interface(normalized)

    key_parts = [
        normalize_text(brand or ""),
        normalize_text(model or ""),
        normalize_text(capacity or ""),
        normalize_text(storage_type or ""),
    ]
    key_parts = [part for part in key_parts if part]
    if len(key_parts) < 3:
        key_parts = _fallback_key_parts(normalized, capacity)

    product_key = "|".join(key_parts)
    query = _build_shopee_query(brand, model, capacity, storage_type, form_factor, interface, normalized)
    return ProductSignature(
        product_key=product_key,
        brand=brand,
        model=model,
        capacity=capacity,
        storage_type=storage_type,
        form_factor=form_factor,
        interface=interface,
        shopee_query=query,
    )


def write_ml_product_groups_csv(groups: list[MlProductGroup], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = [
            "product_key",
            "search_query",
            "brand",
            "model",
            "capacity",
            "storage_type",
            "form_factor",
            "interface",
            "shopee_query",
            "ads_count",
            "best_price_brl",
            "avg_price_brl",
            "max_price_brl",
            "total_sold",
            "max_rating",
            "total_reviews",
            "best_title",
            "best_url",
            "best_mlb_id",
            "source_pages",
            "grouped_titles",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for group in groups:
            writer.writerow(group.__dict__)


def _product_rank(product: BrazilProduct) -> tuple[float, int, int, int]:
    ad_penalty = 1 if product.is_ad else 0
    missing_id_penalty = 1 if not product.mlb_id else 0
    engagement = product.sold_quantity + product.reviews
    return (product.price_brl, ad_penalty, missing_id_penalty, -engagement)


def _extract_brand(normalized: str) -> str | None:
    for alias, brand in sorted(BRAND_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return brand
    return None


def _extract_model(normalized: str) -> str | None:
    for pattern in MODEL_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            return _title_model(match.group(0))
    return None


def _extract_capacity(normalized: str) -> str | None:
    matches = re.findall(r"\b([0-9]+(?:[,.][0-9]+)?)\s*(tb|gb)\b", normalized)
    if not matches:
        return None
    amount_text, unit = matches[0]
    amount = float(amount_text.replace(",", "."))
    if amount.is_integer():
        amount_label = str(int(amount))
    else:
        amount_label = str(amount).rstrip("0").rstrip(".")
    return f"{amount_label}{unit.upper()}"


def _extract_storage_type(normalized: str) -> str | None:
    if re.search(r"\bnvme\b", normalized):
        return "NVMe"
    if re.search(r"\bsata\b", normalized):
        return "SATA"
    if re.search(r"\bssd\b", normalized):
        return "SSD"
    return None


def _extract_form_factor(normalized: str) -> str | None:
    if re.search(r"\bm\s*2\b|\bm2\b", normalized):
        return "M.2"
    if re.search(r"\b2230\b", normalized):
        return "2230"
    if re.search(r"\b2242\b", normalized):
        return "2242"
    if re.search(r"\b2280\b", normalized):
        return "2280"
    if re.search(r"\b2\s*5\b", normalized):
        return "2.5"
    return None


def _extract_interface(normalized: str) -> str | None:
    if re.search(r"\bpcie\s*5\b|\bgen\s*5\b", normalized):
        return "PCIe 5.0"
    if re.search(r"\bpcie\s*4\b|\bgen\s*4\b", normalized):
        return "PCIe 4.0"
    if re.search(r"\bpcie\s*3\b|\bgen\s*3\b", normalized):
        return "PCIe 3.0"
    if re.search(r"\bpcie\b", normalized):
        return "PCIe"
    return None


def _build_shopee_query(
    brand: str | None,
    model: str | None,
    capacity: str | None,
    storage_type: str | None,
    form_factor: str | None,
    interface: str | None,
    normalized: str,
) -> str:
    parts = [brand, model, capacity]
    if not model and not brand:
        parts = _fallback_key_parts(normalized, capacity)[:4]
    if storage_type and storage_type != "SSD":
        parts.append(storage_type)
    if form_factor and form_factor in {"M.2", "2230", "2242", "2280"}:
        parts.append(form_factor)
    if interface and interface in {"PCIe 4.0", "PCIe 5.0"}:
        parts.append(interface)
    return " ".join(part for part in parts if part)


def _fallback_key_parts(normalized: str, capacity: str | None) -> list[str]:
    clean_capacity = normalize_text(capacity or "")
    parts = []
    for token in normalized.split():
        if token in GENERIC_TOKENS:
            continue
        if token.isdigit() and token in {"2230", "2242", "2280"}:
            continue
        if clean_capacity and token in clean_capacity.split():
            continue
        parts.append(token)
        if len(parts) >= 5:
            break
    if clean_capacity:
        parts.append(clean_capacity)
    return parts or [normalized[:80]]


def _title_model(value: str) -> str:
    acronyms = {"nvme", "pcie", "wd", "msi", "xpg"}
    pieces = []
    for token in value.split():
        if token in acronyms or re.search(r"\d", token):
            pieces.append(token.upper())
        else:
            pieces.append(token.capitalize())
    return " ".join(pieces)


def _compact_join(values) -> str:
    seen = []
    for value in values:
        clean = " ".join(str(value).split())
        if clean and clean not in seen:
            seen.append(clean)
        if len(seen) >= 8:
            break
    return " || ".join(seen)
