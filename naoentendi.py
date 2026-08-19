# -*- coding: utf-8 -*-
"""
Caderninho das perguntas que o bot não entendeu.

Serve para decidir com DADO, não com palpite, quais frases vale a pena ensinar.
Quando você pergunta algo fora dos padrões conhecidos, o bot responde que não
entendeu — e anota a frase aqui. Depois é só rodar /naoentendi, mandar a lista
numa sessão do Claude Code (que já está paga no seu plano) e as frases
recorrentes viram padrões novos em consultas.py: grátis e instantâneas pra
sempre, sem API cobrada por pergunta.

ONDE ISSO FICA GUARDADO, e por quê:
o webhook do Telegram roda no Vercel, que **não tem disco pra gravar** — é a
única parte do sistema que enxerga suas mensagens, e não pode escrever arquivo
nem commitar no repositório. Mas o Google Calendar já está autenticado ali, e o
projeto inteiro já usa `extendedProperties` de eventos como memória (é assim que
ele lembra "já mandei esse lembrete"). Então cada frase vira um evento de dia
inteiro numa data-âncora no ano 2000.

Por que o ano 2000: tudo que lê a agenda (lembretes, /hoje, /semana, briefing,
radar) pergunta a partir de AGORA para frente. Eventos de 2000 nunca entram em
nenhuma dessas janelas — ficam invisíveis pra você e inertes pro resto do
sistema, mas continuam consultáveis por marcador.

Frase repetida não cria evento novo: incrementa um contador. A frequência é
justamente o que decide o que ensinar primeiro.
"""
from datetime import date, datetime

import assessor as app

# Data-âncora: qualquer data bem no passado serve. Eventos aqui nunca aparecem
# nas janelas que o assessor consulta (todas começam em "agora").
ANCORA = date(2000, 1, 1)
MARCADOR = "assessor_naoentendi"
LIMITE_FRASE = 180


def _eventos(svc):
    """Todos os registros do caderninho, via marcador (não por data)."""
    r = svc.events().list(
        calendarId=app.CAL_ID,
        privateExtendedProperty=f"{MARCADOR}=1",
        maxResults=250,
        showDeleted=False,
    ).execute()
    return r.get("items", [])


def registrar(svc, frase):
    """Anota a frase. Se já existia, só incrementa o contador."""
    frase = " ".join(str(frase or "").split())[:LIMITE_FRASE]
    if not frase:
        return

    agora = datetime.now(app.TZ)

    # Já anotada antes? Compara sem diferenciar maiúscula/minúscula.
    for ev in _eventos(svc):
        if (ev.get("summary") or "").strip().lower() == frase.lower():
            priv = (ev.get("extendedProperties", {}) or {}).get("private", {}) or {}
            try:
                vezes = int(priv.get("vezes", "1"))
            except ValueError:
                vezes = 1
            priv["vezes"] = str(vezes + 1)
            priv["ultima"] = agora.isoformat()
            svc.events().patch(
                calendarId=app.CAL_ID, eventId=ev["id"],
                body={"extendedProperties": {"private": priv}},
            ).execute()
            return

    svc.events().insert(calendarId=app.CAL_ID, body={
        "summary": frase,
        "description": "Pergunta que o assessor não entendeu. "
                       "Registro interno — pode apagar com /naoentendi limpar.",
        "start": {"date": ANCORA.isoformat()},
        "end":   {"date": ANCORA.isoformat()},
        "transparency": "transparent",   # não ocupa horário
        "extendedProperties": {"private": {
            MARCADOR: "1",
            "vezes": "1",
            "primeira": agora.isoformat(),
            "ultima": agora.isoformat(),
        }},
    }).execute()


def listar(svc):
    """[(vezes, frase, ultima), ...] das mais frequentes para as menos."""
    saida = []
    for ev in _eventos(svc):
        priv = (ev.get("extendedProperties", {}) or {}).get("private", {}) or {}
        try:
            vezes = int(priv.get("vezes", "1"))
        except ValueError:
            vezes = 1
        saida.append((vezes, ev.get("summary", ""), priv.get("ultima", "")))
    saida.sort(key=lambda x: (-x[0], x[2]))
    return saida


def limpar(svc):
    """Apaga o caderninho. Devolve quantos registros sumiram."""
    eventos = _eventos(svc)
    for ev in eventos:
        try:
            svc.events().delete(calendarId=app.CAL_ID, eventId=ev["id"]).execute()
        except Exception:
            pass
    return len(eventos)


def texto(svc):
    """Mensagem pronta pro Telegram."""
    itens = listar(svc)
    if not itens:
        return ("📝 *Caderninho vazio.*\nNão tem pergunta pendente de aprender — "
                "o bot entendeu tudo até agora. 👏")

    linhas = ["📝 *Perguntas que eu não entendi*", ""]
    for vezes, frase, _ in itens[:25]:
        limpa = "".join(c for c in frase if c not in "*_`[]")
        marca = f" _({vezes}x)_" if vezes > 1 else ""
        linhas.append(f"  · {limpa}{marca}")
    if len(itens) > 25:
        linhas.append(f"  · … e mais {len(itens) - 25}")

    total = sum(v for v, _, _ in itens)
    linhas.append("")
    linhas.append(f"_{len(itens)} frase(s) diferente(s), {total} tentativa(s)._")
    linhas.append("Manda essa lista pro Claude Code que eu ensino as recorrentes. "
                  "Pra zerar: `/naoentendi limpar`")
    return "\n".join(linhas)
