# -*- coding: utf-8 -*-
"""
Confere o desvio entre PERGUNTA e COMPROMISSO.

O risco de somar perguntas ao bot é sequestrar frases que sempre funcionaram:
se "reunião sobre contas atrasadas amanhã 10h" virar consulta, você perde um
compromisso sem perceber. Este teste fixa esse limite.

Não envia nada no Telegram e não cria evento: só decide o rumo de cada frase.

Uso:  .venv\\Scripts\\python testar_roteamento.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

import assessor as app

# (frase, rumo esperado)  —  "pergunta" ou "compromisso"
CASOS = [
    # --- devem virar PERGUNTA ---
    ("quais contas estao atrasadas?",        "pergunta"),
    ("quais estão atrasadas",                "pergunta"),
    ("me lista as despesas atrasadas",       "pergunta"),
    ("quanto devo",                          "pergunta"),
    ("quanto eu devo?",                      "pergunta"),
    ("o que vence hoje",                     "pergunta"),
    ("contas de hoje",                       "pergunta"),
    ("/atrasados",                           "pergunta"),
    ("/financeiro",                          "pergunta"),
    ("maiores contas",                       "pergunta"),
    ("estou devendo alguma coisa?",          "pergunta"),
    ("tem conta vencida?",                   "pergunta"),

    # --- vindas do caderninho real (/naoentendi) ---
    ("Quais despesas vao vencer essa semana?", "pergunta"),
    ("o que vence essa semana",                "pergunta"),
    ("contas a vencer",                        "pergunta"),
    ("o que vou pagar esse mes",               "pergunta"),
    ("quanto sobrou de lucro no trimestre?",   "pergunta"),
    ("quanto sobrou esse mes",                 "pergunta"),
    ("qual o resultado do trimestre",          "pergunta"),
    ("compromissos do dia",                    "pergunta"),
    ("agenda do dia",                          "pergunta"),
    ("saldo contas",                           "pergunta"),
    ("saldo das contas",                       "pergunta"),
    ("contas a pagar",                         "pergunta"),
    ("contas para pagar",                      "pergunta"),
    # ...mas com periodo, o especifico tem que ganhar do guarda-chuva:
    ("contas a pagar essa semana",             "pergunta"),
    ("/nao entendi",                           "comando"),
    ("/naoentendi",                            "comando"),
    ("/não entendi",                           "comando"),

    # --- vendas (devem virar PERGUNTA) ---
    ("quanto vendeu hoje?",                  "pergunta"),
    ("quanto vendi hoje",                    "pergunta"),
    ("vendas de hoje",                       "pergunta"),
    ("quanto vendeu ontem",                  "pergunta"),
    ("vendas de ontem",                      "pergunta"),
    ("vendas da semana",                     "pergunta"),
    ("faturamento do mes",                   "pergunta"),
    ("quantos pedidos",                      "pergunta"),
    ("/vendas",                              "pergunta"),

    # --- agenda (devem virar PERGUNTA) ---
    ("o que eu tenho hoje",                  "pergunta"),
    ("o que tenho amanha",                   "pergunta"),
    ("agenda de amanha",                     "pergunta"),
    ("compromissos da semana",               "pergunta"),
    ("tenho algo marcado amanha",            "pergunta"),

    # --- devem continuar virando COMPROMISSO ---
    ("dentista amanha as 10h",                          "compromisso"),
    ("reuniao com fornecedor amanha 15h",               "compromisso"),
    ("pagar aluguel sexta 9h",                          "compromisso"),
    ("reuniao sobre contas atrasadas amanha 10h",       "compromisso"),
    ("ligar pro contador sobre o atrasado terca 14h",   "compromisso"),
    ("toda terca academia 7h",                          "compromisso"),
    ("fotos do maio de laco quinta 8h",                 "compromisso"),
    # Armadilhas: contem palavra de pergunta, mas sao compromisso.
    ("reuniao de vendas amanha",                        "compromisso"),
    ("tenho dentista amanha",                           "compromisso"),
    ("treinamento de vendas na sexta",                  "compromisso"),
    ("fechar o faturamento com a contadora quarta",     "compromisso"),
    ("conferir as vendas do mes com o joao sexta 16h",  "compromisso"),
]


def rumo(frase):
    """Repete a decisão que o bot toma, sem executar nada."""
    import re
    baixa = frase.lower().strip()
    if baixa in ("/start", "/ajuda", "/help", "ajuda", "/hoje", "hoje",
                 "/semana", "semana"):
        return "comando"
    if re.match(r"^/n[aã]o\s?entendi\b", app._sem_acento_simples(baixa)):
        return "comando"
    try:
        import consultas
        if consultas.identificar(frase):
            _, _, achou_hora, _ = app.extrair_hora(frase)
            if not achou_hora:
                return "pergunta"
    except ImportError:
        pass
    return "compromisso"


# Casos em que nao basta "e pergunta": tem que cair na intencao CERTA.
# Sem isto, uma frase especifica caindo no guarda-chuva passaria batido —
# "contas a pagar essa semana" viraria o resumo geral e ninguem notaria.
INTENCOES = [
    ("contas a pagar",             "resumo"),
    ("contas a pagar essa semana", "a_vencer_semana"),
    ("saldo contas",               "resumo"),
    ("compromissos do dia",        "agenda_hoje"),
    ("compromissos da semana",     "agenda_semana"),
    ("o que vence hoje",           "vence_hoje"),
    ("o que vence essa semana",    "a_vencer_semana"),
    ("quais estao atrasadas",      "atrasados"),
    ("quanto sobrou esse mes",     "caixa_mes"),
    ("quanto sobrou no trimestre", "caixa_trimestre"),
    ("quanto vendeu ontem",        "vendas_ontem"),
    ("vendas da semana",           "vendas_semana"),
    ("saldo conta sol di verao",   "resumo"),
]

# Frases que citam uma CONTA: a resposta tem que valer so pra ela.
# Sem isto, o bot devolvia o consolidado ignorando o nome — pior que nao
# entender, porque parece que respondeu certo.
CONTAS = [
    ("saldo conta sol di verao",              "SOL DI VERAO"),
    ("saldo da sol di verao",                 "SOL DI VERAO"),
    ("atrasados da sol di verao",             "SOL DI VERAO"),
    ("saldo m.o francisco",                   "M.O FRANCISCO"),
    ("quanto devo na conta do francisco",     "M.O FRANCISCO"),
    ("saldo do cartao",                       "Cartão Empresarial"),
    ("saldo cartao empresarial",              "Cartão Empresarial"),
    ("saldo cap fel",                         "CAIXA CAP FEL"),
    # Sem conta citada: tem que valer pra TODAS (None).
    ("saldo contas",                          None),
    ("quais contas estao atrasadas",          None),
    ("o que vence hoje",                      None),
]


def main():
    import consultas

    largura = max(len(f) for f, _ in CASOS) + 2
    erros = 0

    print("== Rumo: pergunta, compromisso ou comando ==")
    for frase, esperado in CASOS:
        obtido = rumo(frase)
        ok = obtido == esperado
        if not ok:
            erros += 1
        print(f"  {'[ OK ]' if ok else '[FALHA]'} {frase:<{largura}} "
              f"-> {obtido}" + ("" if ok else f"   (esperava {esperado})"))

    print("\n== Intencao exata (o especifico tem que ganhar do generico) ==")
    larg2 = max(len(f) for f, _ in INTENCOES) + 2
    for frase, esperada in INTENCOES:
        obtida = consultas.identificar(frase)
        ok = obtida == esperada
        if not ok:
            erros += 1
        print(f"  {'[ OK ]' if ok else '[FALHA]'} {frase:<{larg2}} "
              f"-> {obtida}" + ("" if ok else f"   (esperava {esperada})"))

    print("\n== Conta citada na frase ==")
    import snapshot
    dados = snapshot.carregar()
    if not dados or not dados.get("contas"):
        print("  (sem fotografia com contas — rode snapshot.py antes)")
        contas_testadas = 0
    else:
        contas_testadas = len(CONTAS)
        larg3 = max(len(f) for f, _ in CONTAS) + 2
        for frase, esperada in CONTAS:
            achada = consultas.identificar_conta(frase, dados)
            nome = achada["nome"] if achada else None
            ok = nome == esperada
            if not ok:
                erros += 1
            print(f"  {'[ OK ]' if ok else '[FALHA]'} {frase:<{larg3}} "
                  f"-> {nome}" + ("" if ok else f"   (esperava {esperada})"))

    total = len(CASOS) + len(INTENCOES) + contas_testadas
    print()
    if erros:
        print(f"=> {erros} caso(s) errado(s) de {total}.")
        sys.exit(1)
    print(f"=> Os {total} casos passaram.")


if __name__ == "__main__":
    main()
