from __future__ import annotations

import re
import unicodedata


STOPWORDS = {
    "original",
    "novo",
    "nova",
    "lacrado",
    "promocao",
    "promoção",
    "frete",
    "gratis",
    "grátis",
    "envio",
    "imediato",
    "pronta",
    "entrega",
    "garantia",
    "oficial",
    "chinh",
    "hang",
}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token not in STOPWORDS]
    return " ".join(tokens)


def tokens(value: str) -> set[str]:
    return set(normalize_text(value).split())


def infer_brand(title: str, known_brands: set[str]) -> str | None:
    normalized = normalize_text(title)
    for brand in sorted(known_brands, key=len, reverse=True):
        if normalize_text(brand) in normalized:
            return brand
    return None

