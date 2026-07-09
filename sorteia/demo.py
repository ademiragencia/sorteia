"""Gerador de histórico sintético para testar o SorteIA sem internet.

O modo demo cria concursos aleatórios com pequenos vieses artificiais para
que as análises e estratégias tenham o que mostrar. Serve apenas para
experimentar a ferramenta — os palpites sobre dados demo não têm relação
com os sorteios reais.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .jogos import MESES, Jogo


def gerar_historico(jogo: Jogo, concursos: int = 500, semente: int = 42) -> list[dict]:
    rng = random.Random(semente)
    universo = list(range(jogo.minimo, jogo.maximo + 1))
    # viés artificial e estável por número, só para o demo ficar interessante
    pesos = {n: 1.0 + 0.35 * rng.random() for n in universo}
    inicio = date.today() - timedelta(days=concursos * 3)

    historico = []
    for i in range(1, concursos + 1):
        registro: dict = {
            "concurso": i,
            "data": (inicio + timedelta(days=i * 3)).strftime("%d/%m/%Y"),
            "sorteios": [],
        }
        for _ in range(jogo.sorteios_por_concurso):
            if jogo.colunas:
                sorteio = [rng.randrange(10) for _ in range(jogo.colunas)]
            else:
                sorteio = sorted(_amostra(universo, pesos, jogo.sorteados, rng))
            registro["sorteios"].append(sorteio)
        if jogo.tem_mes:
            registro["mes"] = rng.choice(MESES)
        if jogo.trevos:
            registro["trevos"] = sorted(rng.sample(range(1, 7), jogo.trevos))
        historico.append(registro)
    sorteados = jogo.colunas or jogo.sorteados
    historico[-1]["premiacoes"] = [
        {"descricao": f"{sorteados} acertos", "ganhadores": 0, "valor": 0.0},
        {"descricao": f"{sorteados - 1} acertos",
         "ganhadores": rng.randrange(1, 90),
         "valor": round(rng.uniform(8_000, 95_000), 2)},
        {"descricao": f"{sorteados - 2} acertos",
         "ganhadores": rng.randrange(150, 6_000),
         "valor": round(rng.uniform(80, 1_400), 2)},
    ]
    historico[-1]["proximo"] = {
        "data": (inicio + timedelta(days=(concursos + 1) * 3)).strftime("%d/%m/%Y"),
        "estimativa": float(rng.randrange(3, 120) * 1_000_000),
        "acumulou": rng.random() < 0.5,
    }
    return historico


def _amostra(universo: list[int], pesos: dict[int, float], k: int, rng: random.Random) -> list[int]:
    disponiveis = dict(pesos)
    escolhidos = []
    for _ in range(k):
        numeros = list(disponiveis)
        sorteado = rng.choices(numeros, weights=[disponiveis[n] for n in numeros], k=1)[0]
        escolhidos.append(sorteado)
        del disponiveis[sorteado]
    return escolhidos
