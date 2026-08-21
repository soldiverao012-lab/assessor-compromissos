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
import time
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


# ── ⏳ Pendentes (o que passou e você não confirmou) ─────────────────────────
def bloco_pendentes(svc, agora):
    """
    As tarefas cobradas e ainda não confirmadas.

    Fica logo abaixo da agenda de propósito: o compromisso de hoje o próprio
    dia cobra; o que ficou pra trás só reaparece se alguém insistir. Some
    sozinho quando não há nada em aberto — briefing limpo é briefing lido.
    """
    import pendencias
    linhas = pendencias.linhas(svc, agora)
    return "\n".join(linhas) if linhas else None


# ── 🔭 No radar (próximos dias) ──────────────────────────────────────────────
# Quantos dias à frente o radar enxerga. Uma semana: é o horizonte em que dá pra
# se preparar pra um evento de mercado, e casa com o comando /semana do bot.
DIAS_RADAR = 7
# Quantas linhas o radar mostra antes de resumir o resto.
MAX_RADAR = 6


def bloco_radar(svc, agora):
    """
    O que vem NOS PRÓXIMOS DIAS — não hoje.

    Existe porque o bloco de agenda cobre só o dia corrente, e tem compromisso
    que não adianta descobrir na manhã dele: evento de mercado (FOMC, payroll)
    você quer ver chegando com dias de antecedência pra se posicionar. O lembrete
    de "1 dia antes" avisa, mas avisa tarde pra esse tipo de coisa.
    """
    inicio = agora.replace(hour=23, minute=59, second=59)  # a partir de amanhã
    fim = agora + timedelta(days=DIAS_RADAR)
    evs = app.eventos_entre(svc, inicio, fim)
    if not evs:
        return None  # nada à frente: não polui o briefing

    linhas = []
    for ev in evs:
        ini = ev["start"].get("dateTime")
        if not ini:
            continue
        d = datetime.fromisoformat(ini).astimezone(TZ)
        dias = (d.date() - agora.date()).days
        quando = "amanhã" if dias == 1 else f"{app.DIAS_SEMANA[d.weekday()]} {d.day:02d}/{d.month:02d}"
        linhas.append(f"  · {quando} {d.strftime('%H:%M')} — {_limpar(ev.get('summary'), 45)}")

    if not linhas:
        return None
    mostradas = linhas[:MAX_RADAR]
    if len(linhas) > MAX_RADAR:
        mostradas.append(f"  · … e mais {len(linhas) - MAX_RADAR}")
    return f"🔭 *No radar* (7 dias)\n" + "\n".join(mostradas)


# ── 💰 Financeiro (Granatum) ─────────────────────────────────────────────────
GRANATUM_BASE = "https://api.granatum.com.br/v1"

# O Granatum permite 100 requisições/min (e 200 a cada 5 min). Como o corte
# adaptativo faz ~80 chamadas por fotografia, sem controle de ritmo elas saíam
# a ~170/min — acima do teto. Funcionava enquanto a API estava tolerante e
# quebrava quando havia concorrência (uma execução local junto com a da nuvem).
# 0.75s entre chamadas mantém ~80/min, com folga.
INTERVALO_MINIMO = 0.75
_ultima_chamada = [0.0]

# Sessão com retentativa: um 429 ou um 5xx passageiro não pode derrubar a
# fotografia inteira. Antes, um único tropeço matava o job (exit 1) e o
# briefing ficava com dado velho sem ninguém saber por quê.
_sessao = None


def _granatum_sessao():
    global _sessao
    if _sessao is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        _sessao = requests.Session()
        _sessao.headers.update({"User-Agent": "assessor-soldiverao/1.0"})
        # Paciência de ~90s no total. O Granatum tem quedas curtas (já foi visto
        # devolvendo 502 em série por vários minutos); esperar um pouco mais
        # atravessa o soluço em vez de desistir na primeira onda.
        _sessao.mount("https://", HTTPAdapter(max_retries=Retry(
            total=5, backoff_factor=3.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )))
    return _sessao


def _granatum_get(caminho, params):
    """GET no Granatum, respeitando o ritmo e com retentativa."""
    espera = INTERVALO_MINIMO - (time.monotonic() - _ultima_chamada[0])
    if espera > 0:
        time.sleep(espera)
    r = _granatum_sessao().get(f"{GRANATUM_BASE}/{caminho}", params=params, timeout=60)
    _ultima_chamada[0] = time.monotonic()
    r.raise_for_status()
    return r.json()
# Quantos dias pra trás procurar atrasado. Conta esquecida fica meses em aberto.
DIAS_ATRASO = 180
# Quantos atrasados listar antes de resumir o resto.
MAX_ATRASADOS = 6


def _granatum_contas(token):
    """IDs de TODAS as contas ativas, perguntando ao Granatum na hora.

    De propósito não existe lista fixa aqui. O briefing nasceu com as duas
    contas do projeto do extrato (que só tem duas porque só há dois extratos
    bancários) e, por isso, os vencimentos do CAIXA e do Cartão Empresarial
    nunca apareciam — sem erro, sem aviso, só sumiam. Conta nova criada no
    Granatum passa a ser vista sozinha, sem mexer em configuração.
    """
    contas = _granatum_get("contas", {"access_token": token}) or []
    return [str(c["id"]) for c in contas if c.get("ativo", True)]


# A API devolve no máximo 50 lançamentos por consulta — e são os 50 mais
# ANTIGOS do período pedido.
TETO_RESPOSTA = 50
# Profundidade máxima do corte (180 dias / 2^6 ≈ 3 dias por fatia).
MAX_CORTES = 6
# Teto de chamadas por rodada, pra não esbarrar no rate limit (100/min).
MAX_CHAMADAS = 90


def _granatum_periodo(token, conta_id, inicio, fim, orcamento, profundidade=0):
    """
    Lançamentos da conta entre duas datas, cortando o período quando necessário.

    Por que não é uma consulta só: a API **ignora o parâmetro `page`** (pedir
    página 2 devolve exatamente a página 1) e corta a resposta em 50 itens,
    ficando com os mais ANTIGOS. Numa janela de 180 dias os 50 mais antigos são
    de fevereiro, então março em diante simplesmente não existe para quem
    pergunta — foi assim que IPTU, férias e mensalidades sumiram do briefing.

    Sem paginação, a única saída é perguntar por períodos curtos. Em vez de
    chutar um tamanho fixo (mês trunca em mês movimentado; semana desperdiça
    chamada em mês parado), o período se parte ao meio toda vez que a resposta
    vem no teto — o corte se ajusta sozinho ao movimento de cada conta.
    """
    if orcamento[0] <= 0:
        return []
    orcamento[0] -= 1

    dados = _granatum_get("lancamentos", {
        "access_token": token, "conta_id": conta_id,
        "data_inicio": inicio.isoformat(), "data_fim": fim.isoformat(),
    }) or []

    # Veio abaixo do teto: com certeza é tudo o que existe nesse intervalo.
    if len(dados) < TETO_RESPOSTA:
        return dados
    # Bateu no teto e não dá mais pra cortar: devolve o que veio.
    if inicio >= fim or profundidade >= MAX_CORTES:
        return dados

    meio = inicio + (fim - inicio) / 2
    esquerda = _granatum_periodo(token, conta_id, inicio, meio, orcamento, profundidade + 1)
    direita = _granatum_periodo(token, conta_id, meio + timedelta(days=1), fim,
                                orcamento, profundidade + 1)
    return esquerda + direita


def _granatum_lancamentos(token, conta_id, inicio, fim, orcamento):
    """Lançamentos únicos da conta no período (o corte pode repetir itens)."""
    vistos, unicos = set(), []
    for l in _granatum_periodo(token, conta_id, inicio, fim, orcamento):
        if l.get("id") not in vistos:
            vistos.add(l.get("id"))
            unicos.append(l)
    return unicos


def bloco_financeiro(agora):
    token = os.getenv("GRANATUM_TOKEN")
    if not token:
        return None  # fonte não configurada — bloco não aparece

    hoje = agora.date()
    inicio = hoje - timedelta(days=DIAS_ATRASO)

    orcamento = [MAX_CHAMADAS]  # compartilhado entre as contas
    lancamentos = []
    for conta in _granatum_contas(token):
        lancamentos.extend(_granatum_lancamentos(token, conta, inicio, hoje, orcamento))

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
        # Sair e entrar são somados SEPARADAMENTE de propósito: juntar os dois dá
        # o líquido, e um líquido no lugar do "a pagar" engana — mostraria
        # R$ 1.981 de total numa lista que tem uma conta de R$ 2.800.
        sai = sum(-v for _, v, _ in vence_hoje if v < 0)
        entra = sum(v for _, v, _ in vence_hoje if v > 0)
        resumo = []
        if sai:
            resumo.append(f"sai {_dinheiro(sai)}")
        if entra:
            resumo.append(f"entra {_dinheiro(entra)}")
        partes.append(f"  _Vence hoje_ ({', '.join(resumo)}):")
        for _, valor, desc in sorted(vence_hoje, key=lambda x: x[1]):
            sinal = "🔴" if valor < 0 else "🟢"
            partes.append(f"  {sinal} {desc} — {_dinheiro(abs(valor))}")
    if atrasados:
        # Mesma regra do "vence hoje": nada de líquido disfarçado de total.
        sai = sum(-v for _, v, _ in atrasados if v < 0)
        entra = sum(v for _, v, _ in atrasados if v > 0)
        resumo = []
        if sai:
            resumo.append(f"a pagar {_dinheiro(sai)}")
        if entra:
            resumo.append(f"a receber {_dinheiro(entra)}")
        partes.append(f"  ⚠️ _Atrasado_: {len(atrasados)} lançamento(s) — "
                      + ", ".join(resumo))
        # Ordem: mais RECENTE primeiro e, dentro do mesmo dia, o de MAIOR valor.
        # O que venceu ontem ainda dá pra resolver hoje; o de seis meses atrás
        # já virou faxina de outro dia. E o critério de valor importa: ordenando
        # só por data, uma conta de R$ 2.051 caía no "… e mais N" enquanto seis
        # contas de R$ 121 ocupavam a lista.
        ordenados = sorted(atrasados, key=lambda x: (x[0], abs(x[1])), reverse=True)
        for d, valor, desc in ordenados[:MAX_ATRASADOS]:
            partes.append(f"  · {d.strftime('%d/%m')} {desc} — {_dinheiro(abs(valor))}")
        if len(atrasados) > MAX_ATRASADOS:
            partes.append(f"  · … e mais {len(atrasados) - MAX_ATRASADOS}")
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
    ("pendentes",  bloco_pendentes,  True),
    ("radar",      bloco_radar,      True),
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
