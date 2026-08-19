# -*- coding: utf-8 -*-
"""
Testa o caderninho — e, principalmente, se ele CONTAMINA o resto.

O risco de guardar registros dentro da agenda é vazar: um deles aparecer no
/hoje, no briefing, no radar, ou pior, disparar um lembrete no seu Telegram.
Este teste cria um registro de verdade, confere que nenhuma dessas janelas o
enxerga, e apaga no fim.

Uso:  .venv\\Scripts\\python testar_naoentendi.py
"""
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

import assessor as app
import naoentendi

FRASE = "ZZTESTE quanto sobrou de lucro liquido no trimestre"


def main():
    svc = app.calendario()
    agora = datetime.now(app.TZ)
    erros = 0

    print("1) Registrando uma frase de teste...")
    naoentendi.registrar(svc, FRASE)
    itens = naoentendi.listar(svc)
    achou = [i for i in itens if i[1] == FRASE]
    if achou:
        print(f"  [ OK ] anotada (vezes={achou[0][0]})")
    else:
        print("  [FALHA] nao apareceu na listagem")
        erros += 1

    print("\n2) Repetindo a MESMA frase (deve so contar, nao duplicar)...")
    naoentendi.registrar(svc, FRASE)
    itens = naoentendi.listar(svc)
    iguais = [i for i in itens if i[1] == FRASE]
    if len(iguais) == 1 and iguais[0][0] == 2:
        print("  [ OK ] 1 registro, contador em 2")
    else:
        print(f"  [FALHA] {len(iguais)} registro(s), contador "
              f"{iguais[0][0] if iguais else '-'}")
        erros += 1

    print("\n3) O registro VAZA pra alguma janela do sistema?")

    def confere(rotulo, eventos):
        vazou = [e for e in eventos if (e.get("summary") or "") == FRASE]
        if vazou:
            print(f"  [FALHA] VAZOU em {rotulo}")
            return 1
        print(f"  [ OK ] invisivel em {rotulo}")
        return 0

    erros += confere("hoje (/hoje)",
                     app.eventos_entre(svc, agora, agora + timedelta(days=1)))
    erros += confere("semana (/semana)",
                     app.eventos_entre(svc, agora, agora + timedelta(days=7)))
    erros += confere("janela dos lembretes",
                     app.eventos_entre(svc, agora, agora + timedelta(days=1, hours=1)))
    erros += confere("radar do briefing (7 dias)",
                     app.eventos_entre(svc, agora.replace(hour=23, minute=59),
                                       agora + timedelta(days=7)))
    erros += confere("ano inteiro pra tras e pra frente",
                     app.eventos_entre(svc, agora - timedelta(days=365),
                                       agora + timedelta(days=365)))

    print("\n4) Limpando...")
    n = naoentendi.limpar(svc)
    print(f"  [ OK ] {n} registro(s) apagado(s)")
    if naoentendi.listar(svc):
        print("  [FALHA] sobrou registro depois de limpar")
        erros += 1

    print()
    if erros:
        print(f"=> {erros} problema(s).")
        sys.exit(1)
    print("=> Caderninho funciona e nao contamina nada.")


if __name__ == "__main__":
    main()
