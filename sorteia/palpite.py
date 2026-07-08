"""Geração de palpites a partir das estatísticas históricas.

Estratégias disponíveis:

- ``quentes``      — favorece os números mais sorteados da história do jogo.
- ``atrasados``    — favorece os números que estão há mais tempo sem sair.
- ``equilibrado``  — mistura frequência histórica, frequência recente e atraso.
- ``surpresa``     — sorteio uniforme, sem viés (linha de base honesta).
- ``inteligente``  — (padrão) gera centenas de candidatos com pesos combinados
  e pontua cada um por afinidade de pares, soma plausível, proporção de
  ímpares e distribuição pelo volante, devolvendo os melhores.

Nenhuma estratégia altera a probabilidade real de ganhar: todo sorteio da
Caixa é aleatório e independente do passado. O SorteIA gera jogos bem
distribuídos e estatisticamente "típicos" — e deixa a sorte para você. 🍀
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .analise import Estatisticas
from .jogos import MESES, Jogo

ESTRATEGIAS = ("inteligente", "quentes", "atrasados", "equilibrado", "surpresa")


@dataclass
class Palpite:
    jogo: Jogo
    numeros: list[int]
    estrategia: str
    mes: str | None = None          # Dia de Sorte
    trevos: list[int] = field(default_factory=list)  # +Milionária
    pontuacao: float = 0.0

    def formatado(self) -> str:
        if self.jogo.colunas:
            corpo = " ".join(str(n) for n in self.numeros)
        else:
            largura = len(str(self.jogo.maximo))
            corpo = " ".join(f"{n:0{largura}d}" for n in self.numeros)
        extras = []
        if self.trevos:
            extras.append("🍀 trevos: " + " e ".join(map(str, self.trevos)))
        if self.mes:
            extras.append(f"📅 mês: {self.mes}")
        return corpo + ("   " + "  ".join(extras) if extras else "")


def _normalizar(pesos: dict[int, float]) -> dict[int, float]:
    maior = max(pesos.values()) or 1.0
    return {k: v / maior for k, v in pesos.items()}


def _pesos(stats: Estatisticas, estrategia: str) -> dict[int, float]:
    universo = stats.universo
    freq = _normalizar({n: stats.frequencia.get(n, 0) + 1.0 for n in universo})
    recente = _normalizar({n: stats.freq_recente.get(n, 0) + 1.0 for n in universo})
    atraso = _normalizar({n: stats.atraso.get(n, 0) + 1.0 for n in universo})

    if estrategia == "quentes":
        return {n: freq[n] ** 2 for n in universo}
    if estrategia == "atrasados":
        return {n: atraso[n] ** 2 for n in universo}
    if estrategia == "surpresa":
        return {n: 1.0 for n in universo}
    # equilibrado / inteligente
    return {n: 0.45 * freq[n] + 0.30 * recente[n] + 0.25 * atraso[n] for n in universo}


def _amostrar(pesos: dict[int, float], quantidade: int, rng: random.Random) -> list[int]:
    """Amostragem ponderada sem reposição."""
    disponiveis = dict(pesos)
    escolhidos: list[int] = []
    for _ in range(quantidade):
        numeros = list(disponiveis)
        valores = [disponiveis[n] for n in numeros]
        sorteado = rng.choices(numeros, weights=valores, k=1)[0]
        escolhidos.append(sorteado)
        del disponiveis[sorteado]
    return sorted(escolhidos)


def _pontuar(numeros: list[int], stats: Estatisticas) -> float:
    """Nota de 0 a 1 medindo o quão 'típico' o jogo é frente ao histórico."""
    jogo = stats.jogo
    nota = 0.0

    # 1) soma dentro da faixa histórica central (p10–p90)
    p10, _, p90 = stats.faixa_de_soma()
    fator = jogo.sorteados / max(len(numeros), 1)
    soma_ajustada = sum(numeros) * fator  # compara apostas maiores na mesma escala
    if p90 and p10 <= soma_ajustada <= p90:
        nota += 0.30

    # 2) proporção de ímpares próxima da típica
    tipico = stats.impares_tipico() * len(numeros) / jogo.sorteados
    impares = sum(1 for n in numeros if n % 2)
    nota += 0.25 * max(0.0, 1.0 - abs(impares - tipico) / max(len(numeros), 1) * 2)

    # 3) afinidade de pares: média histórica dos pares presentes no jogo
    if stats.pares:
        media_geral = sum(stats.pares.values()) / len(stats.pares)
        pares_do_jogo = [
            stats.pares.get((a, b), 0)
            for i, a in enumerate(numeros)
            for b in numeros[i + 1:]
        ]
        if pares_do_jogo:
            media_jogo = sum(pares_do_jogo) / len(pares_do_jogo)
            nota += 0.25 * min(1.0, media_jogo / (media_geral * 1.5 or 1))

    # 4) espalhamento pelo volante (dividido em 5 faixas)
    amplitude = jogo.maximo - jogo.minimo + 1
    faixas = {min((n - jogo.minimo) * 5 // amplitude, 4) for n in numeros}
    nota += 0.20 * len(faixas) / 5

    return nota


def _palpite_supersete(stats: Estatisticas, estrategia: str, rng: random.Random) -> list[int]:
    """Super Sete: um dígito de 0 a 9 por coluna, ponderado por coluna."""
    numeros = []
    for coluna in range(stats.jogo.colunas):
        freq_col = stats.freq_colunas[coluna] if stats.freq_colunas else {}
        if estrategia == "surpresa" or not freq_col:
            pesos = {d: 1.0 for d in range(10)}
        else:
            pesos = _normalizar({d: freq_col.get(d, 0) + 1.0 for d in range(10)})
        digitos = list(pesos)
        numeros.append(rng.choices(digitos, weights=[pesos[d] for d in digitos], k=1)[0])
    return numeros


def _extras(stats: Estatisticas, estrategia: str, rng: random.Random) -> dict:
    extras: dict = {}
    jogo = stats.jogo
    if jogo.tem_mes:
        if estrategia == "surpresa" or not stats.freq_mes:
            extras["mes"] = rng.choice(MESES)
        else:
            pesos = {m: stats.freq_mes.get(m, 0) + 1.0 for m in MESES}
            extras["mes"] = rng.choices(list(pesos), weights=list(pesos.values()), k=1)[0]
    if jogo.trevos:
        universo = list(range(1, 7))
        if estrategia == "surpresa" or not stats.freq_trevos:
            extras["trevos"] = sorted(rng.sample(universo, jogo.trevos))
        else:
            pesos = {t: stats.freq_trevos.get(t, 0) + 1.0 for t in universo}
            extras["trevos"] = _amostrar(pesos, jogo.trevos, rng)
    return extras


def gerar(
    stats: Estatisticas,
    quantidade: int = 1,
    estrategia: str = "inteligente",
    semente: int | None = None,
) -> list[Palpite]:
    if estrategia not in ESTRATEGIAS:
        raise ValueError(
            f"Estratégia desconhecida: {estrategia!r}. Opções: {', '.join(ESTRATEGIAS)}"
        )
    jogo = stats.jogo
    rng = random.Random(semente)
    palpites: list[Palpite] = []
    vistos: set[tuple[int, ...]] = set()

    if jogo.colunas:  # Super Sete tem geração própria (por coluna)
        while len(palpites) < quantidade:
            numeros = _palpite_supersete(stats, estrategia, rng)
            chave = tuple(numeros)
            if chave in vistos and len(vistos) < 10 ** jogo.colunas:
                continue
            vistos.add(chave)
            palpites.append(Palpite(jogo, numeros, estrategia))
        return palpites

    pesos = _pesos(stats, estrategia)

    if estrategia == "inteligente":
        candidatos_por_palpite = 200
        candidatos = []
        for _ in range(quantidade * candidatos_por_palpite):
            numeros = _amostrar(pesos, jogo.marcados, rng)
            candidatos.append((_pontuar(numeros, stats), numeros))
        candidatos.sort(key=lambda par: -par[0])
        for pontuacao, numeros in candidatos:
            chave = tuple(numeros)
            if chave in vistos:
                continue
            vistos.add(chave)
            palpites.append(
                Palpite(jogo, numeros, estrategia, pontuacao=pontuacao, **_extras(stats, estrategia, rng))
            )
            if len(palpites) == quantidade:
                break
        return palpites

    while len(palpites) < quantidade:
        numeros = _amostrar(pesos, jogo.marcados, rng)
        chave = tuple(numeros)
        if chave in vistos:
            continue
        vistos.add(chave)
        palpites.append(
            Palpite(
                jogo,
                numeros,
                estrategia,
                pontuacao=_pontuar(numeros, stats),
                **_extras(stats, estrategia, rng),
            )
        )
    return palpites
