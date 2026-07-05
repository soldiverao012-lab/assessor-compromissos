"""
api/webhook.py
Webhook do Telegram rodando no Vercel (servidor 24/7, resposta instantânea).

O Telegram faz um POST aqui toda vez que você manda uma mensagem pro bot.
A gente entende a frase e cria o evento na hora, reaproveitando toda a lógica
que já está em assessor.py.

Configurar o webhook (uma vez):
  https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<projeto>.vercel.app/api/webhook
"""

import os
import sys
import json
from http.server import BaseHTTPRequestHandler

# Permite importar o assessor.py que está na pasta acima.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import assessor


def _processar(update):
    msg = update.get("message") or update.get("edited_message")
    if not msg or "text" not in msg:
        return
    # Só respondemos VOCÊ.
    if str(msg["chat"]["id"]) != str(assessor.TG_CHAT):
        return
    svc = assessor.calendario()
    assessor.tratar_mensagem(svc, msg["text"].strip())


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Checagem de segurança opcional (se WEBHOOK_SECRET estiver definido).
        segredo = os.getenv("WEBHOOK_SECRET")
        if segredo and self.headers.get("X-Telegram-Bot-Api-Secret-Token") != segredo:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return
        try:
            tam = int(self.headers.get("content-length", 0))
            corpo = self.rfile.read(tam) if tam else b"{}"
            _processar(json.loads(corpo))
        except Exception as e:
            print("erro no webhook:", e)
        # Responde 200 sempre, pra o Telegram não ficar reenviando.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write("Assessor online 🤖".encode("utf-8"))
