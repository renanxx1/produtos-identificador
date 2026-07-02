import pandas as pd

from produtos_identificador.collectors.mercadolivre_scraper import load_brazil_products_csv, write_brazil_products_csv
from produtos_identificador.ml_preprocess import dedupe_ml_products
from produtos_identificador.models import BrazilProduct
from produtos_identificador.streamlit_app import (
    add_to_blacklist,
    apply_ml_blacklist,
    best_manual_rows,
    load_blacklist,
    load_manual_shopee,
    remove_ml_product_from_raw,
)


def test_best_manual_rows_keeps_lowest_price_plus_shipping_per_product():
    rows = pd.DataFrame(
        [
            {"product_key": "ssd|1tb", "enabled": True, "price_vnd": 1_000_000, "shipping_vnd": 50_000, "title": "A"},
            {"product_key": "ssd|1tb", "enabled": True, "price_vnd": 980_000, "shipping_vnd": 10_000, "title": "B"},
            {"product_key": "ssd|2tb", "enabled": True, "price_vnd": 1_800_000, "shipping_vnd": 0, "title": "C"},
        ]
    )

    best = best_manual_rows(rows)

    assert list(best["title"]) == ["B", "C"]


def test_remove_ml_product_from_raw_removes_group_and_rewrites_clean_csv(tmp_path):
    raw = tmp_path / "raw.csv"
    clean = tmp_path / "clean.csv"
    write_brazil_products_csv(
        [
            BrazilProduct(source="ML", title="SSD Kingston NV3 1TB NVMe", price_brl=500, url="a", query="ssd"),
            BrazilProduct(source="ML", title="SSD Kingston NV3 1TB M2 NVMe", price_brl=480, url="b", query="ssd"),
            BrazilProduct(source="ML", title="SSD Kingston NV3 2TB NVMe", price_brl=900, url="c", query="ssd"),
        ],
        raw,
    )

    removed = remove_ml_product_from_raw("kingston|nv3|1tb|nvme", raw, clean)

    assert removed == 2
    assert [product.title for product in load_brazil_products_csv(raw)] == ["SSD Kingston NV3 2TB NVMe"]
    assert "2TB" in clean.read_text(encoding="utf-8-sig")
    assert "1TB" not in clean.read_text(encoding="utf-8-sig")


def test_load_manual_shopee_keeps_url_as_text_when_empty(tmp_path):
    path = tmp_path / "manual.csv"
    path.write_text(
        "product_key,enabled,marketplace,title,price_vnd,shipping_vnd,url,rating,sold_quantity,confidence,notes\n"
        "ssd|1tb,True,Shopee VN,Produto,1000000,0,,4.8,10,0.9,\n",
        encoding="utf-8",
    )

    df = load_manual_shopee(path)

    assert df["url"].dtype == object
    assert df.loc[0, "url"] == ""
    assert df.loc[0, "status"] == "cadastrado"


def test_blacklist_filters_grouped_products(tmp_path):
    groups = dedupe_ml_products(
        [
            BrazilProduct(source="ML", title="SSD Kingston NV3 1TB NVMe", price_brl=500, url="a", query="ssd"),
            BrazilProduct(source="ML", title="SSD Kingston NV3 2TB NVMe", price_brl=900, url="b", query="ssd"),
        ]
    )
    one_tb = next(group for group in groups if group.capacity == "1TB")
    blacklist_path = tmp_path / "blacklist.csv"

    add_to_blacklist(one_tb, blacklist_path, "nao localizado")
    filtered = apply_ml_blacklist(groups, load_blacklist(blacklist_path))

    assert [group.capacity for group in filtered] == ["2TB"]
