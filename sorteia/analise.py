"""Análise estatística do histórico de concursos de um jogo."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

from .jogos import Jogo

JANELA_RECENTE = 50  # concursos considerados "recentes"


@dataclass
class Estatisticas:
    jogo: Jogo
    total_concursos: int
    frequencia: Counter            # número -> vezes sorteado (histórico inteiro)
    freq_recente: Counter          # número -> vezes sorteado nos últimos N concursos
    atraso: dict[int, int]         # número -> concursos desde a última aparição
    pares: Counter                 # (a, b) -> vezes que saíram juntos
    somas: list[int]               # soma das dezenas de cada sorteio
    impares: Counter               # qtd de ímpares por sorteio -> ocorrências
    freq_mes: Counter = field(default_factory=Counter)     # Dia de Sorte
    freq_trevos: Counter = field(default_factory=Counter)  # +Milionária
    freq_colunas: list[Counter] = field(default_factory=list)  # Super Sete

    @property
    def universo(self) -> list[int]:
        return list(range(self.jogo.minimo, self.jogo.maximo + 1))

    def mais_quentes(self, n: int = 10) -> list[tuple[int, int]]:
        return self.frequencia.most_common(n)

    def mais_frios(self, n: int = 10) -> list[tuple[int, int]]:
        return sorted(
            ((num, self.frequencia.get(num, 0)) for num in self.universo),
            key=lambda par: par[1],
        )[:n]

    def mais_atrasados(self, n: int = 10) -> list[tuple[int, int]]:
        return sorted(self.atraso.items(), key=lambda par: -par[1])[:n]

    def faixa_de_soma(self) -> tuple[int, int, int]:
        """(p10, mediana, p90) da soma histórica das dezenas de um sorteio."""
        if not self.somas:
            return (0, 0, 0)
        ordenadas = sorted(self.somas)
        p10 = ordenadas[int(len(ordenadas) * 0.10)]
        p90 = ordenadas[min(int(len(ordenadas) * 0.90), len(ordenadas) - 1)]
        return (p10, int(statistics.median(ordenadas)), p90)

    def impares_tipico(self) -> int:
        """Quantidade de ímpares mais comum em um sorteio."""
        if not self.impares:
            return self.jogo.sorteados // 2
        return self.impares.most_common(1)[0][0]


def analisar(jogo: Jogo, concursos: list[dict]) -> Estatisticas:
    frequencia: Counter = Counter()
    freq_recente: Counter = Counter()
    atraso: dict[int, int] = {n: len(concursos) for n in range(jogo.minimo, jogo.maximo + 1)}
    pares: Counter = Counter()
    somas: list[int] = []
    impares: Counter = Counter()
    freq_mes: Counter = Counter()
    freq_trevos: Counter = Counter()
    freq_colunas: list[Counter] = [Counter() for _ in range(jogo.colunas)]

    concursos = sorted(concursos, key=lambda c: c["concurso"])
    inicio_recente = max(0, len(concursos) - JANELA_RECENTE)

    for indice, concurso in enumerate(concursos):
        restantes = len(concursos) - indice - 1
        for sorteio in concurso["sorteios"]:
            frequencia.update(sorteio)
            if indice >= inicio_recente:
                freq_recente.update(sorteio)
            for numero in sorteio:
                atraso[numero] = min(atraso.get(numero, restantes), restantes)
            somas.append(sum(sorteio))
            impares[sum(1 for n in sorteio if n % 2)] += 1
            if jogo.colunas:
                for coluna, digito in enumerate(sorteio[: jogo.colunas]):
                    freq_colunas[coluna][digito] += 1
            else:
                pares.update(combinations(sorted(sorteio), 2))
        if concurso.get("mes"):
            freq_mes[concurso["mes"]] += 1
        for trevo in concurso.get("trevos", []):
            freq_trevos[trevo] += 1

    return Estatisticas(
        jogo=jogo,
        total_concursos=len(concursos),
        frequencia=frequencia,
        freq_recente=freq_recente,
        atraso=atraso,
        pares=pares,
        somas=somas,
        impares=impares,
        freq_mes=freq_mes,
        freq_trevos=freq_trevos,
        freq_colunas=freq_colunas,
    )
