# -*- coding: utf-8 -*-
"""
Cobrança de tarefas — o bot pergunta se você fez, e só larga do seu pé
quando você responde.

Como funciona:
  1. Passou a hora do compromisso? Pouco depois do fim, o bot pergunta:
     "❓ Você fez isso?" com três botões.
  2. ✅ *Fiz*          -> o compromisso é APAGADO da agenda. Acabou.
  3. ⏳ *Ainda não*    -> continua na agenda, continua aparecendo no /hoje,
                          no bom dia e no briefing, e é cobrado de novo.
  4. 🔕 *Parar de cobrar* -> fica na agenda, mas o bot cala a boca sobre ele.
     (Válvula de escape: sem isso, um compromisso recorrente que você não quer
     confirmar toda semana transforma o assessor num chato.)

Onde fica guardado: no próprio evento do Google Calendar
(`extendedProperties.private`), do mesmo jeito que os lembretes já fazem.
Zero banco de dados, zero estado no repositório.

Regras de convivência (o motivo de cada uma está na constante):
  • Nunca cobra de madrugada.
  • Nunca cobra evento de dia inteiro.
  • Cobra menos vezes conforme a tarefa envelhece, em vez de martelar igual.

Uso na mão:
    python pendencias.py            # lista o que está em aberto (não envia nada)
    python pendencias.py --cobrar   # roda a cobrança de verdade, agora
    python pendencias.py --testar   # manda UMA cobrança de exemplo, pra você
                                    # ver como chega e testar os botões
"""
import sys
from datetime import datetime, timedelta

import assessor as app

# ── Ajustes de convivência ───────────────────────────────────────────────────

# Quanto tempo depois do FIM do compromisso o bot pergunta. Perguntar no
# minuto exato do fim pega você ainda dentro da reunião.
FOLGA_MIN = 10

# Só cobra dentro deste horário. Um compromisso das 22h terminaria 23h e a
# recobrança cairia de madrugada — alarme noturno faz a pessoa silenciar o bot
# inteiro, e aí ela perde também os avisos que importam.
HORA_INICIO, HORA_FIM = 8, 22

# Intervalo entre cobranças = BASE × (quantas vezes já cobrei), com teto.
# Cresce de propósito: uma tarefa que você adia há uma semana não fica mais
# urgente sendo perguntada de 4 em 4 horas — vira ruído e você para de ler.
HORAS_ENTRE_COBRANCAS = 4
HORAS_MAXIMO = 24

# Quanto tempo pra trás o bot enxerga tarefa não confirmada.
DIAS_MEMORIA = 14

# Só começa a cobrar algo que terminou há menos que isto. Sem esse limite, a
# primeira vez que o recurso rodasse ele despejaria uma cobrança para cada
# compromisso das últimas duas semanas de uma vez só.
HORAS_PRIMEIRA_COBRANCA = 72

# Teto de mensagens por rodada, pra nunca virar enxurrada no Telegram.
MAX_POR_RODADA = 4


# ── Leitura do evento ────────────────────────────────────────────────────────
def _priv(ev):
    return (ev.get("extendedProperties", {}) or {}).get("private", {}) or {}


def _marcar(svc, ev, **campos):
    """Grava marcas no próprio evento (mesma técnica dos lembretes)."""
    priv = dict(_priv(ev))
    priv.update({k: str(v) for k, v in campos.items()})
    svc.events().patch(
        calendarId=app.CAL_ID, eventId=ev["id"],
        body={"extendedProperties": {"private": priv}},
    ).execute()
    ev.setdefault("extendedProperties", {})["private"] = priv


def _limpar(texto, tamanho=60):
    """Tira o que quebra o Markdown do Telegram (um '_' solto recusa a mensagem)."""
    limpo = " ".join("".join(c for c in str(texto or "") if c not in "*_`[]").split())
    if len(limpo) > tamanho:
        limpo = limpo[: tamanho - 1].rstrip() + "…"
    return limpo or "(sem título)"


def fim_do_evento(ev):
    """Quando o compromisso terminou. None se for de dia inteiro."""
    fim = (ev.get("end") or {}).get("dateTime")
    if not fim:
        # Dia inteiro não é tarefa com hora marcada — e é justamente assim que
        # o caderninho do /naoentendi guarda as frases (eventos em 01/01/2000).
        # Cobrar isso perguntaria ao dono se ele "fez" uma anotação interna.
        return None
    try:
        return datetime.fromisoformat(fim).astimezone(app.TZ)
    except ValueError:
        return None


def concluido(ev):
    return str(ev.get("summary") or "").startswith("✅")


def silenciado(ev):
    return _priv(ev).get("nao_cobrar") == "1"


def _cobrancas(ev):
    try:
        return int(_priv(ev).get("cobrancas") or 0)
    except ValueError:
        return 0


def _cobrado_em(ev):
    quando = _priv(ev).get("cobrado_em")
    if not quando:
        return None
    try:
        return datetime.fromisoformat(quando).astimezone(app.TZ)
    except ValueError:
        return None


# ── Quem está pendente ───────────────────────────────────────────────────────
def listar(svc, agora=None):
    """
    As tarefas que já passaram e você não confirmou — as que "continuam
    aparecendo". É esta lista que o /hoje, o bom dia e o briefing mostram.
    """
    agora = agora or datetime.now(app.TZ)
    inicio = agora - timedelta(days=DIAS_MEMORIA)
    corte = agora - timedelta(minutes=FOLGA_MIN)

    pendentes = []
    for ev in app.eventos_entre(svc, inicio, agora):
        fim = fim_do_evento(ev)
        if not fim or fim > corte:
            continue                      # ainda rolando (ou dia inteiro)
        if concluido(ev) or silenciado(ev):
            continue
        pendentes.append(ev)
    pendentes.sort(key=lambda e: fim_do_evento(e))
    return pendentes


def _pode_falar(agora):
    return HORA_INICIO <= agora.hour < HORA_FIM


def _esta_na_hora(ev, agora):
    """Este pendente merece uma mensagem agora?"""
    ultima = _cobrado_em(ev)
    if ultima is None:
        # Primeira cobrança: só se for coisa recente. Tarefa de duas semanas
        # atrás que nunca foi cobrada é histórico, não pendência nova.
        fim = fim_do_evento(ev)
        return (agora - fim) <= timedelta(hours=HORAS_PRIMEIRA_COBRANCA)
    espera = min(HORAS_ENTRE_COBRANCAS * max(_cobrancas(ev), 1), HORAS_MAXIMO)
    return (agora - ultima) >= timedelta(hours=espera)


def texto_cobranca(ev):
    fim = fim_do_evento(ev)
    inicio = (ev.get("start") or {}).get("dateTime")
    quando = app.formatar_quando(datetime.fromisoformat(inicio).astimezone(app.TZ)) \
        if inicio else app.formatar_quando(fim)
    vezes = _cobrancas(ev)
    insistindo = "\n\n_(já perguntei antes — some da lista assim que você responder)_" \
        if vezes >= 2 else ""
    return (f"❓ *Você fez isso?*\n"
            f"*{_limpar(ev.get('summary'))}* — era {quando}.{insistindo}")


def botoes(ev):
    """
    Teclado da cobrança. `callback_data` do Telegram tem teto de 64 bytes e o
    prefixo come 4 — sem espaço, mandamos sem botão em vez de mandar quebrado.
    """
    cid = ev["id"]
    if len(cid) > 58:
        return None
    return [[
        {"text": "✅ Fiz",        "callback_data": f"fiz:{cid}"},
        {"text": "⏳ Ainda não",  "callback_data": f"ain:{cid}"},
    ], [
        {"text": "🔕 Parar de cobrar", "callback_data": f"mut:{cid}"},
    ]]


def cobrar(svc, agora=None):
    """Manda as cobranças da vez. Devolve quantas foram."""
    agora = agora or datetime.now(app.TZ)
    if not _pode_falar(agora):
        return 0

    enviadas = 0
    for ev in listar(svc, agora):
        if enviadas >= MAX_POR_RODADA:
            break
        if not _esta_na_hora(ev, agora):
            continue
        app.enviar(texto_cobranca(ev), botoes=botoes(ev))
        # Marca DEPOIS de enviar: se o Telegram falhar, a cobrança não é dada
        # como feita e o próximo vigia tenta de novo.
        _marcar(svc, ev, cobrado_em=agora.isoformat(), cobrancas=_cobrancas(ev) + 1)
        enviadas += 1
    return enviadas


# ── Resposta aos botões ──────────────────────────────────────────────────────
def resolver(svc, acao, event_id, agora=None):
    """
    Trata o toque. Devolve (aviso_curto, texto_que_substitui_a_mensagem)
    ou None se a ação não é daqui.
    """
    agora = agora or datetime.now(app.TZ)
    if acao == "fiz":
        # Confirmou -> some da agenda de vez, como o dono pediu. Em compromisso
        # que se repete, apaga só a ocorrência: a série continua.
        titulo = app.apagar_evento(svc, event_id)
        return "✅ Boa!", f"✅ *Feito:* {_limpar(titulo)}\n_(apaguei da agenda)_"

    if acao == "ain":
        ev = svc.events().get(calendarId=app.CAL_ID, eventId=event_id).execute()
        # Zera a contagem: você respondeu, então a próxima cobrança volta ao
        # intervalo curto em vez de continuar espaçando como se fosse ignorada.
        _marcar(svc, ev, cobrado_em=agora.isoformat(), cobrancas=1)
        return "⏳ Fica na lista.", (f"⏳ *Ainda pendente:* {_limpar(ev.get('summary'))}\n"
                                    "_(continua aparecendo até você confirmar)_")

    if acao == "mut":
        ev = svc.events().get(calendarId=app.CAL_ID, eventId=event_id).execute()
        _marcar(svc, ev, nao_cobrar="1")
        return "🔕 Não cobro mais.", (f"🔕 *Parei de cobrar:* {_limpar(ev.get('summary'))}\n"
                                      "_(continua na agenda, só não pergunto mais)_")
    return None


# ── Como os pendentes aparecem nas listas ────────────────────────────────────
def _ha_quanto(fim, agora):
    dias = (agora.date() - fim.date()).days
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "ontem"
    return f"há {dias} dias"


def linhas(svc, agora=None, limite=5):
    """Linhas prontas pro bom dia e pro briefing. Lista vazia se não há nada."""
    agora = agora or datetime.now(app.TZ)
    pend = listar(svc, agora)
    if not pend:
        return []
    saida = [f"⏳ *Pendentes* ({len(pend)}) — não confirmados"]
    for ev in pend[:limite]:
        fim = fim_do_evento(ev)
        saida.append(f"• {_ha_quanto(fim, agora)} — {_limpar(ev.get('summary'), 45)}")
    if len(pend) > limite:
        saida.append(f"• … e mais {len(pend) - limite}")
    return saida


# ── Uso na mão ───────────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    app.checar_credenciais()
    svc = app.calendario()
    agora = datetime.now(app.TZ)
    pend = listar(svc, agora)

    print(f"⏳ {len(pend)} pendente(s):")
    for ev in pend:
        marca = "cobrado" if _cobrado_em(ev) else "sem cobrança"
        print(f"   {fim_do_evento(ev).strftime('%d/%m %H:%M')}  "
              f"{_limpar(ev.get('summary'), 45):<46} ({marca})")

    if "--cobrar" in sys.argv:
        print(f"\n📨 {cobrar(svc, agora)} cobrança(s) enviada(s).")
    elif "--testar" in sys.argv:
        if not pend:
            print("\nNada pendente — nada pra mostrar.")
            return
        ev = pend[-1]                      # o mais recente
        app.enviar(texto_cobranca(ev), botoes=botoes(ev))
        print(f"\n📨 exemplo enviado: {_limpar(ev.get('summary'))}")
        print("   (não marquei como cobrado — é só uma amostra)")
    else:
        print("\n(nada foi enviado — use --cobrar ou --testar)")


if __name__ == "__main__":
    main()
