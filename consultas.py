# -*- coding: utf-8 -*-
"""
Perguntas que o bot sabe responder sobre o financeiro.

Lê a fotografia gravada por snapshot.py (nunca consulta o Granatum na hora —
seriam ~38 segundos e o webhook morre antes) e responde em ~1 segundo.

O entendimento é por palavra-chave, no mesmo espírito do parser de datas do
assessor.py: sem API paga, sem depender de nada externo.

Regra importante de convivência com o resto do bot: quem manda frase livre
está quase sempre CRIANDO COMPROMISSO ("dentista amanhã 10h"). Só tratamos a
mensagem como pergunta quando ela casa com um padrão bem específico — por isso
os padrões abaixo exigem palavras que ninguém usa em título de compromisso
("atrasad", "quanto devo", "o que vence"). Na dúvida, devolve None e a frase
segue o caminho normal de virar evento.
"""
import re
import unicodedata
from datetime import datetime

import snapshot


def _sem_acento(texto):
    n = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def _dinheiro(valor):
    return f"R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _limpar(texto, tamanho=38):
    """Tira o que quebra o Markdown do Telegram (um '*' solto recusa a mensagem)."""
    limpo = "".join(c for c in str(texto or "") if c not in "*_`[]")
    limpo = " ".join(limpo.split())
    return (limpo[:tamanho - 1] + "…") if len(limpo) > tamanho else (limpo or "(sem descrição)")


# ── Padrões de pergunta ──────────────────────────────────────────────────────
# Cada um: (nome da intenção, regex). Testados em ordem; o primeiro que casar vence.
PADROES = [
    ("atrasados", r"\batrasad|\bem atraso\b|\bvencid[oa]s?\b|\bdevendo\b|quanto (eu )?devo"),
    ("hoje",      r"vence (hoje|agora)|\bo que vence\b|(contas?|pagar) (de )?hoje|a pagar hoje"),
    ("resumo",    r"\bfinanceiro\b|\bresumo (do )?financeiro\b|como (esta|estao) as contas"),
    ("maiores",   r"maior(es)? (conta|despesa|divida)|\bmaiores\b"),
]

COMANDOS = {
    "/atrasados": "atrasados",
    "/financeiro": "resumo",
    "/vencehoje": "hoje",
}


def identificar(texto):
    """Descobre a intenção da mensagem. None = não é pergunta financeira."""
    bruto = str(texto or "").strip()
    baixa = _sem_acento(bruto)

    if baixa in COMANDOS:
        return COMANDOS[baixa]
    for nome, padrao in PADROES:
        if re.search(padrao, baixa):
            return nome
    return None


# ── Respostas ────────────────────────────────────────────────────────────────
def _idade(dados):
    """Há quanto tempo a fotografia foi tirada, em texto curto."""
    try:
        quando = datetime.fromisoformat(dados["atualizado_em"])
    except (KeyError, ValueError):
        return ""
    minutos = int((datetime.now(quando.tzinfo) - quando).total_seconds() // 60)
    if minutos < 2:
        return "agora"
    if minutos < 60:
        return f"há {minutos} min"
    horas = minutos // 60
    return f"há {horas}h" if horas < 24 else f"há {horas // 24}d"


def _linhas(itens, limite, mostrar_dias=False):
    saida = []
    for a in itens[:limite]:
        d = datetime.fromisoformat(a["data"]).strftime("%d/%m")
        extra = f" _({a['dias']}d)_" if mostrar_dias and a.get("dias", 0) > 0 else ""
        conta = f"  ·  {_limpar(a.get('conta'), 16)}" if a.get("conta") else ""
        saida.append(f"  · {d} {_limpar(a['descricao'])} — {_dinheiro(a['valor'])}{extra}{conta}")
    if len(itens) > limite:
        saida.append(f"  · … e mais {len(itens) - limite}")
    return saida


def responder(intencao, limite=12):
    """Monta o texto da resposta. Devolve None se não houver fotografia ainda."""
    dados = snapshot.carregar()
    if not dados:
        return ("🤔 Ainda não tenho a fotografia do financeiro.\n"
                "Ela é tirada de hora em hora pelo robô da nuvem — "
                "tenta de novo daqui a pouco.")

    abertos = dados.get("abertos", [])
    atrasados = [a for a in abertos if a["situacao"] == "atrasado"]
    hoje = [a for a in abertos if a["situacao"] == "hoje"]
    rodape = f"\n\n_dados de {_idade(dados)}_"

    if intencao == "atrasados":
        if not atrasados:
            return "✅ *Nada atrasado.* Tudo em dia!" + rodape
        sai = sum(-a["valor"] for a in atrasados if a["valor"] < 0)
        entra = sum(a["valor"] for a in atrasados if a["valor"] > 0)
        cab = [f"⚠️ *{len(atrasados)} atrasado(s)* — a pagar {_dinheiro(sai)}"]
        if entra:
            cab.append(f"  _(a receber {_dinheiro(entra)})_")
        # Mais recente primeiro: é o que ainda dá pra resolver hoje.
        ordenados = sorted(atrasados, key=lambda x: (x["data"], abs(x["valor"])), reverse=True)
        return "\n".join(cab + _linhas(ordenados, limite, mostrar_dias=True)) + rodape

    if intencao == "hoje":
        if not hoje:
            return "✅ *Nada vencendo hoje.*" + rodape
        sai = sum(-a["valor"] for a in hoje if a["valor"] < 0)
        entra = sum(a["valor"] for a in hoje if a["valor"] > 0)
        resumo = []
        if sai:
            resumo.append(f"sai {_dinheiro(sai)}")
        if entra:
            resumo.append(f"entra {_dinheiro(entra)}")
        cab = [f"📅 *Vence hoje* ({', '.join(resumo)})"]
        ordenados = sorted(hoje, key=lambda x: abs(x["valor"]), reverse=True)
        return "\n".join(cab + _linhas(ordenados, limite)) + rodape

    if intencao == "maiores":
        if not abertos:
            return "✅ *Nada em aberto.*" + rodape
        ordenados = sorted(abertos, key=lambda x: abs(x["valor"]), reverse=True)
        return ("💰 *Maiores contas em aberto*\n"
                + "\n".join(_linhas(ordenados, limite, mostrar_dias=True)) + rodape)

    if intencao == "resumo":
        sai_atr = sum(-a["valor"] for a in atrasados if a["valor"] < 0)
        sai_hoje = sum(-a["valor"] for a in hoje if a["valor"] < 0)
        futuros = [a for a in abertos if a["situacao"] == "futuro"]
        linhas = ["💰 *Financeiro*"]
        linhas.append(f"  ⚠️ Atrasado: *{len(atrasados)}* — {_dinheiro(sai_atr)}")
        linhas.append(f"  📅 Vence hoje: *{len(hoje)}* — {_dinheiro(sai_hoje)}")
        if futuros:
            sai_fut = sum(-a["valor"] for a in futuros if a["valor"] < 0)
            linhas.append(f"  🔜 A vencer: *{len(futuros)}* — {_dinheiro(sai_fut)}")
        if atrasados:
            pior = max(atrasados, key=lambda x: abs(x["valor"]))
            linhas.append(f"\n  Maior atrasada: {_limpar(pior['descricao'])} "
                          f"— {_dinheiro(pior['valor'])}")
        linhas.append("\n  _Pergunte:_ atrasados · vence hoje · maiores contas")
        return "\n".join(linhas) + rodape

    return None


def tratar(texto):
    """Atalho: identifica e responde. None = não era pergunta financeira."""
    intencao = identificar(texto)
    return responder(intencao) if intencao else None


if __name__ == "__main__":
    # Teste rápido: python consultas.py "quais contas estao atrasadas?"
    import sys
    frases = sys.argv[1:] or [
        "quais estao atrasadas?", "quanto devo", "o que vence hoje",
        "/financeiro", "maiores contas", "dentista amanha as 10h",
    ]
    for f in frases:
        intencao = identificar(f)
        print(f"\n=== {f!r} -> {intencao or 'NAO E PERGUNTA (vira compromisso)'}")
        if intencao:
            print(responder(intencao, limite=4))
