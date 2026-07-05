"""
assessor.py
Seu assessor pessoal de compromissos, via Telegram + Google Calendar.

O que ele faz, toda vez que roda (a cada 15 min, na nuvem):
  1. LÊ suas mensagens novas no Telegram.
       - Frase livre ("reunião amanhã 15h")  -> entende (IA) e cria o evento no Google Calendar.
       - /hoje                                -> lista os compromissos de hoje.
       - /semana                              -> lista os próximos 7 dias.
       - /ajuda ou /start                     -> mostra a ajuda.
  2. CONFERE a agenda e manda LEMBRETES:
       - 1 dia antes de cada compromisso.
       - 1 hora antes de cada compromisso.
     (nunca repete o mesmo lembrete — marca no próprio evento que já avisou.)

Não guarda nada no repositório: o "já li essa mensagem" fica no servidor do Telegram,
e o "já mandei esse lembrete" fica gravado no próprio evento do Google Calendar.

Uso local (pra testar):  python assessor.py
"""

import os
import re
import sys
import json
import requests
from datetime import datetime, timedelta, date, time as dtime
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Pasta onde este script está (pra achar .env e a credencial de qualquer lugar).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Carrega o .env quando roda no seu PC (na nuvem as variáveis já vêm prontas).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass

# ── Configuração ─────────────────────────────────────────────────────────────
TZ        = ZoneInfo("America/Sao_Paulo")

TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT    = os.getenv("TELEGRAM_CHAT_ID")        # só respondemos VOCÊ (segurança)
CAL_ID     = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CRED_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
# Se o caminho for relativo, procura ao lado do script.
if not os.path.isabs(GOOGLE_CRED_FILE):
    GOOGLE_CRED_FILE = os.path.join(BASE_DIR, GOOGLE_CRED_FILE)

# Lembretes: (rótulo interno, quanto antes avisar)
LEMBRETES = [
    ("1d", timedelta(days=1)),
    ("1h", timedelta(hours=1)),
]

MESES = ["", "jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez"]
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# Emojis/acentos no console do Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def checar_credenciais():
    faltando = [n for n, v in {
        "TELEGRAM_BOT_TOKEN": TG_TOKEN,
        "TELEGRAM_CHAT_ID":   TG_CHAT,
    }.items() if not v]
    # A credencial do Google pode vir de um arquivo (local/GitHub) OU
    # de uma variável de ambiente GOOGLE_CREDENTIALS com o JSON (Vercel).
    if not os.getenv("GOOGLE_CREDENTIALS") and not os.path.exists(GOOGLE_CRED_FILE):
        faltando.append("credencial do Google (arquivo ou variável GOOGLE_CREDENTIALS)")
    if faltando:
        raise SystemExit("❌ Faltam credenciais: " + ", ".join(faltando))


# ── Telegram ─────────────────────────────────────────────────────────────────
def tg(metodo, **params):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/{metodo}",
                      json=params, timeout=30)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {j.get('description')}")
    return j["result"]


def enviar(texto):
    """Manda uma mensagem pra você."""
    tg("sendMessage", chat_id=TG_CHAT, text=texto, parse_mode="Markdown")


def ler_mensagens():
    """Pega as mensagens ainda não lidas e as marca como lidas no servidor do Telegram."""
    updates = tg("getUpdates", timeout=0)
    if not updates:
        return []
    ultimo = updates[-1]["update_id"]
    # Confirma (consome) tudo o que lemos — assim não relemos na próxima rodada.
    tg("getUpdates", offset=ultimo + 1, timeout=0)

    mensagens = []
    for u in updates:
        msg = u.get("message") or u.get("edited_message")
        if not msg or "text" not in msg:
            continue
        # Só ouvimos VOCÊ.
        if str(msg["chat"]["id"]) != str(TG_CHAT):
            continue
        mensagens.append(msg["text"].strip())
    return mensagens


# ── Google Calendar ──────────────────────────────────────────────────────────
def calendario():
    escopo = ["https://www.googleapis.com/auth/calendar"]
    cred_json = os.getenv("GOOGLE_CREDENTIALS")   # JSON direto na variável (Vercel)
    if cred_json:
        cred = service_account.Credentials.from_service_account_info(
            json.loads(cred_json), scopes=escopo)
    else:                                          # arquivo (local / GitHub Actions)
        cred = service_account.Credentials.from_service_account_file(
            GOOGLE_CRED_FILE, scopes=escopo)
    return build("calendar", "v3", credentials=cred, cache_discovery=False)


def criar_evento(svc, titulo, inicio_iso, duracao_min, rrule=None):
    inicio = datetime.fromisoformat(inicio_iso)
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=TZ)
    fim = inicio + timedelta(minutes=duracao_min or 60)
    corpo = {
        "summary": titulo,
        "start": {"dateTime": inicio.replace(tzinfo=None).isoformat(),
                  "timeZone": "America/Sao_Paulo"},
        "end":   {"dateTime": fim.replace(tzinfo=None).isoformat(),
                  "timeZone": "America/Sao_Paulo"},
    }
    if rrule:
        corpo["recurrence"] = [rrule if rrule.startswith("RRULE:") else f"RRULE:{rrule}"]
    svc.events().insert(calendarId=CAL_ID, body=corpo).execute()
    return inicio


def eventos_entre(svc, inicio, fim):
    r = svc.events().list(
        calendarId=CAL_ID,
        timeMin=inicio.isoformat(),
        timeMax=fim.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return r.get("items", [])


def marcar_lembrete_enviado(svc, evento, rotulo):
    priv = (evento.get("extendedProperties", {}) or {}).get("private", {}) or {}
    priv[f"lembrete_{rotulo}"] = "1"
    svc.events().patch(
        calendarId=CAL_ID, eventId=evento["id"],
        body={"extendedProperties": {"private": priv}},
    ).execute()


def ja_avisou(evento, rotulo):
    priv = (evento.get("extendedProperties", {}) or {}).get("private", {}) or {}
    return priv.get(f"lembrete_{rotulo}") == "1"


# ── Entender a frase (grátis, sem depender de nada externo) ───────────────────
# Dias da semana em português -> código RRULE / número (segunda=0 ... domingo=6)
DIAS_RRULE = {
    "segunda": ("MO", 0), "seg": ("MO", 0),
    "terça":   ("TU", 1), "terca": ("TU", 1),
    "quarta":  ("WE", 2), "qua": ("WE", 2),
    "quinta":  ("TH", 3), "qui": ("TH", 3),
    "sexta":   ("FR", 4), "sex": ("FR", 4),
    "sábado":  ("SA", 5), "sabado": ("SA", 5), "sab": ("SA", 5),
    "domingo": ("SU", 6), "dom": ("SU", 6),
}
DIAS_SEMANA_NUM = {n: num for n, (_, num) in DIAS_RRULE.items()}
MESES_NUM = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

GATILHOS_RECORRENCIA = re.compile(r"\b(toda|todas|todo|todos|semanal|semanalmente)\b", re.IGNORECASE)
GATILHOS_DIARIO      = re.compile(r"\b(todos os dias|todo dia|diariamente)\b", re.IGNORECASE)

# Palavras de data/hora que devem sair do título.
FILLER = re.compile(
    r"\b(segunda|terça|terca|quarta|quinta|sexta|s[áa]bado|domingo|feira|"
    r"hoje|amanh[ãa]|depois|manh[ãa]|tarde|noite|meio|meia|semana|vem|"
    r"pr[óo]xima|proximo|próximo|toda|todas|todo|todos|diariamente|semanalmente|"
    r"hora|horas|dia|que)\b", re.IGNORECASE)


def _detectar_recorrencia(texto):
    """Retorna (rrule, [dias_da_semana]) se a frase for recorrente; senão (None, [])."""
    t = texto.lower()
    if GATILHOS_DIARIO.search(t):
        return "RRULE:FREQ=DAILY", []
    if not GATILHOS_RECORRENCIA.search(t):
        return None, []
    codigos, dias = [], []
    for nome in sorted(DIAS_RRULE, key=len, reverse=True):
        if re.search(rf"\b{nome}\b", t):
            cod, num = DIAS_RRULE[nome]
            if cod not in codigos:
                codigos.append(cod)
                dias.append(num)
    if codigos:
        return f"RRULE:FREQ=WEEKLY;BYDAY={','.join(codigos)}", dias
    return "RRULE:FREQ=WEEKLY", []          # "toda semana" sem dia específico


def _proxima_ocorrencia(agora, dia_semana, hora, minuto):
    faltam = (dia_semana - agora.weekday()) % 7
    alvo = (agora + timedelta(days=faltam)).replace(
        hour=hora, minute=minuto, second=0, microsecond=0)
    if alvo <= agora:                       # já passou hoje -> semana que vem
        alvo += timedelta(days=7)
    return alvo


def _hora_pelo_periodo(texto):
    t = texto.lower()
    if "manhã" in t or "manha" in t:
        return 9
    if "tarde" in t:
        return 14
    if "noite" in t:
        return 19
    return 9                                # padrão quando não diz a hora


def _remover(texto, trecho):
    if not trecho:
        return texto
    return re.sub(re.escape(trecho), " ", texto, count=1, flags=re.IGNORECASE)


def extrair_data(texto, agora):
    """Acha a DATA na frase. Retorna (date, achou, trecho_encontrado)."""
    t = texto.lower()
    hoje = agora.date()

    m = re.search(r"depois de amanh[ãa]", t)
    if m:
        return hoje + timedelta(days=2), True, m.group(0)
    m = re.search(r"\bamanh[ãa]\b", t)
    if m:
        return hoje + timedelta(days=1), True, m.group(0)
    m = re.search(r"\bhoje\b", t)
    if m:
        return hoje, True, m.group(0)

    # 20/08 ou 20/08/2026
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = agora.year if not m.group(3) else int(m.group(3))
        if y < 100:
            y += 2000
        try:
            alvo = date(y, mo, d)
            if not m.group(3) and alvo < hoje:
                alvo = date(y + 1, mo, d)
            return alvo, True, m.group(0)
        except ValueError:
            pass

    # 20 de agosto
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-zç]+)", t)
    if m and m.group(2) in MESES_NUM:
        d, mo = int(m.group(1)), MESES_NUM[m.group(2)]
        try:
            alvo = date(agora.year, mo, d)
            if alvo < hoje:
                alvo = date(agora.year + 1, mo, d)
            return alvo, True, m.group(0)
        except ValueError:
            pass

    # dia 20
    m = re.search(r"\bdia\s+(\d{1,2})\b", t)
    if m:
        d = int(m.group(1))
        y, mo = hoje.year, hoje.month
        try:
            alvo = date(y, mo, d)
        except ValueError:
            alvo = None
        if alvo is None or alvo < hoje:
            mo2, y2 = (mo + 1, y) if mo < 12 else (1, y + 1)
            try:
                alvo = date(y2, mo2, d)
            except ValueError:
                return None, False, None
        return alvo, True, m.group(0)

    # semana que vem / próxima semana
    m = re.search(r"(semana que vem|pr[óo]xima semana)", t)
    if m:
        return hoje + timedelta(days=7), True, m.group(0)

    # dia da semana (segunda, terça, ...)
    for nome in sorted(DIAS_SEMANA_NUM, key=len, reverse=True):
        m = re.search(rf"\b{nome}\b", t)
        if m:
            faltam = (DIAS_SEMANA_NUM[nome] - agora.weekday()) % 7
            return hoje + timedelta(days=faltam), True, m.group(0)

    return None, False, None


def extrair_hora(texto):
    """Acha a HORA na frase. Retorna (hora, minuto, achou, trecho)."""
    t = texto.lower()

    m = re.search(r"meio[-\s]?dia", t)
    if m:
        return 12, 0, True, m.group(0)
    m = re.search(r"meia[-\s]?noite", t)
    if m:
        return 0, 0, True, m.group(0)

    # 15h30 / 15:30 / 15 horas 30
    m = re.search(r"\b(\d{1,2})\s*(?:h|:|horas?)\s*(\d{2})\b", t)
    if m:
        return int(m.group(1)) % 24, int(m.group(2)) % 60, True, m.group(0)

    # 10 da manhã / 3 da tarde / 8 da noite
    m = re.search(r"\b(\d{1,2})\s*(?:da|de|às|as|à|a)?\s*(manh[ãa]|tarde|noite)\b", t)
    if m:
        h = int(m.group(1)) % 24
        periodo = m.group(2)
        if periodo == "tarde" and h < 12:
            h += 12
        elif periodo == "noite" and h < 12:
            h += 12
        return h, 0, True, m.group(0)

    # às 15 / às 15h
    m = re.search(r"\b(?:às|as|à)\s*(\d{1,2})\s*h?\b", t)
    if m:
        return int(m.group(1)) % 24, 0, True, m.group(0)

    # 15h / 7h
    m = re.search(r"\b(\d{1,2})\s*h\b", t)
    if m:
        return int(m.group(1)) % 24, 0, True, m.group(0)

    # 10 horas
    m = re.search(r"\b(\d{1,2})\s*horas?\b", t)
    if m:
        return int(m.group(1)) % 24, 0, True, m.group(0)

    return 9, 0, False, None


def _montar_titulo(texto, trechos):
    t = texto
    for tr in trechos:
        t = _remover(t, tr)
    t = FILLER.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.-–—:")
    t = re.sub(r"^(?:de|da|do|e|à|as|às|no|na|em|a|o)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+(?:de|da|do|e|à|as|às|no|na|em|a|o)$", "", t, flags=re.IGNORECASE)
    return t.strip() or "Compromisso"


def entender(texto):
    """Transforma uma frase livre em dados do compromisso (ou None se não der)."""
    agora = datetime.now(TZ).replace(tzinfo=None, second=0, microsecond=0)
    rrule, dias = _detectar_recorrencia(texto)

    data_ev, achou_data, trecho_d = extrair_data(texto, agora)
    resto = _remover(texto, trecho_d)
    hora, minuto, achou_hora, trecho_h = extrair_hora(resto)

    if rrule and dias:                       # recorrência semanal com dias
        h, mnt = (hora, minuto) if achou_hora else (_hora_pelo_periodo(texto), 0)
        dt = _proxima_ocorrencia(agora, dias[0], h, mnt)
    elif rrule:                              # diária ou "toda semana" sem dia
        h, mnt = (hora, minuto) if achou_hora else (_hora_pelo_periodo(texto), 0)
        dt = agora.replace(hour=h, minute=mnt)
        if dt <= agora:
            dt += timedelta(days=1)
    else:
        if not achou_data and not achou_hora:
            return None
        dia = data_ev if achou_data else agora.date()
        h, mnt = (hora, minuto) if achou_hora else (_hora_pelo_periodo(texto), 0)
        dt = datetime.combine(dia, dtime(h, mnt))
        if not achou_data and dt <= agora:   # só disse a hora e já passou -> amanhã
            dt += timedelta(days=1)

    if dt < agora - timedelta(minutes=1):    # data no passado = não entendi direito
        return None

    return {
        "ok": True,
        "titulo": _montar_titulo(texto, [trecho_d, trecho_h]),
        "inicio": dt.replace(second=0, microsecond=0).isoformat(),
        "duracao_min": 60,
        "rrule": rrule,
    }


# ── Formatação bonita ────────────────────────────────────────────────────────
def formatar_quando(dt):
    hoje = datetime.now(TZ).date()
    d = dt.date()
    if d == hoje:
        dia = "hoje"
    elif d == hoje + timedelta(days=1):
        dia = "amanhã"
    else:
        dia = f"{DIAS_SEMANA[dt.weekday()]}, {dt.day} {MESES[dt.month]}"
    return f"{dia} às {dt.strftime('%H:%M')}"


def linha_evento(ev):
    ini = ev["start"].get("dateTime")
    if not ini:                          # evento de dia inteiro
        return f"• {ev.get('summary', '(sem título)')} (dia todo)"
    dt = datetime.fromisoformat(ini).astimezone(TZ)
    return f"• {formatar_quando(dt)} — {ev.get('summary', '(sem título)')}"


# ── Comandos ─────────────────────────────────────────────────────────────────
def cmd_lista(svc, dias, titulo):
    agora = datetime.now(TZ)
    evs = eventos_entre(svc, agora, agora + timedelta(days=dias))
    evs = [e for e in evs if e["start"].get("dateTime") or e["start"].get("date")]
    if not evs:
        enviar(f"📭 {titulo}: nada por aqui. Aproveita! 🌴")
        return
    linhas = "\n".join(linha_evento(e) for e in evs)
    enviar(f"🗓️ *{titulo}:*\n{linhas}")


AJUDA = (
    "👋 *Sou seu assessor de compromissos!*\n\n"
    "É só me mandar uma frase e eu marco na sua agenda. Exemplos:\n"
    "• _reunião com fornecedor amanhã 15h_\n"
    "• _dentista sexta às 10 da manhã_\n"
    "• _pagar boleto dia 20_\n"
    "• _treino toda terça e quinta 7h_\n\n"
    "Eu te lembro *1 dia antes* e *1 hora antes* de cada um. 😉\n\n"
    "*Comandos:*\n"
    "/hoje — compromissos de hoje\n"
    "/semana — próximos 7 dias\n"
    "/ajuda — esta mensagem"
)


def tratar_mensagem(svc, texto):
    baixa = texto.lower().strip()
    if baixa in ("/start", "/ajuda", "/help", "ajuda"):
        enviar(AJUDA)
    elif baixa in ("/hoje", "hoje"):
        cmd_lista(svc, 1, "Hoje")
    elif baixa in ("/semana", "semana"):
        cmd_lista(svc, 7, "Próximos 7 dias")
    else:
        dados = entender(texto)
        if not dados:
            enviar("🤔 Não consegui entender a data. Tenta assim: "
                   "_reunião amanhã às 15h_")
            return
        dt = criar_evento(svc, dados["titulo"], dados["inicio"],
                          dados.get("duracao_min", 60), dados.get("rrule"))
        repete = "\n🔁 _(compromisso que se repete)_" if dados.get("rrule") else ""
        enviar(f"✅ Anotado! *{dados['titulo']}*\n"
               f"🗓️ {formatar_quando(dt.astimezone(TZ))}\n"
               f"⏰ Te aviso 1 dia antes e 1h antes.{repete}")


# ── Resumo matinal ───────────────────────────────────────────────────────────
def resumo_matinal(svc):
    """Manda o 'bom dia' com os compromissos de hoje (roda 1x pela manhã)."""
    agora = datetime.now(TZ)
    fim_do_dia = agora.replace(hour=23, minute=59, second=59, microsecond=0)
    evs = eventos_entre(svc, agora, fim_do_dia)
    evs = [e for e in evs if e["start"].get("dateTime") or e["start"].get("date")]

    if not evs:
        enviar("☀️ *Bom dia!* Hoje sua agenda está livre. Aproveita! 🌴")
        return

    linhas = []
    for ev in evs:
        ini = ev["start"].get("dateTime")
        hora = datetime.fromisoformat(ini).astimezone(TZ).strftime("%H:%M") if ini else "dia todo"
        linhas.append(f"• {hora} — {ev.get('summary', '(sem título)')}")

    n = len(evs)
    plural = "compromisso" if n == 1 else "compromissos"
    enviar(f"☀️ *Bom dia!* Hoje você tem {n} {plural}:\n"
           + "\n".join(linhas) + "\n\nBora que o dia rende! 💪")


# ── Lembretes ────────────────────────────────────────────────────────────────
def enviar_lembretes(svc):
    agora = datetime.now(TZ)
    evs = eventos_entre(svc, agora, agora + timedelta(days=1, hours=1))
    for ev in evs:
        ini = ev["start"].get("dateTime")
        if not ini:
            continue
        inicio = datetime.fromisoformat(ini).astimezone(TZ)
        falta = inicio - agora
        if falta.total_seconds() < 0:
            continue
        for rotulo, antecedencia in LEMBRETES:
            if falta > antecedencia or ja_avisou(ev, rotulo):
                continue
            # Evita o lembrete de "1 dia" disparar junto com o de "1h"
            # para compromissos criados em cima da hora.
            if rotulo == "1d" and falta < timedelta(minutes=90):
                marcar_lembrete_enviado(svc, ev, rotulo)
                continue
            quando = "amanhã" if rotulo == "1d" else "daqui 1 hora"
            enviar(f"⏰ *Lembrete!* {ev.get('summary', '(sem título)')}\n"
                   f"É {quando} — {inicio.strftime('%H:%M')}. 💪")
            marcar_lembrete_enviado(svc, ev, rotulo)


# ── Principal ────────────────────────────────────────────────────────────────
def main():
    print("🤖 Assessor rodando...", datetime.now(TZ).strftime("%d/%m %H:%M"))
    checar_credenciais()
    svc = calendario()

    # Modo "resumo matinal": só manda o bom dia e sai.
    if "--resumo" in sys.argv:
        print("   ☀️ enviando resumo matinal")
        resumo_matinal(svc)
        print("   ✅ resumo enviado")
        return

    # Modo "só lembretes": não lê mensagens (usado quando o webhook está ativo).
    if "--lembretes" in sys.argv:
        print("   ⏰ enviando lembretes")
        enviar_lembretes(svc)
        print("   ✅ lembretes enviados")
        return

    mensagens = ler_mensagens()
    print(f"   {len(mensagens)} mensagem(ns) nova(s)")
    for texto in mensagens:
        try:
            tratar_mensagem(svc, texto)
        except Exception as e:
            print("   ⚠️ erro tratando mensagem:", e)
            enviar("😵 Deu um erro aqui ao processar. Tenta de novo?")

    enviar_lembretes(svc)
    print("   ✅ rodada concluída")


if __name__ == "__main__":
    main()
