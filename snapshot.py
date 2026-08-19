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

# Quantos dias pra FRENTE a fotografia enxerga (contas a vencer).
DIAS_FUTURO = 60


def coletar(agora=None):
    """Lê o Granatum e devolve os lançamentos em aberto, já organizados."""
    agora = agora or datetime.now(app.TZ)
    token = os.getenv("GRANATUM_TOKEN")
    if not token:
        raise SystemExit("❌ Falta GRANATUM_TOKEN")

    hoje = agora.date()
    inicio = hoje - timedelta(days=briefing.DIAS_ATRASO)
    # A janela vai pra FRENTE também: sem isso a fotografia não enxerga nada com
    # vencimento futuro, e a pergunta "o que vence essa semana?" não tinha como
    # ser respondida — a situação "futuro" nunca aparecia.
    fim = hoje + timedelta(days=DIAS_FUTURO)
    orcamento = [briefing.MAX_CHAMADAS]

    contas = {}
    lancamentos = []
    for cid in briefing._granatum_contas(token):
        lancamentos.extend(briefing._granatum_lancamentos(token, cid, inicio, fim, orcamento))

    # Nome E SALDO de cada conta. O saldo vem de graça nessa mesma resposta —
    # é o que responde "qual o saldo da conta X" sem consulta nenhuma a mais.
    contas_lista = []
    try:
        resposta = briefing._granatum_get("contas", {"access_token": token}) or []
    except Exception as e:
        print(f"   [aviso] não consegui listar as contas: {e}")
        resposta = []
    if resposta:
        for c in resposta:
            # .strip(): há conta cadastrada com espaço sobrando no fim
            # ("Cartão Empresarial "), o que quebra comparação por nome.
            nome = (c.get("descricao") or "?").strip()
            contas[str(c["id"])] = nome
            try:
                saldo = float(c.get("saldo") or 0)
            except (TypeError, ValueError):
                saldo = 0.0
            contas_lista.append({"id": str(c["id"]), "nome": nome, "saldo": round(saldo, 2)})

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
        "contas": contas_lista,
        "movimento": resumir_movimento(lancamentos, hoje, inicio),
        "vendas": coletar_vendas(agora),
    }


def resumir_movimento(lancamentos, hoje, inicio_janela):
    """
    Quanto ENTROU e quanto SAIU de fato, por período.

    Aproveita dados que já vieram na mesma consulta: até agora os lançamentos
    já pagos eram lidos e jogados fora, e são justamente eles que dizem o que
    de fato aconteceu. Nenhuma chamada a mais na API.

    ⚠️ Isto é CAIXA (dinheiro que entrou menos dinheiro que saiu, pela data de
    pagamento), não lucro contábil. Não considera competência, estoque nem
    depreciação — quem faz isso é o DRE no Granatum. Quem consome tem que
    rotular como "resultado de caixa", nunca como "lucro", senão induz a
    decisão errada.

    Período que a janela não cobre inteiro é OMITIDO, não estimado. Com janela
    de 180 dias, "no ano" começaria antes do primeiro lançamento lido e sairia
    menor que a realidade — um total errado é pior que total nenhum, porque
    parece certo.
    """
    candidatos = {
        "mes":       hoje.replace(day=1),
        "trimestre": hoje - timedelta(days=90),
        "ano":       hoje.replace(month=1, day=1),
    }
    periodos = {n: d for n, d in candidatos.items() if d >= inicio_janela}
    resumo = {nome: {"entrou": 0.0, "saiu": 0.0} for nome in periodos}

    for l in lancamentos:
        pago = str(l.get("data_pagamento") or "")[:10]
        if not pago:
            continue  # ainda não aconteceu: não é movimento
        try:
            d = datetime.fromisoformat(pago).date()
            valor = float(l.get("valor") or 0)
        except (TypeError, ValueError):
            continue
        if d > hoje:
            continue
        for nome, desde in periodos.items():
            if d >= desde:
                if valor >= 0:
                    resumo[nome]["entrou"] += valor
                else:
                    resumo[nome]["saiu"] += -valor

    for nome, v in resumo.items():
        v["entrou"] = round(v["entrou"], 2)
        v["saiu"] = round(v["saiu"], 2)
        v["saldo"] = round(v["entrou"] - v["saiu"], 2)
        v["desde"] = periodos[nome].isoformat()
    return resumo


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
