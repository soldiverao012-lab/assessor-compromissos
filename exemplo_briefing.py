# -*- coding: utf-8 -*-
"""
Mostra como o briefing FICA, com os quatro blocos acesos, sem esperar as 7h.

Não inventa a formatação: troca só a FONTE DOS DADOS por dados fictícios e deixa
o briefing.py de verdade montar o texto. Ou seja, o que aparece aqui é exatamente
o que vai chegar no Telegram quando todos os Secrets estiverem no lugar.

Serve também de teste de fumaça: se alguém mexer na formatação e quebrar, aparece aqui.

Uso:  .venv\\Scripts\\python exemplo_briefing.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

# As chaves só precisam EXISTIR — nada aqui vai à rede de verdade.
os.environ.update({
    "GRANATUM_TOKEN": "exemplo", "GRANATUM_CONTA_ID": "110255,61913",
    "SHOPIFY_STORE": "exemplo.myshopify.com", "SHOPIFY_TOKEN": "exemplo",
    "GMAIL_USER": "exemplo@gmail.com", "GMAIL_APP_PASSWORD": "exemplo",
})

import briefing
import assessor as app

TZ = app.TZ
HOJE = datetime.now(TZ).replace(hour=7, minute=0, second=0, microsecond=0)


def _iso(hora, minuto=0):
    return HOJE.replace(hour=hora, minute=minuto).isoformat()


# ── Dados de exemplo ─────────────────────────────────────────────────────────
AGENDA = [
    {"start": {"dateTime": _iso(9, 30)},  "summary": "Fotos do maiô de laço — 11 cores"},
    {"start": {"dateTime": _iso(14, 0)},  "summary": "Ligar pro fornecedor de tecido"},
    {"start": {"dateTime": _iso(16, 30)}, "summary": "Fechar a fatura da Stone"},
]

LANCAMENTOS = [
    {"descricao": "Aluguel da loja",     "valor": "-2800.00", "data_vencimento": HOJE.date().isoformat()},
    {"descricao": "Energia CPFL",        "valor": "-431.70",  "data_vencimento": HOJE.date().isoformat()},
    {"descricao": "Recebimento Cielo",   "valor": "1250.40",  "data_vencimento": HOJE.date().isoformat()},
    {"descricao": "SIMPLES/MEI",         "valor": "-81.90",   "data_vencimento": (HOJE - timedelta(days=82)).date().isoformat()},
    {"descricao": "SIMPLES/MEI",         "valor": "-76.90",   "data_vencimento": (HOJE - timedelta(days=82)).date().isoformat()},
    {"descricao": "Internet Vivo",       "valor": "-159.90",  "data_vencimento": (HOJE - timedelta(days=6)).date().isoformat()},
    {"descricao": "Ja foi pago (some)",  "valor": "-500.00",  "data_vencimento": HOJE.date().isoformat(),
     "data_pagamento": HOJE.date().isoformat()},
]

PEDIDOS = [{"total_price": v} for v in ("289.90", "159.90", "449.70", "219.90")]

EMAILS = [
    ("Shopify", "Voce recebeu um novo pedido #1042"),
    ("Banco Itau", "Aviso de vencimento: boleto em aberto"),
    ("Fornecedor Tecidos SP", "Re: cotacao lycra + malha [urgente]"),
]


# ── Trocando as fontes por dados fictícios ───────────────────────────────────
class _Resposta:
    def __init__(self, dados):
        self._dados = dados

    def raise_for_status(self):
        pass

    def json(self):
        return self._dados


def _get_falso(url, **kwargs):
    if "granatum" in url:
        # As duas contas: devolve a metade dos lançamentos em cada uma.
        conta = str(kwargs.get("params", {}).get("conta_id"))
        return _Resposta(LANCAMENTOS if conta == "110255" else [])
    if "myshopify" in url:
        return _Resposta({"orders": PEDIDOS})
    raise AssertionError(f"URL inesperada no exemplo: {url}")


class _ImapFalso:
    def __init__(self, *a, **kw):
        pass

    def login(self, *a):
        pass

    def select(self, *a, **kw):
        pass

    def search(self, *a):
        return "OK", [b" ".join(str(i).encode() for i in range(1, len(EMAILS) + 1))]

    def fetch(self, msg_id, *a):
        remetente, assunto = EMAILS[int(msg_id) - 1]
        cabecalho = f"From: {remetente} <contato@exemplo.com>\r\nSubject: {assunto}\r\n\r\n"
        return "OK", [(b"", cabecalho.encode())]

    def logout(self):
        pass


briefing.requests.get = _get_falso
briefing.imaplib.IMAP4_SSL = _ImapFalso
app.eventos_entre = lambda svc, inicio, fim: AGENDA


# ── Renderiza ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    texto = briefing.montar(svc=None, agora=HOJE)
    print("\n┌─ como chega no Telegram " + "─" * 34)
    for linha in texto.split("\n"):
        print("│ " + linha)
    print("└" + "─" * 58 + "\n")
    print("(dados ficticios; a formatacao e a do briefing.py de verdade)")
