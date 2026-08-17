# -*- coding: utf-8 -*-
r"""
Diagnóstico do assessor — confere, uma por uma, se as peças estão de pé.

Rode quando algo parecer parado:  .venv\Scripts\python diagnostico.py
Não manda mensagem nenhuma no Telegram, não cria evento: é só leitura.
"""
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

OK, FALHA, AVISO = "  [ OK ]", "  [FALHA]", "  [AVISO]"


def bloco(titulo):
    print(f"\n{titulo}")


def main():
    from dotenv import load_dotenv
    load_dotenv()

    problemas = 0

    # ── 1. Chaves ────────────────────────────────────────────────────────────
    bloco("1) Chaves no .env")
    for chave in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GOOGLE_CALENDAR_ID"):
        if os.getenv(chave):
            print(f"{OK} {chave}")
        else:
            print(f"{FALHA} {chave} não está preenchida")
            problemas += 1

    # ── 2. Telegram ──────────────────────────────────────────────────────────
    bloco("2) Telegram")
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
        if me.get("ok"):
            print(f"{OK} bot @{me['result']['username']} responde")
        else:
            print(f"{FALHA} token recusado pelo Telegram")
            problemas += 1

        wh = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=20).json()
        info = wh.get("result", {})
        url = info.get("url") or "(nenhum)"
        print(f"{OK} webhook: {url}")
        pendentes = info.get("pending_update_count", 0)
        if pendentes:
            print(f"{AVISO} {pendentes} mensagem(ns) na fila — o webhook pode estar caindo")
        if info.get("last_error_message"):
            print(f"{AVISO} último erro do webhook: {info['last_error_message']}")
    except Exception as e:
        print(f"{FALHA} não consegui falar com o Telegram: {e}")
        problemas += 1

    # ── 3. Google Calendar ───────────────────────────────────────────────────
    bloco("3) Google Calendar")
    try:
        import assessor as app
        svc = app.calendario()
        agora = datetime.now(app.TZ)
        evs = app.eventos_entre(svc, agora, agora + timedelta(days=14))
        print(f"{OK} agenda acessível — {len(evs)} compromisso(s) nos próximos 14 dias")
        for ev in evs[:5]:
            ini = ev["start"].get("dateTime") or ev["start"].get("date")
            print(f"         · {ini}  {ev.get('summary', '(sem título)')}")
    except Exception as e:
        print(f"{FALHA} agenda inacessível: {e}")
        problemas += 1

    # ── 4. Parser de datas ───────────────────────────────────────────────────
    bloco("4) Entendimento de datas (offline)")
    try:
        import assessor as app
        for frase in ("dentista amanhã às 10h", "reunião sexta que vem 15:30", "toda terça academia 7h"):
            d = app.entender(frase)
            if d:
                print(f"{OK} \"{frase}\" -> {d['titulo']} @ {d['inicio']}")
            else:
                print(f"{FALHA} não entendeu: \"{frase}\"")
                problemas += 1
    except Exception as e:
        print(f"{FALHA} parser quebrou: {e}")
        problemas += 1

    # ── Veredito ─────────────────────────────────────────────────────────────
    print()
    if problemas:
        print(f"=> {problemas} problema(s). Veja as linhas [FALHA] acima.")
        sys.exit(1)
    print("=> Tudo certo. O assessor está saudável.")


if __name__ == "__main__":
    main()
