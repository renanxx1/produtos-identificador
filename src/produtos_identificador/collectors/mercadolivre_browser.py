from __future__ import annotations

import os
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from ..models import BrazilProduct
from .mercadolivre_scraper import SEARCH_BASE, ScraperBlockedError, parse_search_html


RESULTS_PER_PAGE = 48


def scrape_search_products_browser(
    query: str,
    *,
    limit: int = 50,
    user_data_dir: str | Path = ".browser/mercadolivre",
    headless: bool = False,
    wait_seconds: int = 20,
    manual_wait_seconds: int = 90,
    debug_html_path: str | Path = "output/debug/ml_browser_debug.html",
    channel: str | None = None,
    no_sandbox: bool = False,
    profile_directory: str | None = None,
    launch_timeout_ms: int = 30_000,
) -> list[BrazilProduct]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright nao esta instalado. Rode: .\\.venv\\Scripts\\python.exe -m pip install -e \".[browser]\""
        ) from error

    url = build_search_url(query)
    profile_dir = Path(user_data_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    _ensure_profile_is_available(profile_dir)

    with sync_playwright() as playwright:
        launch_options = {
            "headless": headless,
            "locale": "pt-BR",
            "timeout": launch_timeout_ms,
            "viewport": {"width": 1366, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
        }
        if channel:
            launch_options["channel"] = channel
        chromium_args = []
        if no_sandbox:
            launch_options["chromium_sandbox"] = False
            chromium_args.append("--no-sandbox")
        if profile_directory:
            chromium_args.append(f"--profile-directory={profile_directory}")
        if chromium_args:
            launch_options["args"] = chromium_args
        context = None
        try:
            context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_options)
            page = context.new_page()
            page.bring_to_front()
            print(f"Abrindo Mercado Livre: {url}")
            _navigate_page(page, url)
            if page.url == "about:blank":
                if headless:
                    raise RuntimeError(
                        "O navegador abriu, mas permaneceu em about:blank. "
                        "Rode sem --headless para navegar manualmente ou use um perfil dedicado."
                    )
                print(
                    "O Chrome permaneceu em about:blank. Na janela aberta, acesse manualmente "
                    f"{url}; vou aguardar ate {manual_wait_seconds}s..."
                )
                deadline = time.monotonic() + manual_wait_seconds
                while time.monotonic() < deadline:
                    page.wait_for_timeout(3000)
                    page = _select_best_page(context, page)
                    if page.url != "about:blank":
                        break
            if page.url == "about:blank":
                _navigate_page(page, url)
            page.wait_for_load_state("domcontentloaded", timeout=30_000)
            page.bring_to_front()
            page = _select_best_page(context, page)
            _try_accept_cookies(page)
            page.wait_for_timeout(wait_seconds * 1000)
            _scroll_results(page)
            html = page.content()

            if _needs_manual_verification(html) and not headless:
                print(
                    "Mercado Livre abriu verificacao. Resolva na janela do navegador; "
                    f"vou aguardar ate {manual_wait_seconds}s..."
                )
                deadline = time.monotonic() + manual_wait_seconds
                while time.monotonic() < deadline:
                    page.wait_for_timeout(3000)
                    html = page.content()
                    if not _needs_manual_verification(html):
                        break
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(wait_seconds * 1000)
                _scroll_results(page)
                html = page.content()

            products = _extract_products_from_dom(page, limit=limit, query=query, page_number=1)
            if not products:
                products = parse_search_html(html, limit=limit)
            if not products:
                _write_debug_html(html, debug_html_path)
                raise RuntimeError(
                    "Navegador carregou a pagina, mas nenhum produto foi extraido. "
                    f"HTML de diagnostico salvo em {debug_html_path}."
                )
            return products if limit <= 0 else products[:limit]
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Timeout ao iniciar/carregar o navegador. Se estiver usando o perfil real do Chrome, "
                "feche todas as janelas/processos do Chrome e tente novamente."
            ) from error
        except ScraperBlockedError:
            raise
        finally:
            if context:
                context.close()


def _try_accept_cookies(page) -> None:
    labels = ["Aceitar cookies", "Aceitar", "Entendi", "Continuar"]
    for label in labels:
        try:
            button = page.get_by_role("button", name=label)
            if button.count() > 0:
                button.first.click(timeout=1500)
                return
        except Exception:
            continue


def _navigate_page(page, url: str) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        pass
    if _is_target_page(page, url):
        return

    try:
        page.evaluate("(target) => { window.location.href = target; }", url)
        page.wait_for_timeout(3000)
    except Exception:
        pass
    if _is_target_page(page, url):
        return

    page.bring_to_front()
    page.keyboard.press("Control+L")
    page.keyboard.type(url)
    page.keyboard.press("Enter")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=60_000)
    except Exception:
        page.wait_for_timeout(5000)


def _is_target_page(page, url: str) -> bool:
    try:
        current = urllib.parse.unquote(page.url.lower())
    except Exception:
        return False
    if current == "about:blank":
        return False
    target = urllib.parse.urlparse(url.lower())
    target_host = target.netloc.lower()
    target_path = urllib.parse.unquote(target.path.lower())
    return target_host in current and target_path in current


def _scroll_results(page) -> None:
    for _ in range(6):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(1200)


def _write_debug_html(html: str, path: str | Path) -> None:
    debug_path = Path(path)
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(html, encoding="utf-8", errors="ignore")


def _needs_manual_verification(html: str) -> bool:
    lowered = html.lower()
    return "suspicious-traffic" in lowered or "account-verification" in lowered or "captcha" in lowered


def _select_best_page(context, fallback_page):
    pages = list(context.pages)
    if not pages:
        return fallback_page
    for page in reversed(pages):
        try:
            url = page.url.lower()
        except Exception:
            continue
        if "mercadolivre.com" in url and url != "about:blank":
            try:
                page.bring_to_front()
            except Exception:
                pass
            return page
    return fallback_page


def _wait_for_non_blank_page(context, *, timeout_ms: int):
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        for page in reversed(list(context.pages)):
            try:
                if page.url and page.url != "about:blank":
                    return page
            except Exception:
                continue
        time.sleep(0.5)
    return None


def build_search_url(query: str, page_number: int = 1) -> str:
    slug = urllib.parse.quote(query.replace(" ", "-"))
    if page_number <= 1:
        return SEARCH_BASE.format(query=slug)
    offset = 1 + ((page_number - 1) * RESULTS_PER_PAGE)
    return f"{SEARCH_BASE.format(query=slug)}_Desde_{offset}_NoIndex_True"


def _extract_products_from_dom(page, *, limit: int, query: str | None = None, page_number: int | None = None) -> list[BrazilProduct]:
    raw_products = page.evaluate(
        """
        ({ limit, query, pageNumber }) => {
          const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
          const getMlbId = (url) => {
            const decoded = decodeURIComponent(url || '');
            const patterns = [
              /[?&#]wid=(MLB\\d+)/i,
              /[?&#]item_id=(MLB\\d+)/i,
              /\\/(MLB-?\\d+)/i
            ];
            for (const pattern of patterns) {
              const match = decoded.match(pattern);
              if (match) return match[1].replace('-', '').toUpperCase();
            }
            return '';
          };
          const moneyToNumber = (value) => {
            const match = clean(value).match(/(?:R\\$\\s*)?([0-9.]+)(?:,([0-9]{2}))?/);
            if (!match) return 0;
            const integer = match[1].replace(/\\./g, '');
            const cents = match[2] || '00';
            return Number(`${integer}.${cents}`);
          };
          const soldToNumber = (value) => {
            const text = clean(value).toLowerCase();
            const match = text.match(/([0-9]+)\\s*(mil\\s*)?vendidos?/);
            if (!match) return 0;
            const amount = Number(match[1]);
            return match[2] ? amount * 1000 : amount;
          };
          const selectors = [
            'li.ui-search-layout__item',
            '.ui-search-result',
            '.poly-card',
            '[class*="poly-card"]',
            '[class*="ui-search-layout__item"]'
          ];
          const cards = Array.from(document.querySelectorAll(selectors.join(',')));
          const seen = new Set();
          const products = [];
          let visiblePosition = 0;
          for (const card of cards) {
            const link = card.querySelector('a[href*="/MLB-"], a[href*="produto.mercadolivre"], a[href*="mercadolivre.com.br"]');
            const url = link ? link.href : '';
            if (!url || seen.has(url)) continue;
            const titleNode = card.querySelector('.ui-search-item__title, .poly-component__title, h2, h3, [class*="title"]');
            const title = clean(titleNode?.innerText || titleNode?.textContent || link.getAttribute('title') || link.getAttribute('aria-label'));
            if (/aproveite|frete gratis|frete grátis|produtos relacionados|mais opcoes|mais opções/i.test(title)) continue;
            const priceNode = card.querySelector(
              '[itemprop="price"], .andes-money-amount, .andes-money-amount__fraction, [class*="money-amount"], [aria-label*="reais"]'
            );
            const price = Number(priceNode?.getAttribute('content')) || moneyToNumber(priceNode?.getAttribute('aria-label') || priceNode?.innerText || card.innerText);
            if (!title || !price) continue;
            const text = clean(card.innerText || '');
            if (/origin_type=cart_intervention|frete_full_fullfilter/i.test(url)) continue;
            visiblePosition += 1;
            const ratingMatch = text.match(/([0-9],[0-9])\\s*(?:de\\s*5|estrelas)?/i);
            const reviewsMatch = text.match(/\\(([0-9.]+)\\)/);
            const isAd = /is_advertising=true|type=pad|\\/mclics\\/clicks/i.test(url);
            products.push({
              source: 'Mercado Livre Browser',
              title,
              price_brl: price,
              url,
              sold_quantity: soldToNumber(text),
              rating: ratingMatch ? Number(ratingMatch[1].replace(',', '.')) : null,
              reviews: reviewsMatch ? Number(reviewsMatch[1].replace(/\\./g, '')) : 0,
              brand: null,
              model: null,
              query,
              page: pageNumber,
              position: visiblePosition,
              is_ad: isAd,
              mlb_id: getMlbId(url)
            });
            seen.add(url);
            if (limit > 0 && products.length >= limit) break;
          }
          return products;
        }
        """,
        {"limit": limit, "query": query, "pageNumber": page_number},
    )
    products: list[BrazilProduct] = []
    for item in raw_products:
        products.append(
            BrazilProduct(
                source=str(item.get("source") or "Mercado Livre Browser"),
                title=str(item.get("title") or ""),
                price_brl=float(item.get("price_brl") or 0),
                url=str(item.get("url") or ""),
                sold_quantity=int(item.get("sold_quantity") or 0),
                rating=float(item["rating"]) if item.get("rating") is not None else None,
                reviews=int(item.get("reviews") or 0),
                brand=item.get("brand"),
                model=item.get("model"),
                query=item.get("query"),
                page=int(item.get("page") or 0) or None,
                position=int(item.get("position") or 0) or None,
                is_ad=bool(item.get("is_ad")),
                mlb_id=item.get("mlb_id") or None,
            )
        )
    return products


def diagnose_browser_navigation(
    query: str,
    *,
    user_data_dir: str | Path = ".browser/mercadolivre",
    channel: str | None = None,
    profile_directory: str | None = None,
    no_sandbox: bool = False,
    wait_seconds: int = 15,
) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright nao esta instalado. Rode: .\\.venv\\Scripts\\python.exe -m pip install -e \".[browser]\""
        ) from error

    url = build_search_url(query)
    profile_dir = Path(user_data_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    _ensure_profile_is_available(profile_dir)

    with sync_playwright() as playwright:
        chromium_args = []
        if no_sandbox:
            chromium_args.append("--no-sandbox")
        if profile_directory:
            chromium_args.append(f"--profile-directory={profile_directory}")
        launch_options = {
            "headless": False,
            "locale": "pt-BR",
            "timeout": 30_000,
        }
        if chromium_args:
            launch_options["args"] = chromium_args
        if channel:
            launch_options["channel"] = channel
        context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_options)
        try:
            page = context.new_page()
            page.bring_to_front()
            _navigate_page(page, url)
            time.sleep(wait_seconds)
            urls = []
            for page in context.pages:
                try:
                    urls.append(page.url)
                except Exception:
                    urls.append("<erro ao ler url>")
            return urls
        finally:
            context.close()


def diagnose_browser_cdp(
    query: str,
    *,
    user_data_dir: str | Path,
    profile_directory: str = "Default",
    port: int = 9222,
    wait_seconds: int = 10,
) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright nao esta instalado. Rode: .\\.venv\\Scripts\\python.exe -m pip install -e \".[browser]\""
        ) from error

    url = SEARCH_BASE.format(query=urllib.parse.quote(query.replace(" ", "-")))
    _launch_chrome_cdp(url, user_data_dir=user_data_dir, profile_directory=profile_directory, port=port)
    _wait_for_cdp(port, timeout_seconds=wait_seconds)

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            _navigate_page(page, url)
            urls: list[str] = []
            for context in browser.contexts:
                for page in context.pages:
                    urls.append(page.url)
            return urls
        finally:
            browser.close()


def scrape_search_products_cdp(
    query: str,
    *,
    limit: int = 50,
    user_data_dir: str | Path,
    profile_directory: str = "Default",
    port: int = 9222,
    wait_seconds: int = 15,
    pages: int = 1,
    delay_seconds: float = 2.0,
) -> list[BrazilProduct]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright nao esta instalado. Rode: .\\.venv\\Scripts\\python.exe -m pip install -e \".[browser]\""
        ) from error

    url = build_search_url(query)
    _launch_chrome_cdp(url, user_data_dir=user_data_dir, profile_directory=profile_directory, port=port)
    _wait_for_cdp(port, timeout_seconds=wait_seconds)

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        try:
            browser_pages = [page for context in browser.contexts for page in context.pages]
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            _navigate_page(page, url)
            browser_pages.append(page)
            page = _best_page_for_url(browser_pages, url)
            if page is None:
                raise RuntimeError("Chrome abriu, mas nao encontrei aba do Mercado Livre via CDP.")
            all_products: list[BrazilProduct] = []
            seen: set[str] = set()
            page_url = url
            for page_number in range(1, max(1, pages) + 1):
                _navigate_page(page, page_url)
                page.bring_to_front()
                page.wait_for_timeout(wait_seconds * 1000)
                _scroll_results(page)
                products = _extract_products_from_dom(page, limit=limit, query=query, page_number=page_number)
                if not products:
                    html = page.content()
                    products = parse_search_html(html, limit=limit)
                for product in products:
                    key = product.mlb_id or _mlb_id_from_url(product.url) or product.url
                    if key and key in seen:
                        continue
                    if key:
                        seen.add(key)
                    all_products.append(product)
                if page_number < max(1, pages):
                    next_page_url = _find_next_page_url(page)
                    if next_page_url and not _same_navigation_url(next_page_url, page.url):
                        page_url = next_page_url
                    else:
                        page_url = build_search_url(query, page_number + 1)
                    time.sleep(delay_seconds)
            return all_products
        finally:
            browser.close()


def _launch_chrome_cdp(
    url: str,
    *,
    user_data_dir: str | Path,
    profile_directory: str,
    port: int,
) -> None:
    chrome_path = _find_chrome_exe()
    if not chrome_path:
        raise RuntimeError("Nao encontrei chrome.exe em C:\\Program Files ou C:\\Program Files (x86).")
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={Path(user_data_dir).resolve()}",
        f"--profile-directory={profile_directory}",
        "--new-window",
        url,
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_cdp(port: int, *, timeout_seconds: int) -> None:
    endpoint = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=2) as response:
                json.loads(response.read().decode("utf-8"))
                return
        except Exception as error:
            last_error = error
            time.sleep(0.5)
    raise RuntimeError(
        f"Chrome nao abriu a porta CDP {port}. Feche outros Chromes ou tente outra porta. "
        "Se voce estiver usando o perfil real do Chrome, ele pode abrir a pagina e ainda assim ignorar "
        "a porta de depuracao. Nesse caso use um perfil dedicado, por exemplo .browser\\ml-cdp. "
        f"Ultimo erro: {last_error}"
    )


def _find_chrome_exe() -> str | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _find_next_page_url(page) -> str | None:
    try:
        next_url = page.evaluate(
            """
            () => {
              const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
              const normalize = (value) => clean(value)
                .toLowerCase()
                .normalize('NFD')
                .replace(/[\\u0300-\\u036f]/g, '');
              const anchors = Array.from(document.querySelectorAll('a[href]'));
              for (const anchor of anchors) {
                const label = normalize([
                  anchor.innerText,
                  anchor.textContent,
                  anchor.getAttribute('aria-label'),
                  anchor.getAttribute('title')
                ].filter(Boolean).join(' '));
                const rel = normalize(anchor.getAttribute('rel'));
                const classes = normalize(anchor.className);
                if (
                  rel === 'next' ||
                  label.includes('seguinte') ||
                  label.includes('proxima') ||
                  classes.includes('pagination--next')
                ) {
                  return anchor.href;
                }
              }
              return null;
            }
            """
        )
    except Exception:
        return None
    if not next_url:
        return None
    return str(next_url)


def _same_navigation_url(left: str, right: str) -> bool:
    left_parts = urllib.parse.urlparse(left)
    right_parts = urllib.parse.urlparse(right)
    return (
        left_parts.netloc.lower() == right_parts.netloc.lower()
        and left_parts.path.rstrip("/").lower() == right_parts.path.rstrip("/").lower()
    )


def _best_page_for_url(pages, target_url: str):
    target_query = urllib.parse.urlparse(target_url).path.lower()
    for page in reversed(pages):
        try:
            url = page.url.lower()
        except Exception:
            continue
        if "mercadolivre.com" in url and target_query in url:
            return page
    for page in reversed(pages):
        try:
            if "mercadolivre.com" in page.url.lower():
                return page
        except Exception:
            continue
    return pages[-1] if pages else None


def _mlb_id_from_url(url: str) -> str | None:
    decoded = urllib.parse.unquote(url or "")
    for pattern in [r"[?&#]wid=(MLB\d+)", r"[?&#]item_id=(MLB\d+)", r"/(MLB-?\d+)"]:
        match = re.search(pattern, decoded, flags=re.IGNORECASE)
        if match:
            return match.group(1).replace("-", "").upper()
    return None


def _ensure_profile_is_available(profile_dir: Path) -> None:
    if os.name != "nt" or not _is_default_chrome_user_data(profile_dir):
        return
    if _is_chrome_running_with_user_data(profile_dir):
        raise RuntimeError(
            "O perfil real do Chrome ja esta em uso. Feche todas as janelas/processos do Chrome "
            "antes de usar --user-data-dir apontando para Google\\Chrome\\User Data, ou use um perfil dedicado "
            "como .browser\\ml-chrome."
        )


def _is_default_chrome_user_data(profile_dir: Path) -> bool:
    normalized = str(profile_dir.resolve()).lower().replace("/", "\\")
    return normalized.endswith("\\google\\chrome\\user data")


def _is_chrome_running_with_user_data(profile_dir: Path) -> bool:
    expected = str(profile_dir.resolve()).lower().replace("/", "\\")
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"name = 'chrome.exe'\" | Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return False
    output = result.stdout.lower().replace("/", "\\")
    return expected in output
