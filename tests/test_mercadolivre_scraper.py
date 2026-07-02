import pytest

from produtos_identificador.collectors.mercadolivre_scraper import (
    ScraperBlockedError,
    load_brazil_products_csv,
    merge_brazil_products_csv,
    parse_search_html,
)
from produtos_identificador.models import BrazilProduct


def test_parse_search_html_extracts_product_cards():
    html = """
    <ol>
      <li class="ui-search-layout__item">
        <a href="https://produto.mercadolivre.com.br/MLB-123">
          <h2 class="ui-search-item__title">SSD Samsung 990 Pro 2TB NVMe</h2>
          <span class="andes-money-amount__fraction">1.090</span>
          <span class="ui-search-reviews__rating-number">4,9 de 5</span>
          <span>380 vendidos</span>
        </a>
      </li>
    </ol>
    """

    products = parse_search_html(html)

    assert len(products) == 1
    assert products[0].title == "SSD Samsung 990 Pro 2TB NVMe"
    assert products[0].price_brl == 1090.0
    assert products[0].sold_quantity == 380
    assert products[0].rating == 4.9
    assert products[0].url == "https://produto.mercadolivre.com.br/MLB-123"


def test_parse_search_html_detects_block_page():
    with pytest.raises(ScraperBlockedError):
        parse_search_html("<html data-assets-prefix='suspicious-traffic-frontend'></html>")


def test_parse_search_html_limit_zero_does_not_cut_results():
    html = """
    <ol>
      <li class="ui-search-layout__item">
        <a href="https://produto.mercadolivre.com.br/MLB-123">
          <h2 class="ui-search-item__title">SSD Samsung 990 Pro 2TB NVMe</h2>
          <span class="andes-money-amount__fraction">1.090</span>
        </a>
      </li>
      <li class="ui-search-layout__item">
        <a href="https://produto.mercadolivre.com.br/MLB-456">
          <h2 class="ui-search-item__title">SSD Kingston NV3 1TB NVMe</h2>
          <span class="andes-money-amount__fraction">590</span>
        </a>
      </li>
    </ol>
    """

    products = parse_search_html(html, limit=0)

    assert len(products) == 2


def test_merge_brazil_products_csv_replaces_same_query_and_keeps_other_queries(tmp_path):
    csv_path = tmp_path / "ml_raw.csv"
    merge_brazil_products_csv(
        [
            BrazilProduct(source="ML", title="SSD antigo", price_brl=100, url="a", query="ssd nvme"),
            BrazilProduct(source="ML", title="Memoria RAM", price_brl=200, url="b", query="memoria ram"),
        ],
        csv_path,
        replace_query="ssd nvme",
    )

    merged = merge_brazil_products_csv(
        [BrazilProduct(source="ML", title="SSD novo", price_brl=90, url="c", query="ssd nvme")],
        csv_path,
        replace_query="ssd nvme",
    )

    titles = [product.title for product in merged]
    assert titles == ["Memoria RAM", "SSD novo"]
    assert [product.title for product in load_brazil_products_csv(csv_path)] == titles
