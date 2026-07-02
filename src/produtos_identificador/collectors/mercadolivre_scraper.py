from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, replace
from html import unescape
from pathlib import Path
from typing import Any

from ..models import BrazilProduct


SEARCH_BASE = "https://lista.mercadolivre.com.br/{query}"


class ScraperBlockedError(RuntimeError):
    pass


def scrape_search_products(
    query: str,
    *,
    limit: int = 50,
    cache_dir: str | Path = ".cache/mercadolivre",
    delay_seconds: float = 1.5,
    use_cache: bool = True,
) -> list[BrazilProduct]:
    html = fetch_search_html(query, cache_dir=cache_dir, use_cache=use_cache)
    products = parse_search_html(html, limit=limit)
    if not products:
        raise RuntimeError("Nao foi possivel extrair produtos da pagina do Mercado Livre.")
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    return _apply_limit(products, limit)


def fetch_search_html(
    query: str,
    *,
    cache_dir: str | Path = ".cache/mercadolivre",
    use_cache: bool = True,
) -> str:
    cache_path = _cache_path(query, cache_dir)
    if use_cache and cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")

    url = SEARCH_BASE.format(query=urllib.parse.quote(query.replace(" ", "-")))
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
            "Cache-Control": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="ignore")

    if _looks_blocked(html):
        raise ScraperBlockedError(
            "Mercado Livre exibiu pagina de verificacao/suspicious traffic. "
            "O scraper nao deve tentar burlar CAPTCHA ou verificacao; use API, cache ou outra fonte."
        )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    return html


def parse_search_html(html: str, *, limit: int = 50) -> list[BrazilProduct]:
    if _looks_blocked(html):
        raise ScraperBlockedError("HTML recebido e uma pagina de verificacao do Mercado Livre.")

    products = _parse_json_ld(html)
    products.extend(_parse_card_html(html))

    unique: dict[str, BrazilProduct] = {}
    for product in products:
        key = product.url or product.title
        if product.title and product.price_brl > 0 and key not in unique:
            unique[key] = product
    return _apply_limit(list(unique.values()), limit)


def _apply_limit(products: list[BrazilProduct], limit: int) -> list[BrazilProduct]:
    if limit <= 0:
        return products
    return products[:limit]


def write_brazil_products_csv(products: list[BrazilProduct], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = [
            "source",
            "title",
            "price_brl",
            "url",
            "sold_quantity",
            "rating",
            "reviews",
            "brand",
            "model",
            "query",
            "page",
            "position",
            "is_ad",
            "mlb_id",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for product in products:
            writer.writerow(asdict(product))


def merge_brazil_products_csv(
    products: list[BrazilProduct],
    output_path: str | Path,
    *,
    replace_query: str | None = None,
) -> list[BrazilProduct]:
    path = Path(output_path)
    query_key = _query_key(replace_query or (products[0].query if products else ""))
    existing = load_brazil_products_csv(path) if path.exists() else []
    if query_key:
        existing = [product for product in existing if _query_key(product.query) != query_key]
    normalized_products = [product if product.query else replace(product, query=replace_query) for product in products]
    merged = existing + normalized_products
    write_brazil_products_csv(merged, path)
    return merged


def load_brazil_products_csv(path: str | Path) -> list[BrazilProduct]:
    products: list[BrazilProduct] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            products.append(
                BrazilProduct(
                    source=row.get("source", "").strip() or "Mercado Livre CSV",
                    title=row.get("title", "").strip(),
                    price_brl=_to_float(row.get("price_brl")) or 0.0,
                    url=row.get("url", "").strip(),
                    sold_quantity=int(_to_float(row.get("sold_quantity")) or 0),
                    rating=_to_float(row.get("rating")),
                    reviews=int(_to_float(row.get("reviews")) or 0),
                    brand=_optional(row.get("brand")),
                    model=_optional(row.get("model")),
                    query=_optional(row.get("query")),
                    page=int(_to_float(row.get("page")) or 0) or None,
                    position=int(_to_float(row.get("position")) or 0) or None,
                    is_ad=_to_bool(row.get("is_ad")),
                    mlb_id=_optional(row.get("mlb_id")),
                )
            )
    return products


def _query_key(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _parse_json_ld(html: str) -> list[BrazilProduct]:
    products: list[BrazilProduct] = []
    for script in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(unescape(script).strip())
        except json.JSONDecodeError:
            continue
        for item in _iter_json_ld_items(payload):
            product = _product_from_json_ld(item)
            if product:
                products.append(product)
    return products


def _iter_json_ld_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for entry in payload:
            items.extend(_iter_json_ld_items(entry))
        return items
    if not isinstance(payload, dict):
        return []
    if payload.get("@type") == "ItemList":
        elements = payload.get("itemListElement") or []
        return [element.get("item", element) for element in elements if isinstance(element, dict)]
    if payload.get("@type") == "Product":
        return [payload]
    graph = payload.get("@graph")
    if isinstance(graph, list):
        return _iter_json_ld_items(graph)
    return []


def _product_from_json_ld(item: dict[str, Any]) -> BrazilProduct | None:
    title = str(item.get("name") or "").strip()
    if not title:
        return None
    offers = item.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = _to_float(offers.get("price") if isinstance(offers, dict) else None)
    url = str(item.get("url") or (offers.get("url") if isinstance(offers, dict) else "") or "")
    rating_data = item.get("aggregateRating") or {}
    rating = _to_float(rating_data.get("ratingValue")) if isinstance(rating_data, dict) else None
    reviews = int(_to_float(rating_data.get("reviewCount")) or 0) if isinstance(rating_data, dict) else 0
    return BrazilProduct(
        source="Mercado Livre Scraper",
        title=title,
        price_brl=price or 0.0,
        url=url,
        rating=rating,
        reviews=reviews,
    )


def _parse_card_html(html: str) -> list[BrazilProduct]:
    products: list[BrazilProduct] = []
    blocks = re.findall(
        r'<li[^>]+class=["\'][^"\']*ui-search-layout__item[^"\']*["\'][^>]*>(.*?)</li>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not blocks:
        blocks = re.findall(
            r'<div[^>]+class=["\'][^"\']*ui-search-result[^"\']*["\'][^>]*>(.*?)</div>\s*</div>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    for block in blocks:
        title = _first_match(
            block,
            [
                r'class=["\'][^"\']*ui-search-item__title[^"\']*["\'][^>]*>(.*?)<',
                r'title=["\']([^"\']+)["\']',
                r'aria-label=["\']([^"\']+)["\']',
            ],
        )
        url = _first_match(block, [r'<a[^>]+href=["\']([^"\']+)["\']'])
        price = _extract_price(block)
        if not title or not price:
            continue
        products.append(
            BrazilProduct(
                source="Mercado Livre Scraper",
                title=_clean_text(title),
                price_brl=price,
                url=unescape(url or ""),
                sold_quantity=_extract_sold_quantity(block),
                rating=_extract_rating(block),
                reviews=_extract_reviews(block),
            )
        )
    return products


def _extract_price(block: str) -> float:
    meta_price = _first_match(block, [r'itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']'])
    if meta_price:
        return _to_float(meta_price) or 0.0

    fraction = _first_match(block, [r'class=["\'][^"\']*andes-money-amount__fraction[^"\']*["\'][^>]*>(.*?)<'])
    cents = _first_match(block, [r'class=["\'][^"\']*andes-money-amount__cents[^"\']*["\'][^>]*>(.*?)<'])
    if not fraction:
        return 0.0
    value = _digits(fraction)
    if cents:
        value = f"{value}.{_digits(cents).zfill(2)}"
    return _to_float(value) or 0.0


def _extract_sold_quantity(block: str) -> int:
    text = _clean_text(block)
    match = re.search(r"(\d+)\s*(mil\s*)?vendidos?", text, flags=re.IGNORECASE)
    if not match:
        return 0
    value = int(match.group(1))
    return value * 1000 if match.group(2) else value


def _extract_rating(block: str) -> float | None:
    text = _clean_text(block)
    match = re.search(r"(\d+[,.]\d+)\s*(?:de\s*5|estrelas|stars)", text, flags=re.IGNORECASE)
    return _to_float(match.group(1)) if match else None


def _extract_reviews(block: str) -> int:
    text = _clean_text(block)
    match = re.search(r"\((\d+)\)", text)
    return int(match.group(1)) if match else 0


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return unescape(match.group(1)).strip()
    return None


def _clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _optional(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _to_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "sim"}


def _looks_blocked(html: str) -> bool:
    lowered = html.lower()
    return (
        "suspicious-traffic" in lowered
        or "account-verification" in lowered
        or "verificacao" in lowered
        or "verificação" in lowered
        or "captcha" in lowered
    )


def _cache_path(query: str, cache_dir: str | Path) -> Path:
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
    return Path(cache_dir) / f"{digest}.html"
