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
from datetime import datetime, timedelta

import snapshot


def _sem_acento(texto):
    n = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def _dinheiro(valor):
    return f"R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dinheiro_com_sinal(valor):
    """Para SALDO, onde o sinal é a informação principal."""
    return ("-" if valor < 0 else "") + _dinheiro(valor)


def _limpar(texto, tamanho=38):
    """Tira o que quebra o Markdown do Telegram (um '*' solto recusa a mensagem)."""
    limpo = "".join(c for c in str(texto or "") if c not in "*_`[]")
    limpo = " ".join(limpo.split())
    return (limpo[:tamanho - 1] + "…") if len(limpo) > tamanho else (limpo or "(sem descrição)")


# ── Padrões de pergunta ──────────────────────────────────────────────────────
# Cada um: (nome da intenção, regex). Testados EM ORDEM; o primeiro que casar
# vence — por isso os períodos específicos ("ontem", "semana") vêm antes do
# genérico, senão "vendas de ontem" cairia no de hoje.
PADROES = [
    # --- financeiro ---
    ("atrasados",     r"\batrasad|\bem atraso\b|\bvencid[oa]s?\b|\bdevendo\b|quanto (eu )?devo"),

    # Os de PERÍODO vêm antes do "hoje" de propósito: o padrão de hoje contém
    # "o que vence", que também casa com "o que vence essa semana". Na ordem
    # errada, perguntar pela semana devolvia as contas de hoje — errado e
    # silencioso. Foi o teste de intenção exata que pegou isso.
    ("a_vencer_semana", r"(vence|vencer|venc\w+|pagar|despesas?|contas?).{0,20}"
                        r"(nessa|essa|esta|desta|da|na)\s+semana"),
    ("a_vencer_mes",    r"(vence|vencer|venc\w+|pagar|despesas?|contas?).{0,20}"
                        r"(nesse|esse|este|deste|do|no)\s+mes"),
    ("vence_hoje",    r"vence (hoje|agora)|\bo que vence\b|(contas?|pagar) (de )?hoje|a pagar hoje"),
    ("a_vencer",        r"\ba vencer\b|(o que|quais).{0,20}(vai|vao|vou) vencer"),
    ("maiores",       r"maior(es)? (conta|despesa|divida)|\bmaiores contas?\b"),
    # "quanto sobrou / resultado / lucro" — movimento de caixa do periodo.
    ("caixa_trimestre", r"(sobrou|resultado|lucro|saldo|balanco).{0,25}trimestre"
                        r"|trimestre.{0,25}(sobrou|resultado|lucro)"),
    ("caixa_mes",       r"(sobrou|resultado|lucro|saldo|balanco).{0,25}(nesse|esse|este|do|no)?\s*mes"
                        r"|quanto (eu )?(sobrou|lucrei|ganhei)"),
    # Guarda-chuva do financeiro. Vem DEPOIS dos especificos de proposito:
    # "contas a pagar essa semana" tem que cair no a_vencer_semana, nao aqui.
    ("resumo",        r"\bfinanceiro\b|como (esta|estao) as contas"
                      r"|^saldo\b|saldo (d[ae]s )?contas?|contas? (a|para|pra) pagar"
                      r"|^contas$|resumo (das )?contas"),

    # --- vendas (período específico primeiro) ---
    # Os padrões pedem o VERBO de venda ("vendeu", "faturou") ou a palavra
    # "vendas" perto do período. Um genérico solto tipo r"\bvendas?\b" seria
    # armadilha: "reunião de vendas amanhã" é COMPROMISSO, não pergunta.
    ("vendas_ontem",  r"(vend|fatur|pedid)\w*\s+(de\s+)?ontem|ontem.*(vendeu|vendi|faturou)"),
    ("vendas_semana", r"(vend|fatur|pedid)\w*\s+(d[ae]\s+)?semana|(vendeu|vendi|faturou).*semana"),
    ("vendas_mes",    r"(vend|fatur|pedid)\w*\s+(d[oe]\s+)?mes|(vendeu|vendi|faturou).*mes"),
    ("vendas_hoje",   r"(vend|fatur|pedid)\w*\s+(de\s+)?hoje|hoje.*(vendeu|vendi|faturou)"),
    # "faturamento" sozinho nao basta: "fechar o faturamento com a contadora
    # quarta" e compromisso. So conta como pergunta em forma interrogativa
    # ("qual o faturamento") ou como palavra unica da mensagem.
    ("vendas_hoje",   r"quant[oa]s?\s+(eu\s+)?(vendeu|vendi|vendemos|faturou|faturei|pedidos)"
                      r"|^/?vendas?$|^faturamento$|(qual|quanto)\s+\w*\s*faturamento"),

    # --- agenda (o /hoje e /semana continuam valendo; isto é a forma falada) ---
    # Idem: exigem forma claramente interrogativa. "tenho dentista amanhã" tem
    # que continuar virando COMPROMISSO.
    ("agenda_amanha", r"(agenda|compromissos?)\s+(de\s+|pra\s+|para\s+)?amanha"
                      r"|o que\s+(eu\s+)?(tenho|tem)\s+.*amanha"
                      r"|(tenho|tem)\s+(algo|alguma coisa)\s+.*amanha"),
    ("agenda_semana", r"(agenda|compromissos?)\s+(d[ae]\s+|pra\s+|para\s+)?semana"
                      r"|o que\s+(eu\s+)?(tenho|tem)\s+.*semana"
                      r"|(tenho|tem)\s+(algo|alguma coisa)\s+.*semana"),
    # "do dia" é tão comum quanto "de hoje" — exigir a palavra "hoje" era
    # exigência à toa (foi assim que "compromissos do dia" caiu no caderninho).
    ("agenda_hoje",   r"(agenda|compromissos?)\s+(de\s+|pra\s+|para\s+|d[oa]\s+)?(hoje|dia)\b"
                      r"|o que\s+(eu\s+)?(tenho|tem)\s+.*hoje"
                      r"|(tenho|tem)\s+(algo|alguma coisa)\s+.*hoje"
                      r"|^minha agenda$|^agenda$|^compromissos$"),
]

COMANDOS = {
    "/atrasados":  "atrasados",
    "/financeiro": "resumo",
    "/vencehoje":  "vence_hoje",
    "/vendas":     "vendas_hoje",
}

# Intenções que precisam do Google Calendar (o bot passa o serviço adiante).
PRECISAM_AGENDA = {"agenda_hoje", "agenda_amanha", "agenda_semana"}


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


# ── 🏦 Reconhecer a conta citada na frase ────────────────────────────────────
# Palavras que aparecem em nome de conta mas não distinguem uma da outra.
GENERICAS = {"conta", "contas", "de", "do", "da", "di", "das", "dos", "e"}


def _tokens(nome):
    """Palavras significativas de um nome de conta, sem acento nem pontuação."""
    limpo = _sem_acento(nome)
    limpo = "".join(c if c.isalnum() else " " for c in limpo)
    return [t for t in limpo.split() if len(t) >= 3 and t not in GENERICAS]


def identificar_conta(texto, dados):
    """
    Qual conta a frase cita? None = nenhuma (a resposta vale para todas).

    "saldo conta sol di verao" tem que responder SÓ da Sol di Verão — antes
    ele devolvia o consolidado e ignorava o nome, o que é pior que não
    entender: parece que respondeu.

    A comparação é por palavra significativa, não pelo nome exato, porque
    ninguém digita "M.O FRANCISCO" nem "CAIXA CAP FEL" como está cadastrado.
    Empate vai para quem casou mais palavras ("cap fel" ganha de "caixa").
    """
    contas = (dados or {}).get("contas") or []
    if not contas:
        return None
    frase = _sem_acento(texto)

    melhor, pontos_melhor = None, 0
    for c in contas:
        toks = _tokens(c.get("nome", ""))
        if not toks:
            continue
        pontos = sum(1 for t in toks if t in frase)
        if pontos > pontos_melhor:
            melhor, pontos_melhor = c, pontos
    return melhor


def _so_da_conta(abertos, conta):
    if not conta:
        return abertos
    return [a for a in abertos if a.get("conta") == conta["nome"]]


def _texto_saldo_conta(conta, abertos):
    """Saldo da conta + o que ela tem em aberto."""
    meus = _so_da_conta(abertos, conta)
    atrasados = [a for a in meus if a["situacao"] == "atrasado"]
    hoje = [a for a in meus if a["situacao"] == "hoje"]
    futuros = [a for a in meus if a["situacao"] == "futuro"]

    saldo = conta.get("saldo", 0.0)
    icone = "🟢" if saldo >= 0 else "🔴"
    linhas = [f"🏦 *{_limpar(conta['nome'], 30)}*",
              f"  {icone} saldo: *{_dinheiro_com_sinal(saldo)}*"]

    def bloco(rotulo, itens, emoji):
        if not itens:
            return
        sai = sum(-a["valor"] for a in itens if a["valor"] < 0)
        linhas.append(f"  {emoji} {rotulo}: *{len(itens)}* — {_dinheiro(sai)}")

    bloco("atrasado", atrasados, "⚠️")
    bloco("vence hoje", hoje, "📅")
    bloco("a vencer", futuros, "🔜")
    if not (atrasados or hoje or futuros):
        linhas.append("  ✅ nada em aberto nesta conta")
    return "\n".join(linhas)


# ── 🛒 Vendas ────────────────────────────────────────────────────────────────
PERIODOS = {
    "vendas_hoje":   ("hoje",   "hoje"),
    "vendas_ontem":  ("ontem",  "ontem"),
    "vendas_semana": ("semana", "nos últimos 7 dias"),
    "vendas_mes":    ("mes",    "nos últimos 30 dias"),
}


def _vendas_ao_vivo(chave):
    """
    Consulta a Shopify na hora. Devolve None se as chaves não estiverem aqui.

    A Shopify responde em ~0,3s, então dá pra consultar ao vivo — mas só se as
    variáveis existirem no ambiente onde o bot roda (no Vercel elas são
    configuração à parte). Sem elas, quem responde é a fotografia.
    """
    import os
    loja, token = os.getenv("SHOPIFY_STORE"), os.getenv("SHOPIFY_TOKEN")
    if not loja or not token:
        return None
    try:
        import snapshot as s
        import assessor as app
        resumo = s.coletar_vendas(datetime.now(app.TZ))
        return (resumo or {}).get(chave)
    except Exception:
        return None  # qualquer tropeço: cai pra fotografia


def _texto_vendas(intencao, dados):
    chave, rotulo = PERIODOS[intencao]

    venda = _vendas_ao_vivo(chave)
    ao_vivo = venda is not None
    if venda is None:
        venda = ((dados or {}).get("vendas") or {}).get(chave)

    if venda is None:
        return ("🤔 Ainda não conheço as vendas.\n"
                "Elas entram na próxima fotografia (de hora em hora).")

    n, total = venda.get("pedidos", 0), venda.get("total", 0.0)
    if not n:
        return f"🛒 *Nenhum pedido {rotulo}.*" + ("" if ao_vivo else _rodape(dados))

    ticket = total / n
    corpo = (f"🛒 *{n} pedido{'s' if n > 1 else ''} {rotulo}* — {_dinheiro(total)}\n"
             f"  _ticket médio_ {_dinheiro(ticket)}")
    return corpo + ("\n\n_agora mesmo_" if ao_vivo else _rodape(dados))


# ── 📅 Agenda ────────────────────────────────────────────────────────────────
JANELAS = {
    "agenda_hoje":   (0, 1, "Hoje"),
    "agenda_amanha": (1, 2, "Amanhã"),
    "agenda_semana": (0, 7, "Próximos 7 dias"),
}


def _texto_agenda(intencao, svc):
    import assessor as app
    from datetime import timedelta

    de_dias, ate_dias, titulo = JANELAS[intencao]
    agora = datetime.now(app.TZ)
    inicio = (agora + timedelta(days=de_dias)).replace(hour=0, minute=0, second=0, microsecond=0)
    if de_dias == 0:
        inicio = agora  # hoje começa agora, não à meia-noite
    fim = (agora + timedelta(days=ate_dias)).replace(hour=0, minute=0, second=0, microsecond=0)

    evs = app.eventos_entre(svc, inicio, fim)
    if not evs:
        return f"📅 *{titulo}* — nada marcado. 🌴"

    linhas = []
    for ev in evs[:12]:
        ini = ev["start"].get("dateTime")
        if ini:
            d = datetime.fromisoformat(ini).astimezone(app.TZ)
            quando = (d.strftime("%H:%M") if ate_dias - de_dias <= 1
                      else f"{app.DIAS_SEMANA[d.weekday()]} {d.strftime('%d/%m %H:%M')}")
        else:
            quando = "dia todo"
        linhas.append(f"  · {quando} — {_limpar(ev.get('summary'), 42)}")
    if len(evs) > 12:
        linhas.append(f"  · … e mais {len(evs) - 12}")
    return f"📅 *{titulo}* — {len(evs)} compromisso(s)\n" + "\n".join(linhas)


def _rodape(dados):
    return f"\n\n_dados de {_idade(dados)}_" if dados else ""


def responder(intencao, limite=12, svc=None, texto=""):
    """Monta o texto da resposta. Devolve None se não houver fotografia ainda."""
    if intencao in JANELAS:
        if svc is None:
            return None  # sem acesso à agenda: deixa a frase seguir o caminho normal
        return _texto_agenda(intencao, svc)

    dados = snapshot.carregar()

    if intencao in PERIODOS:
        return _texto_vendas(intencao, dados)

    if not dados:
        return ("🤔 Ainda não tenho a fotografia do financeiro.\n"
                "Ela é tirada de hora em hora pelo robô da nuvem — "
                "tenta de novo daqui a pouco.")

    abertos = dados.get("abertos", [])

    # A frase citou uma conta? Então tudo daqui pra baixo é só dela.
    conta = identificar_conta(texto, dados)
    filtro = ""
    if conta:
        # "saldo da conta X" pede o saldo, não a lista — é outra resposta.
        if intencao == "resumo" or "saldo" in _sem_acento(texto):
            return _texto_saldo_conta(conta, abertos) + f"\n\n_dados de {_idade(dados)}_"
        abertos = _so_da_conta(abertos, conta)
        # Aviso obrigatório: sem ele, "Nada atrasado. Tudo em dia!" filtrado por
        # uma conta parece dizer que TUDO está em dia — e não está.
        filtro = f"\n_(só da conta {_limpar(conta['nome'], 24)})_"
    atrasados = [a for a in abertos if a["situacao"] == "atrasado"]
    hoje = [a for a in abertos if a["situacao"] == "hoje"]
    rodape = filtro + f"\n\n_dados de {_idade(dados)}_"

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

    if intencao == "vence_hoje":
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

    if intencao in ("a_vencer", "a_vencer_semana", "a_vencer_mes"):
        futuros = [a for a in abertos if a["situacao"] == "futuro"]
        dias = {"a_vencer_semana": 7, "a_vencer_mes": 30}.get(intencao, 30)
        rotulo = {"a_vencer_semana": "nos próximos 7 dias",
                  "a_vencer_mes": "nos próximos 30 dias"}.get(intencao, "a vencer")
        limite_data = (datetime.fromisoformat(dados["referencia"]).date()
                       + timedelta(days=dias)).isoformat()
        proximos = [a for a in futuros if a["data"] <= limite_data]
        if not proximos:
            return f"✅ *Nada vencendo {rotulo}.*" + rodape
        sai = sum(-a["valor"] for a in proximos if a["valor"] < 0)
        entra = sum(a["valor"] for a in proximos if a["valor"] > 0)
        resumo = []
        if sai:
            resumo.append(f"a pagar {_dinheiro(sai)}")
        if entra:
            resumo.append(f"a receber {_dinheiro(entra)}")
        cab = [f"🔜 *{len(proximos)} conta(s) {rotulo}* — " + ", ".join(resumo)]
        # Por data crescente: o que vence primeiro é o que você resolve primeiro.
        ordenados = sorted(proximos, key=lambda x: (x["data"], -abs(x["valor"])))
        return "\n".join(cab + _linhas(ordenados, limite)) + rodape

    if intencao in ("caixa_mes", "caixa_trimestre"):
        chave = "mes" if intencao == "caixa_mes" else "trimestre"
        mov = (dados.get("movimento") or {}).get(chave)
        if not mov:
            return ("🤔 Não tenho esse período fechado.\n"
                    "_A fotografia só calcula período que ela cobre inteiro — "
                    "melhor não ter número do que ter número errado._" + rodape)
        nome = "neste mês" if chave == "mes" else "no trimestre"
        desde = datetime.fromisoformat(mov["desde"]).strftime("%d/%m")
        saldo = mov["saldo"]
        icone = "🟢" if saldo >= 0 else "🔴"
        return (f"{icone} *Caixa {nome}* (desde {desde})\n"
                f"  ⬆️ entrou {_dinheiro(mov['entrou'])}\n"
                f"  ⬇️ saiu {_dinheiro(mov['saiu'])}\n"
                f"  *{'sobrou' if saldo >= 0 else 'faltou'} {_dinheiro(saldo)}*\n\n"
                "_É caixa: dinheiro que entrou menos o que saiu, pela data de "
                "pagamento. Não é lucro contábil — estoque, competência e "
                "depreciação ficam de fora. Pra lucro de verdade, o DRE no "
                "Granatum._" + rodape)

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
        mov = (dados.get("movimento") or {}).get("mes")
        if mov:
            sinal = "sobrou" if mov["saldo"] >= 0 else "faltou"
            linhas.append(f"  💵 Caixa do mês: {sinal} {_dinheiro(mov['saldo'])}")
        linhas.append("\n  _Pergunte:_ atrasados · vence hoje · o que vence essa "
                      "semana · maiores contas · quanto sobrou esse mês · "
                      "quanto vendeu hoje")
        return "\n".join(linhas) + rodape

    return None


def tratar(texto, svc=None):
    """Atalho: identifica e responde. None = não era pergunta que eu saiba tratar."""
    intencao = identificar(texto)
    return responder(intencao, svc=svc, texto=texto) if intencao else None


if __name__ == "__main__":
    # Teste rápido: python consultas.py "quanto vendeu hoje?"
    import sys
    frases = sys.argv[1:] or [
        "quais estao atrasadas?", "quanto devo", "o que vence hoje",
        "quanto vendeu hoje?", "quanto vendeu ontem", "vendas da semana",
        "faturamento do mes", "/financeiro", "maiores contas",
        "dentista amanha as 10h",
    ]
    for f in frases:
        intencao = identificar(f)
        print(f"\n=== {f!r} -> {intencao or 'NAO E PERGUNTA (vira compromisso)'}")
        if intencao and intencao not in JANELAS:
            # texto=f é essencial: é dele que sai a conta citada na frase.
            print(responder(intencao, limite=4, texto=f))
        elif intencao:
            print("   (precisa da agenda — testado pelo bot)")
