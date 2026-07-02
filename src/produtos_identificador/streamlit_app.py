from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from produtos_identificador.collectors.mercadolivre_browser import scrape_search_products_cdp
from produtos_identificador.collectors.mercadolivre_scraper import (
    load_brazil_products_csv,
    merge_brazil_products_csv,
    write_brazil_products_csv,
)
from produtos_identificador.config import cost_config_from_env, load_dotenv
from produtos_identificador.ml_preprocess import MlProductGroup, dedupe_ml_products, write_ml_product_groups_csv
from produtos_identificador.models import BrazilProduct, CostConfig, MatchResult, VietnamProduct
from produtos_identificador.pricing import calculate_opportunity


RAW_ML_PATH = Path("output/ml/raw/ml_cdp.csv")
CLEAN_ML_PATH = Path("output/ml/clean/ml_products_clean.csv")
MANUAL_SHOPEE_PATH = Path("data/manual/shopee_manual.csv")
BLACKLIST_PATH = Path("data/manual/ml_blacklist.csv")
OPPORTUNITIES_PATH = Path("output/reports/manual_opportunities.csv")

MANUAL_FIELDS = [
    "product_key",
    "enabled",
    "status",
    "discard_reason",
    "marketplace",
    "title",
    "price_vnd",
    "shipping_vnd",
    "url",
    "rating",
    "sold_quantity",
    "confidence",
    "notes",
]
MANUAL_TEXT_FIELDS = ["product_key", "status", "discard_reason", "marketplace", "title", "url", "notes"]
MANUAL_NUMERIC_FIELDS = ["price_vnd", "shipping_vnd", "rating", "sold_quantity", "confidence"]
MANUAL_STATUS_OPTIONS = ["pendente", "em pesquisa", "cadastrado", "descartado", "aprovado"]
DISCARD_REASON_OPTIONS = ["", "sem margem", "produto diferente", "frete alto", "variacao confusa", "pouca demanda", "preco VN instavel", "nao localizado"]
BLACKLIST_FIELDS = ["product_key", "search_query", "shopee_query", "reason", "created_at"]


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="Produtos Identificador", layout="wide")
    st.title("Produtos Identificador")
    st.caption("Mercado Livre agrupado, equivalentes Shopee manuais e calculo de margem.")

    config = sidebar_config()
    ml_path, manual_path, blacklist_path = sidebar_paths()

    tabs = st.tabs(["Extracao ML", "Produtos ML", "Shopee manual", "Oportunidades", "Blacklist"])
    with tabs[0]:
        render_ml_extraction(ml_path, blacklist_path)
    with tabs[1]:
        groups = load_ml_groups(ml_path["clean"])
        manual_df = load_manual_shopee(manual_path)
        render_ml_products(groups, ml_path, manual_df, blacklist_path)
    with tabs[2]:
        groups = load_ml_groups(ml_path["clean"])
        render_manual_shopee(groups, manual_path)
    with tabs[3]:
        groups = load_ml_groups(ml_path["clean"])
        manual_df = load_manual_shopee(manual_path)
        render_opportunities(groups, manual_df, config)
    with tabs[4]:
        groups = load_ml_groups(ml_path["clean"])
        render_blacklist(groups, ml_path, blacklist_path)


def sidebar_config() -> CostConfig:
    base = cost_config_from_env()
    with st.sidebar:
        st.header("Custos")
        brl_per_vnd = st.number_input("Cambio BRL por VND", min_value=0.0, value=float(base.brl_per_vnd), step=0.00001, format="%.6f")
        import_tax_rate = st.number_input("Imposto importacao", min_value=0.0, value=float(base.import_tax_rate), step=0.01, format="%.4f")
        icms_rate = st.number_input("ICMS", min_value=0.0, value=float(base.icms_rate), step=0.01, format="%.4f")
        ml_fee_rate = st.number_input("Taxa ML", min_value=0.0, value=float(base.ml_fee_rate), step=0.01, format="%.4f")
        payment_fee_rate = st.number_input("Taxa pagamento", min_value=0.0, value=float(base.payment_fee_rate), step=0.01, format="%.4f")
        fixed_cost_brl = st.number_input("Custo fixo BRL", min_value=0.0, value=float(base.fixed_cost_brl), step=1.0, format="%.2f")
        target_margin_rate = st.number_input("Margem alvo", min_value=0.0, value=float(base.target_margin_rate), step=0.01, format="%.4f")
    return CostConfig(
        brl_per_vnd=brl_per_vnd,
        import_tax_rate=import_tax_rate,
        icms_rate=icms_rate,
        ml_fee_rate=ml_fee_rate,
        payment_fee_rate=payment_fee_rate,
        fixed_cost_brl=fixed_cost_brl,
        target_margin_rate=target_margin_rate,
    )


def sidebar_paths() -> tuple[dict[str, Path], Path, Path]:
    with st.sidebar:
        st.header("Arquivos")
        raw_ml = Path(st.text_input("ML bruto", str(RAW_ML_PATH)))
        clean_ml = Path(st.text_input("ML agrupado", str(CLEAN_ML_PATH)))
        manual = Path(st.text_input("Shopee manual", str(MANUAL_SHOPEE_PATH)))
        blacklist = Path(st.text_input("Blacklist ML", str(BLACKLIST_PATH)))
    return {"raw": raw_ml, "clean": clean_ml}, manual, blacklist


def render_ml_extraction(ml_path: dict[str, Path], blacklist_path: Path) -> None:
    st.subheader("Extracao e agrupamento do Mercado Livre")
    st.write(
        "Use esta etapa para coletar anuncios do Mercado Livre. "
        "A busca atual substitui os registros antigos da mesma busca no CSV bruto e preserva as demais buscas."
    )

    col1, col2, col3 = st.columns(3)
    query = col1.text_input("Busca", "ssd nvme")
    pages = col2.number_input("Paginas", min_value=1, value=3, step=1)
    limit = col3.number_input("Limite por pagina", min_value=0, value=0, step=10, help="Use 0 para sem limite.")

    col4, col5, col6 = st.columns(3)
    user_data_dir = col4.text_input("Chrome user data dir", ".browser/ml-cdp")
    profile_directory = col5.text_input("Profile directory", "Default")
    port = col6.number_input("Porta CDP", min_value=9000, max_value=9999, value=9342, step=1)

    col7, col8 = st.columns(2)
    wait = col7.number_input("Espera por pagina (s)", min_value=5, value=20, step=1)
    delay = col8.number_input("Pausa entre paginas (s)", min_value=0.0, value=2.0, step=0.5)

    run = st.button("Coletar ML e agrupar", type="primary")
    if run:
        with st.status("Coletando Mercado Livre...", expanded=True) as status:
            try:
                products = scrape_search_products_cdp(
                    query,
                    limit=int(limit),
                    user_data_dir=user_data_dir,
                    profile_directory=profile_directory,
                    port=int(port),
                    wait_seconds=int(wait),
                    pages=int(pages),
                    delay_seconds=float(delay),
                )
                merged_products = merge_brazil_products_csv(products, ml_path["raw"], replace_query=query)
                st.write(f"Anuncios coletados: {len(products)}")
                st.write(f"Total acumulado no CSV bruto: {len(merged_products)}")
                groups = apply_ml_blacklist(dedupe_ml_products(merged_products), load_blacklist(blacklist_path))
                write_ml_product_groups_csv(groups, ml_path["clean"])
                st.write(f"Produtos agrupados: {len(groups)}")
                status.update(label="Extracao concluida.", state="complete")
                st.success(f"Arquivos atualizados: {ml_path['raw']} e {ml_path['clean']}")
            except Exception as error:
                status.update(label="Falha na extracao.", state="error")
                st.error(str(error))

    st.divider()
    st.subheader("Agrupar CSV bruto existente")
    if st.button("Reprocessar agrupamento do CSV bruto"):
        try:
            products = load_brazil_products_csv(ml_path["raw"])
            groups = apply_ml_blacklist(dedupe_ml_products(products), load_blacklist(blacklist_path))
            write_ml_product_groups_csv(groups, ml_path["clean"])
            st.success(f"Produtos agrupados: {len(groups)}")
        except Exception as error:
            st.error(str(error))


def render_ml_products(groups: list[MlProductGroup], ml_path: dict[str, Path], manual_df: pd.DataFrame, blacklist_path: Path) -> None:
    st.subheader("Produtos agrupados do Mercado Livre")
    if not groups:
        st.info("Nenhum produto agrupado encontrado. Rode a extracao ou reprocessamento primeiro.")
        return

    df = groups_to_df(groups)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Produtos", len(df))
    col2.metric("Anuncios agrupados", int(df["ads_count"].sum()))
    col3.metric("Menor preco", format_brl(float(df["best_price_brl"].min())))
    col4.metric("Vendas proxy", int(df["total_sold"].sum()))

    search = st.text_input("Filtrar produtos", "")
    only_without_manual = st.checkbox("Mostrar somente sem equivalente Shopee", value=False)
    view = df.copy()
    if only_without_manual:
        manual_keys = set(manual_df[manual_df["product_key"].astype(str).str.len() > 0]["product_key"].astype(str))
        view = view[~view["product_key"].astype(str).isin(manual_keys)]
    if search:
        mask = view.apply(lambda row: search.lower() in " ".join(map(str, row.values)).lower(), axis=1)
        view = view[mask]

    st.dataframe(
        view[
            [
                "search_query",
                "product_key",
                "brand",
                "model",
                "capacity",
                "best_price_brl",
                "ads_count",
                "total_sold",
                "max_rating",
                "shopee_query",
                "best_title",
                "best_url",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "best_price_brl": st.column_config.NumberColumn("Melhor preco BRL", format="R$ %.2f"),
            "best_url": st.column_config.LinkColumn("Melhor anuncio"),
        },
    )

    st.divider()
    st.subheader("Remover produto do ML")
    st.caption("Remove do CSV bruto todos os anuncios que pertencem ao produto agrupado selecionado e atualiza o agrupamento.")
    options = {
        f"{row.search_query or 'sem categoria'} | {row.shopee_query} | {format_brl(row.best_price_brl)}": row.product_key
        for row in groups
    }
    selected = st.selectbox("Produto para remover", list(options.keys()), key="remove_ml_product")
    confirm = st.checkbox("Confirmo que quero remover este produto do CSV bruto", key="confirm_remove_ml_product")
    if st.button("Remover produto selecionado", disabled=not confirm):
        removed = remove_ml_product_from_raw(options[selected], ml_path["raw"], ml_path["clean"])
        if removed:
            st.success(f"Produto removido. Anuncios removidos: {removed}. Atualize a pagina para ver a tabela sem ele.")
        else:
            st.warning("Nenhum anuncio correspondente foi encontrado no CSV bruto.")

    st.divider()
    st.subheader("Adicionar produto a blacklist")
    st.caption("Remove do agrupamento atual e impede que o produto volte a aparecer em novas extracoes/reprocessamentos.")
    blacklist_reason = st.selectbox("Motivo da blacklist", DISCARD_REASON_OPTIONS[1:], key="blacklist_reason_from_products")
    confirm_blacklist = st.checkbox("Confirmo que quero colocar este produto na blacklist", key="confirm_blacklist_product")
    if st.button("Adicionar selecionado a blacklist", disabled=not confirm_blacklist):
        selected_key = options[selected]
        selected_group = next((group for group in groups if group.product_key == selected_key), None)
        if selected_group:
            add_to_blacklist(selected_group, blacklist_path, blacklist_reason)
            groups_after = apply_ml_blacklist(load_ml_groups(ml_path["clean"]), load_blacklist(blacklist_path))
            write_ml_product_groups_csv(groups_after, ml_path["clean"])
            st.success("Produto adicionado a blacklist. Atualize a pagina para ver a tabela sem ele.")


def render_manual_shopee(groups: list[MlProductGroup], manual_path: Path) -> None:
    st.subheader("Cadastro manual de equivalentes Shopee/Vietna")
    if not groups:
        st.info("Carregue produtos agrupados do Mercado Livre antes de cadastrar equivalentes.")
        return

    manual_df = load_manual_shopee(manual_path)
    product_options = {
        f"{group.search_query or 'sem categoria'} | {group.shopee_query} | {format_brl(group.best_price_brl)}": group
        for group in groups
    }

    with st.form("manual_shopee_form", clear_on_submit=True):
        selected_label = st.selectbox("Produto ML", list(product_options.keys()))
        selected = product_options[selected_label]
        st.caption(f"Chave: {selected.product_key}")
        col1, col2 = st.columns(2)
        title = col1.text_input("Titulo Shopee / fornecedor")
        url = col2.text_input("URL")
        col3, col4, col5 = st.columns(3)
        price_vnd = col3.number_input("Preco VND", min_value=0.0, value=0.0, step=1000.0, format="%.0f")
        shipping_vnd = col4.number_input("Frete VND", min_value=0.0, value=0.0, step=1000.0, format="%.0f")
        confidence = col5.slider("Confianca do match", min_value=0.0, max_value=1.0, value=0.8, step=0.05)
        col6, col7, col8 = st.columns(3)
        rating = col6.number_input("Rating fornecedor", min_value=0.0, max_value=5.0, value=0.0, step=0.1)
        sold_quantity = col7.number_input("Vendas fornecedor", min_value=0, value=0, step=1)
        marketplace = col8.text_input("Marketplace", "Shopee VN")
        col9, col10 = st.columns(2)
        status = col9.selectbox("Status", MANUAL_STATUS_OPTIONS, index=2)
        discard_reason = col10.selectbox("Motivo descarte", DISCARD_REASON_OPTIONS)
        notes = st.text_area("Notas", "")
        submitted = st.form_submit_button("Adicionar equivalente", type="primary")

    if submitted:
        if not title and not url:
            st.warning("Informe ao menos titulo ou URL.")
        elif price_vnd <= 0:
            st.warning("Informe o preco em VND.")
        else:
            row = {
                "product_key": selected.product_key,
                "enabled": True,
                "status": status,
                "discard_reason": discard_reason,
                "marketplace": marketplace or "Shopee VN",
                "title": title or selected.shopee_query,
                "price_vnd": price_vnd,
                "shipping_vnd": shipping_vnd,
                "url": url,
                "rating": rating or "",
                "sold_quantity": sold_quantity,
                "confidence": confidence,
                "notes": notes,
            }
            manual_df = pd.concat([manual_df, pd.DataFrame([row])], ignore_index=True)
            save_manual_shopee(manual_df, manual_path)
            st.success("Equivalente adicionado.")

    st.divider()
    st.write("Equivalentes cadastrados")
    edited = st.data_editor(
        manual_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "enabled": st.column_config.CheckboxColumn("Ativo"),
            "status": st.column_config.SelectboxColumn("Status", options=MANUAL_STATUS_OPTIONS),
            "discard_reason": st.column_config.SelectboxColumn("Motivo descarte", options=DISCARD_REASON_OPTIONS),
            "price_vnd": st.column_config.NumberColumn("Preco VND", format="%.0f"),
            "shipping_vnd": st.column_config.NumberColumn("Frete VND", format="%.0f"),
            "url": st.column_config.LinkColumn("URL"),
            "confidence": st.column_config.NumberColumn("Confianca", min_value=0.0, max_value=1.0, format="%.2f"),
        },
    )
    if st.button("Salvar edicoes Shopee"):
        save_manual_shopee(edited, manual_path)
        st.success(f"CSV salvo em {manual_path}")


def render_opportunities(groups: list[MlProductGroup], manual_df: pd.DataFrame, config: CostConfig) -> None:
    st.subheader("Comparacao de valores e margem")
    if not groups:
        st.info("Nenhum produto ML agrupado encontrado.")
        return
    if manual_df.empty:
        st.info("Cadastre equivalentes Shopee manualmente para calcular oportunidades.")
        return

    status_filter = st.multiselect("Status manual", MANUAL_STATUS_OPTIONS, default=["cadastrado", "aprovado"])
    best_manual_only = st.checkbox("Usar apenas o melhor preco Shopee por produto ML", value=True)
    if status_filter:
        manual_df = manual_df[manual_df["status"].isin(status_filter)]
    opportunities = build_manual_opportunities(groups, manual_df, config, best_manual_only=best_manual_only)
    if not opportunities.empty:
        col1, col2, col3 = st.columns(3)
        min_margin = col1.slider("Margem minima", min_value=-1.0, max_value=1.0, value=0.0, step=0.05)
        only_enabled = col2.checkbox("Somente ativos", value=True)
        only_profitable = col3.checkbox("Somente lucro positivo", value=False)
        view = opportunities.copy()
        if only_enabled and "enabled" in view.columns:
            view = view[view["enabled"].astype(bool)]
        view = view[view["margin_rate"] >= min_margin]
        if only_profitable:
            view = view[view["gross_profit_brl"] > 0]
        view = view.sort_values(["score", "margin_rate", "gross_profit_brl"], ascending=False)
    else:
        view = opportunities

    if view.empty:
        st.warning("Nenhuma oportunidade dentro dos filtros atuais.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Oportunidades", len(view))
    col2.metric("Maior margem", f"{view['margin_rate'].max() * 100:.1f}%")
    col3.metric("Maior lucro", format_brl(float(view["gross_profit_brl"].max())))
    col4.metric("Score medio", f"{view['score'].mean():.0f}")

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ml_price_brl": st.column_config.NumberColumn("Venda BR", format="R$ %.2f"),
            "vn_price_vnd": st.column_config.NumberColumn("Preco VN", format="%.0f"),
            "landed_cost_brl": st.column_config.NumberColumn("Custo importado", format="R$ %.2f"),
            "marketplace_fees_brl": st.column_config.NumberColumn("Taxas ML", format="R$ %.2f"),
            "total_cost_brl": st.column_config.NumberColumn("Custo total", format="R$ %.2f"),
            "gross_profit_brl": st.column_config.NumberColumn("Lucro", format="R$ %.2f"),
            "margin_rate": st.column_config.NumberColumn("Margem", format="%.2f"),
            "ml_url": st.column_config.LinkColumn("ML"),
            "vn_url": st.column_config.LinkColumn("VN"),
        },
    )

    OPPORTUNITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    view.to_csv(OPPORTUNITIES_PATH, index=False, encoding="utf-8-sig")
    st.download_button(
        "Baixar CSV de oportunidades",
        view.to_csv(index=False).encode("utf-8-sig"),
        file_name="manual_opportunities.csv",
        mime="text/csv",
    )


def load_ml_groups(path: Path) -> list[MlProductGroup]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            rows.append(
                MlProductGroup(
                    product_key=row.get("product_key", ""),
                    search_query=row.get("search_query", ""),
                    brand=_optional(row.get("brand")),
                    model=_optional(row.get("model")),
                    capacity=_optional(row.get("capacity")),
                    storage_type=_optional(row.get("storage_type")),
                    form_factor=_optional(row.get("form_factor")),
                    interface=_optional(row.get("interface")),
                    shopee_query=row.get("shopee_query", ""),
                    ads_count=int(_float(row.get("ads_count"))),
                    best_price_brl=_float(row.get("best_price_brl")),
                    avg_price_brl=_float(row.get("avg_price_brl")),
                    max_price_brl=_float(row.get("max_price_brl")),
                    total_sold=int(_float(row.get("total_sold"))),
                    max_rating=_optional_float(row.get("max_rating")),
                    total_reviews=int(_float(row.get("total_reviews"))),
                    best_title=row.get("best_title", ""),
                    best_url=row.get("best_url", ""),
                    best_mlb_id=_optional(row.get("best_mlb_id")),
                    source_pages=row.get("source_pages", ""),
                    grouped_titles=row.get("grouped_titles", ""),
                )
            )
    return rows


def remove_ml_product_from_raw(product_key: str, raw_path: Path, clean_path: Path) -> int:
    products = load_brazil_products_csv(raw_path) if raw_path.exists() else []
    kept: list[BrazilProduct] = []
    removed = 0
    for product in products:
        group_key = dedupe_ml_products([product])[0].product_key if product.title and product.price_brl > 0 else ""
        if group_key == product_key:
            removed += 1
        else:
            kept.append(product)
    if not removed:
        return 0
    write_brazil_products_csv(kept, raw_path)
    write_ml_product_groups_csv(dedupe_ml_products(kept), clean_path)
    return removed


def render_blacklist(groups: list[MlProductGroup], ml_path: dict[str, Path], blacklist_path: Path) -> None:
    st.subheader("Blacklist de produtos ML")
    st.write("Produtos nesta lista sao removidos do agrupamento e nao aparecem nas proximas analises.")
    blacklist_df = load_blacklist(blacklist_path)
    edited = st.data_editor(
        blacklist_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "reason": st.column_config.SelectboxColumn("Motivo", options=DISCARD_REASON_OPTIONS[1:]),
        },
    )
    col1, col2 = st.columns(2)
    if col1.button("Salvar blacklist"):
        save_blacklist(edited, blacklist_path)
        reprocess_grouping_with_blacklist(ml_path["raw"], ml_path["clean"], blacklist_path)
        st.success("Blacklist salva e agrupamento reprocessado.")
    if col2.button("Reprocessar agrupamento aplicando blacklist"):
        total = reprocess_grouping_with_blacklist(ml_path["raw"], ml_path["clean"], blacklist_path)
        st.success(f"Produtos agrupados apos blacklist: {total}")

    if groups:
        st.divider()
        st.write("Adicionar produto atual a blacklist")
        options = {
            f"{group.search_query or 'sem categoria'} | {group.shopee_query} | {format_brl(group.best_price_brl)}": group
            for group in groups
        }
        selected_label = st.selectbox("Produto", list(options.keys()), key="blacklist_tab_product")
        reason = st.selectbox("Motivo", DISCARD_REASON_OPTIONS[1:], key="blacklist_tab_reason")
        if st.button("Adicionar a blacklist", key="blacklist_tab_add"):
            add_to_blacklist(options[selected_label], blacklist_path, reason)
            total = reprocess_grouping_with_blacklist(ml_path["raw"], ml_path["clean"], blacklist_path)
            st.success(f"Adicionado. Produtos agrupados apos blacklist: {total}")


def load_blacklist(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=BLACKLIST_FIELDS)
    df = pd.read_csv(path, encoding="utf-8-sig", dtype="string")
    for field in BLACKLIST_FIELDS:
        if field not in df.columns:
            df[field] = ""
    for field in BLACKLIST_FIELDS:
        df[field] = df[field].fillna("").astype(str).astype("object")
    return df[BLACKLIST_FIELDS]


def save_blacklist(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = df.copy()
    for field in BLACKLIST_FIELDS:
        if field not in clean.columns:
            clean[field] = ""
        clean[field] = clean[field].fillna("").astype(str)
    clean = clean[clean["product_key"].astype(str).str.len() > 0]
    clean = clean.drop_duplicates(subset=["product_key"], keep="last")
    clean[BLACKLIST_FIELDS].to_csv(path, index=False, encoding="utf-8-sig")


def add_to_blacklist(group: MlProductGroup, path: Path, reason: str) -> None:
    df = load_blacklist(path)
    row = {
        "product_key": group.product_key,
        "search_query": group.search_query,
        "shopee_query": group.shopee_query,
        "reason": reason,
        "created_at": pd.Timestamp.now().isoformat(timespec="seconds"),
    }
    save_blacklist(pd.concat([df, pd.DataFrame([row])], ignore_index=True), path)


def apply_ml_blacklist(groups: list[MlProductGroup], blacklist_df: pd.DataFrame) -> list[MlProductGroup]:
    if blacklist_df.empty:
        return groups
    blocked = set(blacklist_df["product_key"].fillna("").astype(str))
    return [group for group in groups if group.product_key not in blocked]


def reprocess_grouping_with_blacklist(raw_path: Path, clean_path: Path, blacklist_path: Path) -> int:
    products = load_brazil_products_csv(raw_path) if raw_path.exists() else []
    groups = apply_ml_blacklist(dedupe_ml_products(products), load_blacklist(blacklist_path))
    write_ml_product_groups_csv(groups, clean_path)
    return len(groups)


def load_manual_shopee(path: Path) -> pd.DataFrame:
    if not path.exists():
        return normalize_manual_shopee_df(pd.DataFrame(columns=MANUAL_FIELDS))
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={field: "string" for field in MANUAL_TEXT_FIELDS})
    return normalize_manual_shopee_df(df)


def normalize_manual_shopee_df(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.copy()
    for field in MANUAL_FIELDS:
        if field not in clean.columns:
            clean[field] = "" if field != "enabled" else True
    for field in MANUAL_TEXT_FIELDS:
        clean[field] = clean[field].fillna("").astype(str).astype("object")
    clean["status"] = clean["status"].replace("", "cadastrado")
    clean["discard_reason"] = clean["discard_reason"].fillna("").astype(str)
    clean["enabled"] = clean["enabled"].apply(_truthy).astype(bool)
    for field in MANUAL_NUMERIC_FIELDS:
        clean[field] = clean[field].apply(_float)
    clean["sold_quantity"] = clean["sold_quantity"].astype(int)
    if "confidence" in clean.columns:
        clean["confidence"] = clean["confidence"].replace(0, 0.8)
    return clean[MANUAL_FIELDS]


def save_manual_shopee(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = normalize_manual_shopee_df(df)
    clean[MANUAL_FIELDS].to_csv(path, index=False, encoding="utf-8-sig")


def build_manual_opportunities(
    groups: list[MlProductGroup],
    manual_df: pd.DataFrame,
    config: CostConfig,
    *,
    best_manual_only: bool = True,
) -> pd.DataFrame:
    by_key = {group.product_key: group for group in groups}
    rows = []
    candidate_df = best_manual_rows(manual_df) if best_manual_only else manual_df
    for _, row in candidate_df.iterrows():
        group = by_key.get(str(row.get("product_key", "")))
        if not group or not _truthy(row.get("enabled", True)):
            continue
        vn_price = _float(row.get("price_vnd"))
        if vn_price <= 0:
            continue
        br = BrazilProduct(
            source="Mercado Livre agrupado",
            title=group.best_title,
            price_brl=group.best_price_brl,
            url=group.best_url,
            sold_quantity=group.total_sold,
            rating=group.max_rating,
            reviews=group.total_reviews,
            brand=group.brand,
            model=group.model,
            mlb_id=group.best_mlb_id,
        )
        vn = VietnamProduct(
            marketplace=str(row.get("marketplace") or "Shopee VN"),
            title=str(row.get("title") or group.shopee_query),
            price_vnd=vn_price,
            shipping_vnd=_float(row.get("shipping_vnd")),
            url=str(row.get("url") or ""),
            rating=_optional_float(row.get("rating")),
            sold_quantity=int(_float(row.get("sold_quantity"))),
        )
        match = MatchResult(True, max(0.0, min(1.0, _float(row.get("confidence")) or 0.8)), "Cadastro manual")
        opp = calculate_opportunity(br, vn, match, config)
        rows.append(
            {
                "product_key": group.product_key,
                "search_query": group.search_query,
                "ml_product": group.shopee_query or group.best_title,
                "vn_product": vn.title,
                "enabled": _truthy(row.get("enabled", True)),
                "ml_price_brl": br.price_brl,
                "vn_price_vnd": vn.price_vnd,
                "vn_shipping_vnd": vn.shipping_vnd,
                "landed_cost_brl": opp.landed_cost_brl,
                "marketplace_fees_brl": opp.marketplace_fees_brl,
                "total_cost_brl": opp.total_cost_brl,
                "gross_profit_brl": opp.gross_profit_brl,
                "margin_rate": opp.margin_rate,
                "score": opp.score,
                "ml_sales_proxy": br.sold_quantity,
                "match_confidence": match.confidence,
                "ml_url": br.url,
                "vn_url": vn.url,
                "notes": row.get("notes", ""),
            }
        )
    return pd.DataFrame(rows)


def best_manual_rows(manual_df: pd.DataFrame) -> pd.DataFrame:
    if manual_df.empty or "product_key" not in manual_df.columns:
        return manual_df
    candidates = manual_df.copy()
    candidates = candidates[candidates.apply(lambda row: _truthy(row.get("enabled", True)), axis=1)]
    candidates["_landed_vnd"] = candidates.apply(lambda row: _float(row.get("price_vnd")) + _float(row.get("shipping_vnd")), axis=1)
    candidates = candidates[candidates["_landed_vnd"] > 0]
    if candidates.empty:
        return candidates.drop(columns=["_landed_vnd"], errors="ignore")
    best_indexes = candidates.sort_values(["product_key", "_landed_vnd"]).groupby("product_key", sort=False).head(1).index
    return manual_df.loc[best_indexes]


def groups_to_df(groups: list[MlProductGroup]) -> pd.DataFrame:
    return pd.DataFrame([asdict(group) for group in groups])


def format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _float(value) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0.0


def _optional(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    result = _float(value)
    return result if result > 0 else None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "false", "nao", "não", "no"}


if __name__ == "__main__":
    main()
