# -*- coding: utf-8 -*-
"""
Como o robô se comporta quando o Granatum está fora do ar.

O Granatum cai de vez em quando (visto devolvendo 502 em série). Nesses
momentos o certo NÃO é gritar: a fotografia anterior ainda responde bem e o
serviço volta sozinho. Alarme de hora em hora vira ruído, e ruído ensina a
pessoa a ignorar justamente o aviso que importa.

Este teste fixa a regra: só incomoda quando o dado envelheceu de verdade.

Uso:  .venv\\Scripts\\python testar_falha_coleta.py
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import assessor as app
import snapshot

QUEDA = RuntimeError("502 Server Error: Bad Gateway for url: .../v1/contas")


def simular(horas_da_foto):
    """Roda main() com o Granatum fora e uma foto de N horas. Devolve (saida, avisos)."""
    avisos = []
    app.enviar = lambda t, botoes=None: avisos.append(t)

    coletar_real, carregar_real = snapshot.coletar, snapshot.carregar
    arquivo_real = snapshot.ARQUIVO_ERRO
    # Path nao aceita troca de metodo; aponto o arquivo pra um temporario.
    temporario = Path(tempfile.gettempdir()) / "assessor_teste_erro.txt"

    def coletar_falso():
        raise QUEDA

    def carregar_falso():
        if horas_da_foto is None:
            return None
        quando = datetime.now(app.TZ) - timedelta(hours=horas_da_foto)
        return {"atualizado_em": quando.isoformat(), "abertos": []}

    snapshot.coletar = coletar_falso
    snapshot.carregar = carregar_falso
    snapshot.ARQUIVO_ERRO = temporario
    try:
        snapshot.main()
        saida = 0
    except SystemExit as e:
        saida = e.code or 0
    finally:
        snapshot.coletar, snapshot.carregar = coletar_real, carregar_real
        snapshot.ARQUIVO_ERRO = arquivo_real

    texto = temporario.read_text(encoding="utf-8") if temporario.exists() else ""
    if temporario.exists():
        temporario.unlink()
    return saida, avisos, texto


CASOS = [
    # (horas da foto, saida esperada, deve avisar?)
    (0.5,  0, False),   # acabou de atualizar: queda passageira, silêncio
    (3.0,  0, False),   # ainda dentro do aceitável
    (8.0,  1, True),    # dado velho: agora é problema
    (None, 1, True),    # nunca teve foto: problema desde já
]


def main():
    erros = 0
    for horas, saida_esp, avisar_esp in CASOS:
        saida, avisos, arquivo = simular(horas)
        rotulo = f"foto de {horas}h" if horas is not None else "sem foto"
        ok_saida = saida == saida_esp
        ok_aviso = bool(avisos) == avisar_esp
        ok_arquivo = "502" in arquivo          # motivo sempre registrado
        ok = ok_saida and ok_aviso and ok_arquivo
        if not ok:
            erros += 1
        print(f"  {'[ OK ]' if ok else '[FALHA]'} {rotulo:<14} "
              f"saida={saida} (esp {saida_esp}) | "
              f"avisou={'sim' if avisos else 'nao'} (esp {'sim' if avisar_esp else 'nao'}) | "
              f"motivo gravado={'sim' if ok_arquivo else 'NAO'}")

    print()
    if erros:
        print(f"=> {erros} caso(s) errado(s) de {len(CASOS)}.")
        sys.exit(1)
    print(f"=> Os {len(CASOS)} casos passaram.")


if __name__ == "__main__":
    main()
