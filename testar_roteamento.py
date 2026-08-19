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

    # --- devem continuar virando COMPROMISSO ---
    ("dentista amanha as 10h",                          "compromisso"),
    ("reuniao com fornecedor amanha 15h",               "compromisso"),
    ("pagar aluguel sexta 9h",                          "compromisso"),
    ("reuniao sobre contas atrasadas amanha 10h",       "compromisso"),
    ("ligar pro contador sobre o atrasado terca 14h",   "compromisso"),
    ("toda terca academia 7h",                          "compromisso"),
    ("fotos do maio de laco quinta 8h",                 "compromisso"),
]


def rumo(frase):
    """Repete a decisão que o bot toma, sem executar nada."""
    baixa = frase.lower().strip()
    if baixa in ("/start", "/ajuda", "/help", "ajuda", "/hoje", "hoje",
                 "/semana", "semana"):
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


def main():
    largura = max(len(f) for f, _ in CASOS) + 2
    erros = 0
    for frase, esperado in CASOS:
        obtido = rumo(frase)
        ok = obtido == esperado
        if not ok:
            erros += 1
        print(f"  {'[ OK ]' if ok else '[FALHA]'} {frase:<{largura}} "
              f"-> {obtido}" + ("" if ok else f"   (esperava {esperado})"))

    print()
    if erros:
        print(f"=> {erros} caso(s) errado(s) de {len(CASOS)}.")
        sys.exit(1)
    print(f"=> Os {len(CASOS)} casos passaram.")


if __name__ == "__main__":
    main()
