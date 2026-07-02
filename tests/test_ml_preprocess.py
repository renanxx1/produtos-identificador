from produtos_identificador.ml_preprocess import build_product_signature, dedupe_ml_products
from produtos_identificador.models import BrazilProduct


def test_build_product_signature_extracts_shopee_query():
    signature = build_product_signature("Ssd Kingston Nv3 1tb Nvme 4.0 Azul Escuro 2280 SNV3S/1000G")

    assert signature.brand == "Kingston"
    assert signature.model == "NV3"
    assert signature.capacity == "1TB"
    assert signature.storage_type == "NVMe"
    assert signature.shopee_query.startswith("Kingston NV3 1TB")


def test_dedupe_ml_products_groups_equivalent_ads_and_keeps_lowest_price():
    products = [
        BrazilProduct(
            source="ML",
            title="SSD Kingston NV3 1TB M2 2280 NVME PCIe 4.0",
            price_brl=1099,
            url="https://example.com/a",
            sold_quantity=10,
            query="ssd nvme",
            mlb_id="MLB1",
        ),
        BrazilProduct(
            source="ML",
            title="Ssd Kingston Nv3 1tb Nvme 4.0 Azul Escuro 2280 SNV3S/1000G",
            price_brl=962,
            url="https://example.com/b",
            sold_quantity=5,
            query="ssd nvme",
            mlb_id="MLB2",
        ),
        BrazilProduct(
            source="ML",
            title="Ssd Kingston Nv3 2tb Nvme 4.0 Azul Escuro 2280 SNV3S/2000G",
            price_brl=1799,
            url="https://example.com/c",
            sold_quantity=3,
            query="ssd nvme",
            mlb_id="MLB3",
        ),
    ]

    groups = dedupe_ml_products(products)

    assert len(groups) == 2
    one_tb = next(group for group in groups if group.capacity == "1TB")
    assert one_tb.ads_count == 2
    assert one_tb.best_price_brl == 962
    assert one_tb.best_mlb_id == "MLB2"
    assert one_tb.search_query == "ssd nvme"
    assert one_tb.shopee_query.startswith("Kingston NV3 1TB")
