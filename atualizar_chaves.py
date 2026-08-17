# -*- coding: utf-8 -*-
r"""
Recolhe as chaves dos projetos vizinhos e deixa o assessor pronto.

O briefing usa credenciais que já existem em OUTROS projetos do workspace
(granatum/.env e shopify/.env). Em vez de você copiar na mão e correr o risco
de errar uma letra, este script:

  1. lê as chaves de granatum/.env e shopify/.env;
  2. atualiza o .env daqui (sem duplicar linha: troca a que já existe);
  3. regenera SECRETS-PARA-O-GITHUB.local.md com os valores prontos pra colar.

Rode sempre que trocar alguma credencial — principalmente depois de reautorizar
a Shopify, que gera um SHOPIFY_TOKEN novo.

Uso:  .venv\Scripts\python atualizar_chaves.py
"""
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

AQUI = Path(__file__).resolve().parent
WORKSPACE = AQUI.parent
ENV_DESTINO = AQUI / ".env"
ARQUIVO_SECRETS = AQUI / "SECRETS-PARA-O-GITHUB.local.md"

# chave no assessor  ->  (arquivo de origem, chave lá)
ORIGENS = {
    "GRANATUM_TOKEN":      ("granatum/.env", "GRANATUM_TOKEN"),
    "SHOPIFY_STORE":       ("shopify/.env",  "SHOPIFY_STORE"),
    "SHOPIFY_TOKEN":       ("shopify/.env",  "SHOPIFY_TOKEN"),
    "SHOPIFY_API_VERSION": ("shopify/.env",  "SHOPIFY_API_VERSION"),
    "GMAIL_USER":          ("granatum/.env", "EMAIL_REMETENTE"),
    "GMAIL_APP_PASSWORD":  ("granatum/.env", "EMAIL_SENHA_APP"),
}

# Não vem de outro projeto: as duas contas do Granatum, de config/contas.yaml.
FIXAS = {"GRANATUM_CONTA_ID": "110255,61913"}

BLOCOS = [
    ("💰 Bloco Financeiro (Granatum)", ["GRANATUM_TOKEN", "GRANATUM_CONTA_ID"]),
    ("📬 Bloco E-mails (Gmail)",       ["GMAIL_USER", "GMAIL_APP_PASSWORD"]),
    ("🛒 Bloco Vendas (Shopify)",      ["SHOPIFY_STORE", "SHOPIFY_TOKEN", "SHOPIFY_API_VERSION"]),
]


def ler_env(caminho):
    valores = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", linha)
        if m:
            valores[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return valores


def gravar_env(caminho, novos):
    """Atualiza chaves no .env trocando a linha existente (não duplica)."""
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    restantes = dict(novos)

    for i, linha in enumerate(linhas):
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", linha)
        if m and m.group(1) in restantes:
            chave = m.group(1)
            linhas[i] = f"{chave}={restantes.pop(chave)}"

    if restantes:  # chaves que ainda não existiam
        linhas.append("")
        for chave, valor in restantes.items():
            linhas.append(f"{chave}={valor}")

    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def escrever_secrets(valores, faltando):
    l = []
    l.append("# 🔑 Secrets pra colar no GitHub\n")
    l.append("> ⚠️ **Este arquivo tem senha de verdade dentro.** Está no `.gitignore`")
    l.append("> (`*.local.md`), então nunca sobe pro GitHub. Depois de colar, pode apagar.\n")
    l.append("Gerado por `atualizar_chaves.py`. Rode ele de novo se trocar alguma credencial.\n")
    l.append("## Onde colar\n")
    l.append("**github.com/soldiverao012-lab/assessor-compromissos** → **Settings** →")
    l.append("**Secrets and variables** → **Actions** → **New repository secret**.\n")
    l.append("Pra cada linha: **Name** = coluna 1, **Secret** = coluna 2.\n")

    for titulo, chaves in BLOCOS:
        l.append(f"## {titulo}\n")
        l.append("| Name | Secret |")
        l.append("|---|---|")
        for chave in chaves:
            valor = valores.get(chave) or "⚠️ FALTANDO"
            l.append(f"| `{chave}` | `{valor}` |")
        l.append("")

    if faltando:
        l.append("## ⚠️ Faltou\n")
        for chave, motivo in faltando:
            l.append(f"- `{chave}` — {motivo}")
        l.append("")

    l.append("## Conferir\n")
    l.append("Aba **Actions** → **Briefing do Dia** → **Run workflow**.\n")
    l.append("Ou aqui, sem enviar nada: `.venv\\Scripts\\python briefing.py --teste`")

    ARQUIVO_SECRETS.write_text("\n".join(l) + "\n", encoding="utf-8")


def main():
    valores, faltando = dict(FIXAS), []

    for chave, (arquivo, chave_origem) in ORIGENS.items():
        origem = ler_env(WORKSPACE / arquivo)
        valor = origem.get(chave_origem, "").strip()
        if valor:
            valores[chave] = valor
            print(f"  [ OK ] {chave:<20} <- {arquivo}")
        else:
            faltando.append((chave, f"vazio em `{arquivo}` (procurei `{chave_origem}`)"))
            print(f"  [FALTA] {chave:<20} <- {arquivo} (vazio)")

    gravar_env(ENV_DESTINO, valores)
    print(f"\n.env atualizado: {ENV_DESTINO}")

    escrever_secrets(valores, faltando)
    print(f"Secrets prontos: {ARQUIVO_SECRETS.name}")

    # Aviso específico do escopo da Shopify, que é o tropeço mais provável.
    token = valores.get("SHOPIFY_TOKEN")
    if token:
        import requests
        loja = valores.get("SHOPIFY_STORE")
        try:
            r = requests.get(f"https://{loja}/admin/oauth/access_scopes.json",
                             headers={"X-Shopify-Access-Token": token}, timeout=20)
            escopos = [e["handle"] for e in r.json().get("access_scopes", [])]
            if "read_orders" in escopos:
                print("\n✅ Shopify: o token JÁ tem read_orders — o bloco de vendas vai funcionar.")
            else:
                print("\n⚠️ Shopify: o token ainda NÃO tem read_orders.")
                print("   Rode:  cd ..\\shopify  &&  python obter_token.py")
                print("   Depois rode este script de novo.")
        except Exception as e:
            print(f"\n⚠️ não consegui conferir os escopos da Shopify: {e}")

    if faltando:
        print(f"\n{len(faltando)} chave(s) faltando — veja o fim do arquivo de Secrets.")


if __name__ == "__main__":
    main()
