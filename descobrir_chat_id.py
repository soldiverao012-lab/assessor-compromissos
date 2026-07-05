"""
descobrir_chat_id.py
Descobre o seu TELEGRAM_CHAT_ID a partir das mensagens que você já mandou pro bot.

Como usar:
  1. No Telegram, mande QUALQUER mensagem pro seu bot (ex: "Oi").
  2. Rode:
       python descobrir_chat_id.py SEU_TOKEN_AQUI
     (ou coloque TELEGRAM_BOT_TOKEN no .env e rode sem argumento)

Ele mostra o número do Chat ID pra você copiar.
"""

import os
import sys
import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

token = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TELEGRAM_BOT_TOKEN")
if not token:
    raise SystemExit("❌ Passe o token: python descobrir_chat_id.py SEU_TOKEN")

r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
j = r.json()

if not j.get("ok"):
    raise SystemExit(f"❌ O token não funcionou. Resposta do Telegram: {j.get('description')}")

updates = j.get("result", [])
if not updates:
    raise SystemExit(
        "⚠️ Nenhuma mensagem encontrada.\n"
        "   → Abra seu bot no Telegram, mande um 'Oi' e rode este script de novo.\n"
        "   (Se você já rodou o assessor.py antes, as mensagens antigas já foram lidas —\n"
        "    é só mandar um 'Oi' novo.)"
    )

print("✅ Token funcionando! Mensagens encontradas:\n")
vistos = set()
for u in updates:
    msg = u.get("message") or u.get("edited_message")
    if not msg:
        continue
    chat = msg["chat"]
    cid = chat["id"]
    if cid in vistos:
        continue
    vistos.add(cid)
    nome = chat.get("first_name", "") or chat.get("title", "")
    print(f"   👤 {nome}")
    print(f"   🆔 SEU CHAT ID  =  {cid}")
    print(f"   💬 mensagem: {msg.get('text', '(sem texto)')}\n")

print("👉 Copie o número do CHAT ID acima e cole no .env em TELEGRAM_CHAT_ID.")
