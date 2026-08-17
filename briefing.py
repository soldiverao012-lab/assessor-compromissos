# -*- coding: utf-8 -*-
"""
Briefing do dia — o "bom dia" completo, às 7h, num recado só no Telegram.

Junta num único texto:
  📅 Agenda      — compromissos de hoje (Google Calendar)
  💰 Financeiro  — o que vence hoje e o que está atrasado (API do Granatum)
  🛒 Vendas      — pedidos de ontem na loja virtual (API da Shopify)
  📬 E-mails     — não lidos que chegaram desde ontem (Gmail via IMAP)

Cada fonte é OPCIONAL e INDEPENDENTE:
  • Sem as chaves da fonte, o bloco simplesmente não aparece — nada quebra.
  • Se uma fonte cair (API fora do ar, senha trocada), o briefing sai assim mesmo
    com um aviso naquele bloco. Um serviço ruim nunca cancela o seu bom dia.

Tudo aqui é gratuito: nenhuma API paga. O Gmail é lido por IMAP com senha de app,
que é grátis e não exige OAuth.

Uso:
    python briefing.py            # monta e ENVIA no Telegram
    python briefing.py --teste    # monta e só IMPRIME na tela (não envia)
"""
import email
import imaplib
import os
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header

import requests

import assessor as app

TZ = app.TZ

# Limite do Telegram é 4096; deixamos folga pro rodapé.
LIMITE_TELEGRAM = 3800


# ── Utilidades ───────────────────────────────────────────────────────────────
def _limpar(texto, tamanho=60):
    """
    Tira os caracteres que quebram o Markdown do Telegram.

    Texto de fora (assunto de e-mail, descrição de lançamento) pode ter '*' ou '_'
    soltos. Um único desses desemparelhado faz a API RECUSAR a mensagem inteira —
    ou seja, um e-mail com underline no assunto derrubaria o briefing todo.
    """
    limpo = "".join(c for c in str(texto or "") if c not in "*_`[]")
    limpo = " ".join(limpo.split())
    if len(limpo) > tamanho:
        limpo = limpo[: tamanho - 1].rstrip() + "…"
    return limpo or "(sem título)"


def _dinheiro(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ── 📅 Agenda ────────────────────────────────────────────────────────────────
def bloco_agenda(svc, agora):
    fim = agora.replace(hour=23, minute=59, second=59, microsecond=0)
    evs = app.eventos_entre(svc, agora, fim)
    if not evs:
        return "📅 *Agenda* — livre hoje. 🌴"

    linhas = []
    for ev in evs:
        ini = ev["start"].get("dateTime")
        hora = (datetime.fromisoformat(ini).astimezone(TZ).strftime("%H:%M")
                if ini else "dia todo")
        linhas.append(f"• {hora} — {_limpar(ev.get('summary'))}")

    n = len(evs)
    cabeca = f"📅 *Agenda* — {n} compromisso{'s' if n > 1 else ''}"
    return cabeca + "\n" + "\n".join(linhas)


# ── 💰 Financeiro (Granatum) ─────────────────────────────────────────────────
def bloco_financeiro(agora):
    token = os.getenv("GRANATUM_TOKEN")
    contas = [c.strip() for c in os.getenv("GRANATUM_CONTA_ID", "").split(",") if c.strip()]
    if not token or not contas:
        return None  # fonte não configurada — bloco não aparece

    hoje = agora.date()
    # Olhamos 90 dias pra trás pra capturar o que venceu e ficou pra trás.
    inicio = (hoje - timedelta(days=90)).isoformat()

    lancamentos = []
    for conta in contas:
        # Sem 'tipo' a API devolve TUDO, inclusive os atrasados — os filtros por
        # tipo deixam os atrasados de fora (aprendido no projeto granatum/).
        r = requests.get(
            "https://api.granatum.com.br/v1/lancamentos",
            params={"access_token": token, "conta_id": conta,
                    "data_inicio": inicio, "data_fim": hoje.isoformat()},
            timeout=30,
        )
        r.raise_for_status()
        lancamentos.extend(r.json() or [])

    vence_hoje, atrasados = [], []
    for l in lancamentos:
        if l.get("data_pagamento"):
            continue  # já quitado
        venc = l.get("data_vencimento")
        if not venc:
            continue
        try:
            d = datetime.fromisoformat(str(venc)[:10]).date()
        except ValueError:
            continue
        try:
            valor = float(l.get("valor") or 0)
        except (TypeError, ValueError):
            continue
        item = (d, valor, _limpar(l.get("descricao"), 40))
        if d == hoje:
            vence_hoje.append(item)
        elif d < hoje:
            atrasados.append(item)

    if not vence_hoje and not atrasados:
        return "💰 *Financeiro* — nada vencendo, nada atrasado. ✅"

    partes = ["💰 *Financeiro*"]
    if vence_hoje:
        total = sum(v for _, v, _ in vence_hoje)
        partes.append(f"  _Vence hoje_ ({_dinheiro(abs(total))}):")
        for _, valor, desc in sorted(vence_hoje, key=lambda x: x[1]):
            sinal = "🔴" if valor < 0 else "🟢"
            partes.append(f"  {sinal} {desc} — {_dinheiro(abs(valor))}")
    if atrasados:
        total = sum(v for _, v, _ in atrasados)
        partes.append(f"  ⚠️ _Atrasado_: {len(atrasados)} lançamento(s), "
                      f"{_dinheiro(abs(total))}")
        for d, valor, desc in sorted(atrasados)[:5]:
            partes.append(f"  · {d.strftime('%d/%m')} {desc} — {_dinheiro(abs(valor))}")
        if len(atrasados) > 5:
            partes.append(f"  · … e mais {len(atrasados) - 5}")
    return "\n".join(partes)


# ── 🛒 Vendas de ontem (Shopify) ─────────────────────────────────────────────
def bloco_vendas(agora):
    loja = os.getenv("SHOPIFY_STORE")
    token = os.getenv("SHOPIFY_TOKEN")
    if not loja or not token:
        return None

    versao = os.getenv("SHOPIFY_API_VERSION", "2024-10")
    ontem = (agora - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    fim = ontem.replace(hour=23, minute=59, second=59)

    r = requests.get(
        f"https://{loja}/admin/api/{versao}/orders.json",
        headers={"X-Shopify-Access-Token": token},
        params={"status": "any", "created_at_min": ontem.isoformat(),
                "created_at_max": fim.isoformat(), "limit": 250},
        timeout=30,
    )
    r.raise_for_status()
    pedidos = r.json().get("orders", [])

    if not pedidos:
        return "🛒 *Loja virtual* — nenhum pedido ontem."

    total = 0.0
    for p in pedidos:
        try:
            total += float(p.get("total_price") or 0)
        except (TypeError, ValueError):
            pass
    n = len(pedidos)
    ticket = total / n if n else 0
    return (f"🛒 *Loja virtual* (ontem) — {n} pedido{'s' if n > 1 else ''}, "
            f"{_dinheiro(total)}\n  _ticket médio_ {_dinheiro(ticket)}")


# ── 📬 E-mails (Gmail por IMAP) ──────────────────────────────────────────────
def bloco_email(agora):
    usuario = os.getenv("GMAIL_USER")
    senha = os.getenv("GMAIL_APP_PASSWORD")
    if not usuario or not senha:
        return None

    # Data no formato do IMAP (01-Jan-2026). SINCE é por dia, então pegamos
    # desde ontem e o servidor filtra o resto.
    desde = (agora - timedelta(days=1)).strftime("%d-%b-%Y")

    conexao = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        conexao.login(usuario, senha)
        conexao.select("INBOX", readonly=True)  # readonly: não marca nada como lido
        _, dados = conexao.search(None, f'(UNSEEN SINCE {desde})')
        ids = dados[0].split() if dados and dados[0] else []
        if not ids:
            return "📬 *E-mails* — caixa limpa, nada novo. ✅"

        assuntos = []
        # Os mais recentes primeiro, no máximo 6 na mensagem.
        for msg_id in reversed(ids[-6:]):
            # PEEK: lê o cabeçalho SEM marcar o e-mail como lido.
            _, corpo = conexao.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            if not corpo or not isinstance(corpo[0], tuple):
                continue
            msg = email.message_from_bytes(corpo[0][1])
            assunto = str(make_header(decode_header(msg.get("Subject", "(sem assunto)"))))
            remetente = str(make_header(decode_header(msg.get("From", ""))))
            # "Fulano <a@b.com>" -> "Fulano"
            remetente = remetente.split("<")[0].strip().strip('"') or remetente
            assuntos.append(f"  • *{_limpar(remetente, 22)}* — {_limpar(assunto, 45)}")

        n = len(ids)
        cabeca = f"📬 *E-mails* — {n} não lido{'s' if n > 1 else ''}"
        if n > len(assuntos):
            assuntos.append(f"  · … e mais {n - len(assuntos)}")
        return cabeca + "\n" + "\n".join(assuntos)
    finally:
        try:
            conexao.logout()
        except Exception:
            pass


# ── Montagem ─────────────────────────────────────────────────────────────────
FONTES = [
    ("agenda",     bloco_agenda,     True),   # True = precisa do serviço do Calendar
    ("financeiro", bloco_financeiro, False),
    ("vendas",     bloco_vendas,     False),
    ("e-mail",     bloco_email,      False),
]


def montar(svc, agora=None):
    """Monta o texto do briefing. Nunca levanta exceção por causa de uma fonte."""
    agora = agora or datetime.now(TZ)
    dia = f"{app.DIAS_SEMANA[agora.weekday()]}, {agora.day:02d}/{agora.month:02d}"
    partes = [f"☀️ *Bom dia!* _{dia}_"]

    for nome, funcao, precisa_svc in FONTES:
        try:
            bloco = funcao(svc, agora) if precisa_svc else funcao(agora)
        except Exception as e:
            # Uma fonte com problema vira uma linha discreta — o resto do
            # briefing continua chegando normalmente.
            bloco = f"⚠️ _{nome} indisponível hoje_ ({type(e).__name__})"
            print(f"   [aviso] fonte '{nome}' falhou: {e}")
        if bloco:
            partes.append(bloco)

    texto = "\n\n".join(partes)
    if len(texto) > LIMITE_TELEGRAM:
        texto = texto[:LIMITE_TELEGRAM].rsplit("\n", 1)[0] + "\n\n…_(briefing cortado)_"
    return texto + "\n\nBora que o dia rende! 💪"


def main():
    teste = "--teste" in sys.argv
    app.checar_credenciais()
    svc = app.calendario()
    texto = montar(svc)

    if teste:
        print("─" * 60)
        print(texto)
        print("─" * 60)
        print("\n(modo --teste: nada foi enviado)")
        return

    app.enviar(texto)
    print("✅ briefing enviado")


if __name__ == "__main__":
    main()
