# -*- coding: utf-8 -*-
"""
Regras da cobrança de tarefas — testadas offline, sem tocar no Telegram nem
no Google Calendar.

O que este teste protege, e por quê:

  • O caderninho do /naoentendi guarda frases como eventos de DIA INTEIRO em
    01/01/2000. Se a cobrança pegasse dia inteiro, o bot perguntaria ao dono se
    ele "fez" uma anotação interna do próprio bot. Isso não pode acontecer.
  • Cobrar de madrugada faz a pessoa silenciar o bot inteiro — e aí ela perde
    também os lembretes, que são a função principal.
  • Quem responde "⏳ ainda não" tem que continuar vendo a tarefa. Se ela sumir,
    a cobrança vira um botão de esconder problema.
  • Quem responde "✅ fiz" tem que ver a tarefa desaparecer da agenda.

Uso:  .venv\\Scripts\\python testar_cobranca.py
"""
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

import assessor as app
import pendencias


# ── Google Calendar de mentira ───────────────────────────────────────────────
class _Chamada:
    def __init__(self, valor=None):
        self.valor = valor

    def execute(self):
        return self.valor


class _Eventos:
    def __init__(self, banco):
        self.banco = banco

    def get(self, calendarId=None, eventId=None):
        return _Chamada(self.banco[eventId])

    def patch(self, calendarId=None, eventId=None, body=None):
        ev = self.banco[eventId]
        for chave, valor in (body or {}).items():
            if chave == "extendedProperties":
                ev.setdefault("extendedProperties", {}).setdefault("private", {}) \
                  .update(valor.get("private", {}))
            else:
                ev[chave] = valor
        return _Chamada(ev)

    def delete(self, calendarId=None, eventId=None):
        self.banco.pop(eventId, None)
        return _Chamada()


class Agenda:
    def __init__(self, eventos):
        self.banco = {e["id"]: e for e in eventos}

    def events(self):
        return _Eventos(self.banco)


def _instalar(agenda):
    """Troca as portas de saída por versões que só anotam. Devolve a caixa de saída."""
    enviados = []
    app.enviar = lambda texto, botoes=None: enviados.append((texto, botoes))

    def eventos_falsos(svc, inicio, fim):
        saida = []
        for ev in agenda.banco.values():
            ini = (ev.get("start") or {}).get("dateTime")
            termina = (ev.get("end") or {}).get("dateTime")
            if not ini:                       # dia inteiro: a API devolve mesmo assim
                saida.append(ev)
                continue
            ini = datetime.fromisoformat(ini)
            termina = datetime.fromisoformat(termina)
            if ini < fim and termina > inicio:
                saida.append(ev)
        return sorted(saida, key=lambda e: (e.get("start") or {}).get("dateTime") or "")

    app.eventos_entre = eventos_falsos
    return enviados


# ── Fábrica de eventos ───────────────────────────────────────────────────────
def evento(ident, titulo, terminou_ha_horas, agora, priv=None, dia_inteiro=False):
    fim = agora - timedelta(hours=terminou_ha_horas)
    inicio = fim - timedelta(hours=1)
    if dia_inteiro:
        corpo = {"id": ident, "summary": titulo,
                 "start": {"date": inicio.date().isoformat()},
                 "end":   {"date": inicio.date().isoformat()}}
    else:
        corpo = {"id": ident, "summary": titulo,
                 "start": {"dateTime": inicio.isoformat()},
                 "end":   {"dateTime": fim.isoformat()}}
    if priv:
        corpo["extendedProperties"] = {"private": priv}
    return corpo


def _hoje_as(hora):
    return datetime.now(app.TZ).replace(hour=hora, minute=0, second=0, microsecond=0)


# ── Casos ────────────────────────────────────────────────────────────────────
def caso_cobra_o_que_passou():
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "pagar boleto", 1, agora)])
    enviados = _instalar(agenda)
    n = pendencias.cobrar(agenda, agora)
    return n == 1 and len(enviados) == 1 and "Você fez isso?" in enviados[0][0]


def caso_respeita_a_folga():
    """Terminou agora mesmo: ainda pode estar no meio das coisas."""
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "reunião", 0.05, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    return not enviados and not pendencias.listar(agenda, agora)


def caso_nao_acorda_ninguem():
    agora = _hoje_as(3)
    agenda = Agenda([evento("a1", "coisa da madrugada", 1, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    # Não cobra agora, mas continua pendente pra cobrar de manhã.
    return not enviados and len(pendencias.listar(agenda, agora)) == 1


def caso_ignora_dia_inteiro():
    """O caderninho do /naoentendi mora em eventos de dia inteiro."""
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "naoentendi: quanto rendeu?", 5, agora, dia_inteiro=True)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    return not enviados and not pendencias.listar(agenda, agora)


def caso_ignora_concluido():
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "✅ dentista", 2, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    return not enviados and not pendencias.listar(agenda, agora)


def caso_ignora_silenciado():
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "academia", 2, agora, priv={"nao_cobrar": "1"})])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    return not enviados and not pendencias.listar(agenda, agora)


def caso_nao_repete_na_mesma_hora():
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "pagar boleto", 2, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)                 # 1ª cobrança
    pendencias.cobrar(agenda, agora + timedelta(minutes=30))
    pendencias.cobrar(agenda, agora + timedelta(hours=1))
    return len(enviados) == 1


def caso_volta_a_cobrar_depois():
    agora = _hoje_as(9)
    agenda = Agenda([evento("a1", "pagar boleto", 1, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    pendencias.cobrar(agenda, agora + timedelta(hours=pendencias.HORAS_ENTRE_COBRANCAS))
    return len(enviados) == 2


def caso_nao_desenterra_historico():
    """Tarefa de dias atrás que nunca foi cobrada é histórico, não pendência nova."""
    agora = _hoje_as(15)
    velha = pendencias.HORAS_PRIMEIRA_COBRANCA + 5
    agenda = Agenda([evento("a1", "coisa antiga", velha, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    return not enviados


def caso_fiz_apaga():
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "pagar boleto", 2, agora)])
    _instalar(agenda)
    aviso, texto = pendencias.resolver(agenda, "fiz", "a1")
    return "a1" not in agenda.banco and "Feito" in texto


def caso_ainda_nao_continua_aparecendo():
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "pagar boleto", 2, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    pendencias.resolver(agenda, "ain", "a1", agora)
    ainda_la = len(pendencias.listar(agenda, agora)) == 1
    linhas = pendencias.linhas(agenda, agora)
    # E volta a ser cobrada depois — dizer "ainda não" não é fugir dela.
    pendencias.cobrar(agenda, agora + timedelta(hours=pendencias.HORAS_ENTRE_COBRANCAS + 1))
    return ainda_la and any("Pendentes" in l for l in linhas) and len(enviados) == 2


def caso_parar_de_cobrar():
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "academia", 2, agora)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    pendencias.resolver(agenda, "mut", "a1")
    pendencias.cobrar(agenda, agora + timedelta(hours=48))
    # Continua na agenda (não foi apagada), mas some da cobrança.
    return "a1" in agenda.banco and len(enviados) == 1 and not pendencias.listar(agenda, agora)


def caso_teto_por_rodada():
    agora = _hoje_as(15)
    agenda = Agenda([evento(f"a{i}", f"tarefa {i}", 2, agora)
                     for i in range(pendencias.MAX_POR_RODADA + 3)])
    enviados = _instalar(agenda)
    pendencias.cobrar(agenda, agora)
    return len(enviados) == pendencias.MAX_POR_RODADA


def caso_caminho_do_webhook():
    """
    O toque no botão chega pelo webhook (Vercel) -> app.tratar_callback.

    Este é o caminho de verdade, e é onde um engano quebraria calado: os botões
    antigos (✅ Concluir / 🗑️ Apagar) passam pelo MESMO lugar e não podem ter
    sido atropelados pelos novos.
    """
    agora = _hoje_as(15)
    agenda = Agenda([evento("a1", "pagar boleto", 2, agora),
                     evento("a2", "outra coisa", 2, agora)])
    _instalar(agenda)
    avisos, edicoes = [], []
    app.responder_callback = lambda cb_id, texto="": avisos.append(texto)
    app.editar_mensagem = lambda chat, msg, texto: edicoes.append(texto)

    def tocar(dados, ident):
        app.tratar_callback(agenda, {
            "id": "cb1", "from": {"id": app.TG_CHAT},
            "message": {"chat": {"id": app.TG_CHAT}, "message_id": 1},
            "data": f"{dados}:{ident}",
        })

    tocar("fiz", "a1")                       # cobrança: apaga
    apagou = "a1" not in agenda.banco
    tocar("done", "a2")                      # botão antigo: marca ✅, NÃO apaga
    concluiu = ("a2" in agenda.banco
                and agenda.banco["a2"]["summary"].startswith("✅"))
    return apagou and concluiu and len(avisos) == 2 and len(edicoes) == 2


def caso_botoes_cabem_no_telegram():
    agora = _hoje_as(15)
    ev = evento("a" * 40, "tarefa", 2, agora)          # id longo, como recorrência
    for linha in pendencias.botoes(ev):
        for botao in linha:
            if len(botao["callback_data"].encode("utf-8")) > 64:
                return False
    return pendencias.botoes(evento("x" * 60, "t", 2, agora)) is None


CASOS = [
    ("cobra o que passou",            caso_cobra_o_que_passou),
    ("espera a folga do fim",         caso_respeita_a_folga),
    ("não cobra de madrugada",        caso_nao_acorda_ninguem),
    ("ignora evento de dia inteiro",  caso_ignora_dia_inteiro),
    ("ignora já concluído",           caso_ignora_concluido),
    ("ignora silenciado",             caso_ignora_silenciado),
    ("não repete na mesma hora",      caso_nao_repete_na_mesma_hora),
    ("volta a cobrar depois",         caso_volta_a_cobrar_depois),
    ("não desenterra histórico",      caso_nao_desenterra_historico),
    ("✅ Fiz apaga da agenda",        caso_fiz_apaga),
    ("⏳ Ainda não continua na lista", caso_ainda_nao_continua_aparecendo),
    ("🔕 para de cobrar, sem apagar", caso_parar_de_cobrar),
    ("teto de mensagens por rodada",  caso_teto_por_rodada),
    ("caminho do webhook (botões)",   caso_caminho_do_webhook),
    ("botões cabem no callback_data", caso_botoes_cabem_no_telegram),
]


def main():
    print("Cobrança de tarefas\n")
    erros = 0
    for nome, funcao in CASOS:
        try:
            ok = funcao()
        except Exception as e:
            ok, nome = False, f"{nome}  ({type(e).__name__}: {e})"
        if not ok:
            erros += 1
        print(f"  {'[ OK ]' if ok else '[FALHA]'} {nome}")

    print()
    if erros:
        print(f"=> {erros} caso(s) errado(s) de {len(CASOS)}.")
        sys.exit(1)
    print(f"=> Os {len(CASOS)} casos passaram.")


if __name__ == "__main__":
    main()
