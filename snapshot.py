# -*- coding: utf-8 -*-
"""
Fotografia do financeiro — para o bot responder na hora.

Por que existe: consultar o Granatum leva ~38 segundos, porque a API corta a
resposta em 50 itens e obriga a fatiar o período em pedaços pequenos. O webhook
do Telegram roda no Vercel, que mata a função em poucos segundos — ou seja, o
bot NUNCA conseguiria consultar o Granatum enquanto você espera a resposta.

Então quem paga esses 38 segundos é o robô da nuvem, de hora em hora, longe de
você: ele tira uma foto dos lançamentos em aberto e grava em state/financeiro.json.
O bot lê a foto e responde em ~1 segundo. Para conta a pagar, um dado de até uma
hora atrás não muda decisão nenhuma.

Uso:
    python snapshot.py            # atualiza state/financeiro.json
    python snapshot.py --mostrar  # imprime o que gravou
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import briefing
import assessor as app

ARQUIVO = Path(__file__).resolve().parent / "state" / "financeiro.json"


def coletar(agora=None):
    """Lê o Granatum e devolve os lançamentos em aberto, já organizados."""
    agora = agora or datetime.now(app.TZ)
    token = os.getenv("GRANATUM_TOKEN")
    if not token:
        raise SystemExit("❌ Falta GRANATUM_TOKEN")

    hoje = agora.date()
    inicio = hoje - timedelta(days=briefing.DIAS_ATRASO)
    orcamento = [briefing.MAX_CHAMADAS]

    contas = {}
    lancamentos = []
    for cid in briefing._granatum_contas(token):
        lancamentos.extend(briefing._granatum_lancamentos(token, cid, inicio, hoje, orcamento))

    # Nome de cada conta, pra foto ficar legível sem consultar de novo.
    import requests
    r = requests.get(f"{briefing.GRANATUM_BASE}/contas",
                     params={"access_token": token}, timeout=30)
    if r.ok:
        contas = {str(c["id"]): c.get("descricao", "?") for c in (r.json() or [])}

    abertos = []
    for l in lancamentos:
        if l.get("data_pagamento"):
            continue  # já quitado
        venc = str(l.get("data_vencimento") or "")[:10]
        if not venc:
            continue
        try:
            d = datetime.fromisoformat(venc).date()
            valor = float(l.get("valor") or 0)
        except (TypeError, ValueError):
            continue
        abertos.append({
            "data": venc,
            "valor": valor,
            "descricao": str(l.get("descricao") or "(sem descrição)"),
            "conta": contas.get(str(l.get("conta_id")), ""),
            "situacao": "hoje" if d == hoje else ("atrasado" if d < hoje else "futuro"),
            "dias": (hoje - d).days,
        })

    abertos.sort(key=lambda x: (x["data"], -abs(x["valor"])))
    return {
        "atualizado_em": agora.isoformat(),
        "referencia": hoje.isoformat(),
        "abertos": abertos,
        "vendas": coletar_vendas(agora),
    }


def coletar_vendas(agora):
    """
    Pedidos da loja por período, para o bot responder sem consultar a Shopify.

    A Shopify é rápida (~0,3s), então o bot até consegue consultá-la ao vivo —
    mas só se as chaves dela existirem no Vercel, o que é configuração à parte.
    Guardando aqui, a pergunta "quanto vendeu hoje" funciona de imediato; se as
    chaves estiverem no Vercel, `consultas.py` prefere o dado ao vivo.
    """
    loja = os.getenv("SHOPIFY_STORE")
    token = os.getenv("SHOPIFY_TOKEN")
    if not loja or not token:
        return None

    import requests
    versao = os.getenv("SHOPIFY_API_VERSION", "2024-10")
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)

    periodos = {
        "hoje":   inicio_dia,
        "ontem":  inicio_dia - timedelta(days=1),
        "semana": inicio_dia - timedelta(days=7),
        "mes":    inicio_dia - timedelta(days=30),
    }
    # Uma requisição só, no período mais largo; os menores saem por filtro.
    r = requests.get(
        f"https://{loja}/admin/api/{versao}/orders.json",
        headers={"X-Shopify-Access-Token": token},
        params={"status": "any", "created_at_min": periodos["mes"].isoformat(),
                "limit": 250},
        timeout=30,
    )
    if not r.ok:
        return None
    pedidos = r.json().get("orders", [])

    resumo = {}
    for nome, desde in periodos.items():
        ate = inicio_dia if nome == "ontem" else agora
        n, total = 0, 0.0
        for p in pedidos:
            try:
                quando = datetime.fromisoformat(p["created_at"]).astimezone(app.TZ)
            except (KeyError, ValueError):
                continue
            if desde <= quando < ate:
                n += 1
                try:
                    total += float(p.get("total_price") or 0)
                except (TypeError, ValueError):
                    pass
        resumo[nome] = {"pedidos": n, "total": round(total, 2)}
    return resumo


def salvar(dados):
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(
        json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ARQUIVO


def carregar():
    """Lê a foto do disco. Devolve None se ainda não existe."""
    if not ARQUIVO.exists():
        return None
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def main():
    dados = coletar()
    caminho = salvar(dados)

    atrasados = [a for a in dados["abertos"] if a["situacao"] == "atrasado"]
    hoje = [a for a in dados["abertos"] if a["situacao"] == "hoje"]
    print(f"✅ {caminho.name}: {len(dados['abertos'])} em aberto "
          f"({len(atrasados)} atrasado(s), {len(hoje)} vencendo hoje)")

    if "--mostrar" in sys.argv:
        for a in dados["abertos"]:
            print(f"   {a['data']}  {a['situacao']:<9} {a['valor']:>10.2f}  "
                  f"{a['descricao'][:38]:<38} {a['conta']}")


if __name__ == "__main__":
    main()
