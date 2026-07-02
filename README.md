# Produtos Identificador

Ferramenta para mapear oportunidades de revenda a partir do Mercado Livre Brasil.

O fluxo atual automatiza a coleta e o agrupamento dos anuncios do Mercado Livre. A busca do equivalente na Shopee/fornecedor fica manual dentro do Streamlit, para evitar CAPTCHA e manter o processo simples de operar.

## Fluxo Atual

1. Coleta produtos do Mercado Livre por termo de busca.
2. Salva os anuncios brutos em `output/ml/raw/ml_cdp.csv`.
3. Agrupa anuncios equivalentes e mantem o menor preco por produto.
4. Aplica blacklist para esconder produtos que voce nao quer revisar novamente.
5. Permite cadastrar manualmente um ou mais equivalentes Shopee/fornecedor por produto.
6. Usa o melhor custo cadastrado para calcular margem, lucro e score.
7. Gera relatorio em `output/reports/manual_opportunities.csv`.

## Instalar

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[all]"
```

## Rodar o Dashboard

```powershell
.\.venv\Scripts\streamlit.exe run src/produtos_identificador/streamlit_app.py
```

## Arquivos Principais

```text
output/ml/raw/ml_cdp.csv              # anuncios brutos coletados do ML
output/ml/clean/ml_products_clean.csv # produtos agrupados com melhor preco
data/manual/shopee_manual.csv         # equivalentes Shopee/fornecedor cadastrados manualmente
data/manual/ml_blacklist.csv          # produtos ignorados nas proximas analises
output/reports/manual_opportunities.csv
```

## Como Usar

1. Abra o Streamlit.
2. Na aba `Extracao ML`, informe a busca, exemplo `ssd nvme`.
3. Rode a coleta. O sistema faz append para buscas novas.
4. Se repetir a mesma busca, os registros antigos daquela busca sao removidos e substituidos pelos novos.
5. Na aba `Produtos ML`, revise os agrupamentos. Voce pode remover produtos do CSV bruto ou enviar itens para a blacklist.
6. Na aba `Shopee manual`, cadastre quantos anuncios quiser para o mesmo produto do ML.
7. Na aba `Oportunidades`, o dashboard usa o menor custo Shopee habilitado por produto e calcula margem/lucro.

## Comandos CLI Uteis

Listar perfis do Chrome:

```powershell
.\.venv\Scripts\produtos-identificador.exe chrome-profiles
```

Diagnosticar abertura do Mercado Livre via CDP:

```powershell
.\.venv\Scripts\produtos-identificador.exe diagnose-ml-cdp --query "ssd nvme" --user-data-dir .browser/ml-cdp --profile-directory Default --port 9341 --wait 20
```

Coletar todas as paginas desejadas do Mercado Livre:

```powershell
.\.venv\Scripts\produtos-identificador.exe scrape-ml-cdp --query "ssd nvme" --pages 5 --limit 0 --user-data-dir .browser/ml-cdp --profile-directory Default --port 9342 --wait 20 --delay 2 --out output/ml/raw/ml_cdp.csv
```

Gerar novamente o CSV agrupado:

```powershell
.\.venv\Scripts\produtos-identificador.exe dedupe-ml --br-csv output/ml/raw/ml_cdp.csv --out output/ml/clean/ml_products_clean.csv
```

Converter uma pagina HTML salva manualmente do Mercado Livre:

```powershell
.\.venv\Scripts\produtos-identificador.exe parse-ml-html --html data/ml_busca.html --out output/ml/raw/ml_cdp.csv
```

## Custos e Margem

Configure no `.env` quando quiser ajustar os calculos:

```text
BRL_PER_VND=0.00021
IMPORT_TAX_RATE=0.60
ICMS_RATE=0.18
ML_FEE_RATE=0.16
PAYMENT_FEE_RATE=0.04
FIXED_COST_BRL=10
TARGET_MARGIN_RATE=0.30
```

Os calculos sao estimativas para triagem. Antes de comprar estoque, valide impostos, NCM, regras de importacao, certificacoes, garantia e politicas do marketplace.
