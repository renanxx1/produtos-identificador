from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .collectors.mercadolivre_scraper import (
    ScraperBlockedError,
    load_brazil_products_csv,
    merge_brazil_products_csv,
    parse_search_html,
    scrape_search_products,
    write_brazil_products_csv,
)
from .config import load_dotenv


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="produtos-identificador")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape-ml", help="Coleta uma busca publica do Mercado Livre.")
    scrape_parser.add_argument("--query", default=os.getenv("ML_QUERY", "ssd nvme"), help="Termo de busca.")
    scrape_parser.add_argument("--limit", type=int, default=int(os.getenv("ML_LIMIT", "50")), help="Limite; use 0 para sem limite.")
    scrape_parser.add_argument("--out", default="output/ml/raw/ml_cdp.csv", help="CSV bruto do Mercado Livre.")
    scrape_parser.add_argument("--no-cache", action="store_true", help="Ignora HTML salvo em cache.")

    browser_parser = subparsers.add_parser("scrape-ml-browser", help="Coleta Mercado Livre com Playwright.")
    browser_parser.add_argument("--query", default=os.getenv("ML_QUERY", "ssd nvme"), help="Termo de busca.")
    browser_parser.add_argument("--limit", type=int, default=int(os.getenv("ML_LIMIT", "50")), help="Limite; use 0 para sem limite.")
    browser_parser.add_argument("--out", default="output/ml/raw/ml_cdp.csv", help="CSV bruto do Mercado Livre.")
    browser_parser.add_argument("--headless", action="store_true", help="Roda sem janela visivel.")
    browser_parser.add_argument("--wait", type=int, default=20, help="Segundos para aguardar carregamento inicial.")
    browser_parser.add_argument("--manual-wait", type=int, default=90, help="Segundos para aguardar verificacao manual.")
    browser_parser.add_argument("--channel", default=None, help="Canal Playwright, exemplo: chrome ou msedge.")
    browser_parser.add_argument("--user-data-dir", default=".browser/mercadolivre", help="Perfil persistente.")
    browser_parser.add_argument("--profile-directory", default=None, help="Perfil dentro do user-data-dir.")
    browser_parser.add_argument("--no-sandbox", action="store_true", help="Passa --no-sandbox ao navegador.")

    html_parser = subparsers.add_parser("parse-ml-html", help="Converte HTML salvo do Mercado Livre em CSV.")
    html_parser.add_argument("--html", required=True, help="Arquivo HTML salvo pelo navegador.")
    html_parser.add_argument("--limit", type=int, default=int(os.getenv("ML_LIMIT", "50")), help="Limite; use 0 para sem limite.")
    html_parser.add_argument("--out", default="output/ml/raw/ml_cdp.csv", help="CSV bruto do Mercado Livre.")

    profiles_parser = subparsers.add_parser("chrome-profiles", help="Lista perfis do Chrome.")
    profiles_parser.add_argument("--user-data-dir", default=None, help="Diretorio User Data do Chrome.")

    nav_parser = subparsers.add_parser("diagnose-ml-browser", help="Abre Chrome/Chromium e lista URLs das abas.")
    nav_parser.add_argument("--query", default=os.getenv("ML_QUERY", "ssd nvme"), help="Termo de busca.")
    nav_parser.add_argument("--channel", default=None, help="Canal Playwright, exemplo: chrome ou msedge.")
    nav_parser.add_argument("--user-data-dir", default=".browser/mercadolivre", help="Perfil persistente.")
    nav_parser.add_argument("--profile-directory", default=None, help="Perfil dentro do user-data-dir.")
    nav_parser.add_argument("--no-sandbox", action="store_true", help="Passa --no-sandbox ao navegador.")
    nav_parser.add_argument("--wait", type=int, default=15, help="Segundos para aguardar antes de listar abas.")

    cdp_diag_parser = subparsers.add_parser("diagnose-ml-cdp", help="Abre Chrome real via CDP e lista URLs das abas.")
    cdp_diag_parser.add_argument("--query", default=os.getenv("ML_QUERY", "ssd nvme"), help="Termo de busca.")
    cdp_diag_parser.add_argument("--user-data-dir", required=True, help="Diretorio User Data do Chrome.")
    cdp_diag_parser.add_argument("--profile-directory", default="Default", help="Perfil do Chrome.")
    cdp_diag_parser.add_argument("--port", type=int, default=9222, help="Porta CDP.")
    cdp_diag_parser.add_argument("--wait", type=int, default=10, help="Segundos para aguardar a porta CDP.")

    cdp_scrape_parser = subparsers.add_parser("scrape-ml-cdp", help="Coleta Mercado Livre conectando no Chrome real via CDP.")
    cdp_scrape_parser.add_argument("--query", default=os.getenv("ML_QUERY", "ssd nvme"), help="Termo de busca.")
    cdp_scrape_parser.add_argument("--limit", type=int, default=int(os.getenv("ML_LIMIT", "50")), help="Limite por pagina; use 0 para sem limite.")
    cdp_scrape_parser.add_argument("--out", default="output/ml/raw/ml_cdp.csv", help="CSV bruto do Mercado Livre.")
    cdp_scrape_parser.add_argument("--user-data-dir", required=True, help="Diretorio User Data do Chrome.")
    cdp_scrape_parser.add_argument("--profile-directory", default="Default", help="Perfil do Chrome.")
    cdp_scrape_parser.add_argument("--port", type=int, default=9222, help="Porta CDP.")
    cdp_scrape_parser.add_argument("--wait", type=int, default=15, help="Segundos para aguardar carregamento.")
    cdp_scrape_parser.add_argument("--pages", type=int, default=1, help="Paginas da busca para coletar.")
    cdp_scrape_parser.add_argument("--delay", type=float, default=2.0, help="Pausa entre paginas.")

    dedupe_parser = subparsers.add_parser("dedupe-ml", help="Agrupa anuncios iguais do Mercado Livre.")
    dedupe_parser.add_argument("--br-csv", default="output/ml/raw/ml_cdp.csv", help="CSV bruto do Mercado Livre.")
    dedupe_parser.add_argument("--out", default="output/ml/clean/ml_products_clean.csv", help="CSV limpo com produtos unicos.")

    args = parser.parse_args()

    if args.command == "scrape-ml":
        try:
            products = scrape_search_products(args.query, limit=args.limit, use_cache=not args.no_cache)
        except ScraperBlockedError as error:
            print(f"Scraper ML bloqueado: {error}", file=sys.stderr)
            raise SystemExit(3) from error
        _merge_and_print(products, args.out, args.query)
        return

    if args.command == "scrape-ml-browser":
        from .collectors.mercadolivre_browser import scrape_search_products_browser

        try:
            products = scrape_search_products_browser(
                args.query,
                limit=args.limit,
                headless=args.headless,
                wait_seconds=args.wait,
                manual_wait_seconds=args.manual_wait,
                channel=args.channel,
                user_data_dir=args.user_data_dir,
                no_sandbox=args.no_sandbox,
                profile_directory=args.profile_directory,
            )
        except (RuntimeError, ScraperBlockedError) as error:
            print(f"Scraper browser falhou: {error}", file=sys.stderr)
            raise SystemExit(3) from error
        _merge_and_print(products, args.out, args.query)
        return

    if args.command == "parse-ml-html":
        products = parse_search_html(Path(args.html).read_text(encoding="utf-8", errors="ignore"), limit=args.limit)
        write_brazil_products_csv(products, args.out)
        print(f"Produtos extraidos: {len(products)}")
        print(f"CSV salvo em: {args.out}")
        return

    if args.command == "chrome-profiles":
        from .chrome_profiles import default_chrome_user_data_dir, list_chrome_profiles

        user_data_dir = Path(args.user_data_dir) if args.user_data_dir else default_chrome_user_data_dir()
        profiles = list_chrome_profiles(user_data_dir)
        print(f"User Data: {user_data_dir}")
        print("directory | name | email | last_used")
        print("----------+------+-------+----------")
        for profile in profiles:
            print(f"{profile.directory} | {profile.name or '-'} | {profile.email or '-'} | {'yes' if profile.last_used else 'no'}")
        return

    if args.command == "diagnose-ml-browser":
        from .collectors.mercadolivre_browser import diagnose_browser_navigation

        try:
            urls = diagnose_browser_navigation(
                args.query,
                channel=args.channel,
                user_data_dir=args.user_data_dir,
                profile_directory=args.profile_directory,
                no_sandbox=args.no_sandbox,
                wait_seconds=args.wait,
            )
        except RuntimeError as error:
            print(f"Diagnostico falhou: {error}", file=sys.stderr)
            raise SystemExit(3) from error
        print("Abas abertas:")
        for url in urls:
            print(f"- {url}")
        return

    if args.command == "diagnose-ml-cdp":
        from .collectors.mercadolivre_browser import diagnose_browser_cdp

        try:
            urls = diagnose_browser_cdp(
                args.query,
                user_data_dir=args.user_data_dir,
                profile_directory=args.profile_directory,
                port=args.port,
                wait_seconds=args.wait,
            )
        except RuntimeError as error:
            print(f"Diagnostico CDP falhou: {error}", file=sys.stderr)
            raise SystemExit(3) from error
        print("Abas abertas via CDP:")
        for url in urls:
            print(f"- {url}")
        return

    if args.command == "scrape-ml-cdp":
        from .collectors.mercadolivre_browser import scrape_search_products_cdp

        try:
            products = scrape_search_products_cdp(
                args.query,
                limit=args.limit,
                user_data_dir=args.user_data_dir,
                profile_directory=args.profile_directory,
                port=args.port,
                wait_seconds=args.wait,
                pages=args.pages,
                delay_seconds=args.delay,
            )
        except (RuntimeError, ScraperBlockedError) as error:
            print(f"Scraper CDP falhou: {error}", file=sys.stderr)
            raise SystemExit(3) from error
        _merge_and_print(products, args.out, args.query)
        return

    if args.command == "dedupe-ml":
        from .ml_preprocess import dedupe_ml_products, write_ml_product_groups_csv

        products = load_brazil_products_csv(args.br_csv)
        groups = dedupe_ml_products(products)
        write_ml_product_groups_csv(groups, args.out)
        print(f"Anuncios lidos: {len(products)}")
        print(f"Produtos unicos: {len(groups)}")
        print(f"CSV salvo em: {args.out}")


def _merge_and_print(products, output_path: str, query: str) -> None:
    if not products:
        print("Nenhum produto extraido.", file=sys.stderr)
        raise SystemExit(3)
    merged = merge_brazil_products_csv(products, output_path, replace_query=query)
    print(f"Produtos coletados: {len(products)}")
    print(f"Total no CSV bruto: {len(merged)}")
    print(f"CSV salvo em: {output_path}")


if __name__ == "__main__":
    main()
