# 🤖 Assessor de Compromissos (Telegram + Google Calendar)

Seu assistente pessoal que:

1. **Anota** — você manda uma frase no Telegram (_"reunião com fornecedor amanhã 15h"_) e ele cria o evento no seu Google Calendar.
2. **Lembra** — a cada 5 min ele confere a agenda e te avisa **1 dia antes** e **1 hora antes** de cada compromisso.
3. **Bom dia** — toda manhã às **7h** ele te manda um resumo dos compromissos do dia. ☀️
4. **Roda sozinho na nuvem** (GitHub Actions), de graça, mesmo com o PC desligado — igualzinho ao seu `publicador/`.

**Comandos no Telegram:** `/hoje` • `/semana` • `/ajuda`

> 💚 **100% gratuito.** O assessor entende as datas em português por conta própria (offline), sem nenhuma API paga.

---

## 🧩 O que você vai precisar (4 chaves — todas grátis)

| # | Chave | Onde consegue |
|---|-------|---------------|
| 1 | `TELEGRAM_BOT_TOKEN` | @BotFather no Telegram |
| 2 | `TELEGRAM_CHAT_ID` | comando/script (passo 2) |
| 3 | `GOOGLE_CREDENTIALS` | Google Cloud (conta de serviço) |
| 4 | `GOOGLE_CALENDAR_ID` | seu e-mail do Google |

Vá seguindo os passos — cada chave é rápida.

---

## 1️⃣ Criar o bot no Telegram

1. No Telegram, abra conversa com **@BotFather**.
2. Mande `/newbot`, dê um nome (ex: `Meu Assessor`) e um usuário terminando em `bot` (ex: `meu_assessor_bot`).
3. Ele te devolve um **token** tipo `123456:ABC-xyz...` → esse é o **`TELEGRAM_BOT_TOKEN`**.
4. **Abra seu bot e mande um "oi"** (qualquer mensagem). Isso é obrigatório pro próximo passo.

## 2️⃣ Descobrir seu Chat ID

1. No Telegram, mande qualquer mensagem pro seu bot (ex: "oi").
2. Rode: `python descobrir_chat_id.py SEU_TOKEN` — ele mostra o número.
   - Esse número é o **`TELEGRAM_CHAT_ID`**. Serve de segurança: o assessor só obedece **você**.
   - (Alternativa: falar com **@userinfobot** no Telegram.)

## 3️⃣ Deixar o assessor mexer na sua Agenda (Google)

Isso parece o mais chato, mas são 6 cliques:

1. Entre em **console.cloud.google.com** e crie um projeto (ou use um existente).
2. Menu **APIs e serviços → Biblioteca** → procure **Google Calendar API** → **Ativar**.
3. Menu **APIs e serviços → Credenciais → Criar credenciais → Conta de serviço**.
   - Dê um nome (ex: `assessor`) → **Concluir**.
4. Clique na conta de serviço criada → aba **Chaves → Adicionar chave → Criar nova chave → JSON**.
   - Baixa um arquivo `.json`. **Guarde bem** — é a **`GOOGLE_CREDENTIALS`**.
   - Anote o **e-mail da conta de serviço** (algo tipo `assessor@projeto.iam.gserviceaccount.com`).
5. **Compartilhe sua agenda com esse e-mail:**
   - Abra o **Google Calendar** (agenda.google.com) no navegador.
   - Passe o mouse na sua agenda (menu esquerdo) → **⋮ → Configurações e compartilhamento**.
   - Em **Compartilhar com pessoas específicas** → **Adicionar pessoas** → cole o e-mail da conta de serviço.
   - Permissão: **"Fazer alterações nos eventos"** → **Enviar**.
6. Seu **`GOOGLE_CALENDAR_ID`** é o **seu próprio e-mail do Google** (ex: `matheusoliveira.ofs@gmail.com`).
   > ⚠️ Importante: **não** deixe `primary` aqui, senão os eventos vão pra agenda vazia da conta de serviço e você não vê nada. Use seu e-mail.

---

## 🧪 Testar no seu PC primeiro (recomendado)

```powershell
cd "assessor"
pip install -r requirements.txt

# copie o arquivo de exemplo e preencha
copy .env.exemplo .env
# abra o .env e cole as 5 chaves (o JSON do Google salve como google_credentials.json nesta pasta)

python assessor.py
```

Agora mande no Telegram: _"dentista amanhã às 10h"_ e rode `python assessor.py` de novo.
Ele deve responder **✅ Anotado!** e o evento aparece na sua Google Agenda. 🎉

---

## ☁️ Colocar pra rodar sozinho (GitHub Actions)

Mesmo esquema do `publicador/`: **esta pasta vira um repositório Git próprio**.

1. Crie um repositório **privado** no GitHub e suba **só o conteúdo desta pasta** (`assessor/`).
   - O `.gitignore` já protege o `.env` e o `google_credentials.json` — eles **nunca** sobem.
2. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Crie os 4:

   | Nome do Secret | Valor |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | o token do passo 1 |
   | `TELEGRAM_CHAT_ID` | o número do passo 2 |
   | `GOOGLE_CREDENTIALS` | **cole todo o conteúdo** do arquivo `.json` do Google |
   | `GOOGLE_CALENDAR_ID` | seu e-mail do Google (passo 3) |

3. Vá na aba **Actions**, habilite os workflows, abra **"Assessor de Compromissos"** → **Run workflow** pra testar na hora.
4. Pronto! A partir daí ele roda **a cada 5 minutos** (anotar + lembretes) e manda o **resumo às 7h** (workflow "Resumo Matinal"), tudo sozinho.

> 🕖 Os dois despertadores usam **os mesmos 4 secrets** — não precisa criar nada a mais. Pra testar o resumo na hora: aba **Actions → Resumo Matinal → Run workflow**. Localmente: `python assessor.py --resumo`.

---

## ❓ Perguntas rápidas

**Demora pra responder?** Na nuvem ele confere a cada ~5 min, então uma anotação pode levar até uns 5 min pra ser confirmada. Lembretes de "1 hora antes" caem com essa mesma folga (ok na prática).

> ⚠️ Rodar a cada 5 min só cabe no plano grátis se o repositório for **público** (repositório privado tem limite de ~2000 min/mês de Actions; público é ilimitado). Como os segredos ficam nos *Secrets* e não no código, deixar público é seguro.

**Posso mudar os horários dos lembretes?** Sim — edite a lista `LEMBRETES` no `assessor.py` (ex: adicionar 30 min antes).

**Ele lê meus outros e-mails/agenda?** Não. A conta de serviço só enxerga a agenda que **você** compartilhou com ela.

**Como funciona sem "banco de dados"?** O Telegram guarda o "já li essa mensagem" e cada evento guarda o "já avisei" dentro dele mesmo. Zero estado no repositório.

**Que frases ele entende?** Ele lê datas e horas em português, offline. Funciona bem com:

- _hoje / amanhã / depois de amanhã_ • _segunda, terça... / sexta que vem_ • _semana que vem_
- _dia 20_ • _20/08_ • _20 de agosto_
- _15h / 15:30 / às 10 / 10 da manhã / 3 da tarde / 8 da noite / meio-dia_
- Repetição: _toda terça_ • _toda terça e quinta_ • _todos os dias_

Se ele não achar a data, responde pedindo pra reescrever. Não precisa acertar a "forma certa" — é só escrever naturalmente.
