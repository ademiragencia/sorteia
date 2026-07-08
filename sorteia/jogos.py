"""Configuração de todos os jogos da Loteria Caixa suportados pelo SorteIA."""

from dataclasses import dataclass


MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


@dataclass(frozen=True)
class Jogo:
    slug: str            # identificador usado nas APIs da Caixa
    nome: str            # nome oficial do jogo
    minimo: int          # menor número do volante
    maximo: int          # maior número do volante
    marcados: int        # quantidade de números marcados na aposta simples
    sorteados: int       # quantidade de números sorteados por concurso
    sorteios_por_concurso: int = 1   # Dupla Sena tem 2 sorteios
    tem_mes: bool = False            # Dia de Sorte sorteia o "Mês de Sorte"
    trevos: int = 0                  # +Milionária sorteia 2 trevos (1 a 6)
    colunas: int = 0                 # Super Sete: 7 colunas de 0 a 9
    emoji: str = "🎱"


JOGOS: dict[str, Jogo] = {
    j.slug: j
    for j in [
        Jogo("megasena", "Mega-Sena", 1, 60, 6, 6, emoji="💚"),
        Jogo("lotofacil", "Lotofácil", 1, 25, 15, 15, emoji="💜"),
        Jogo("quina", "Quina", 1, 80, 5, 5, emoji="💙"),
        Jogo("lotomania", "Lotomania", 0, 99, 50, 20, emoji="🧡"),
        Jogo("duplasena", "Dupla Sena", 1, 50, 6, 6, sorteios_por_concurso=2, emoji="❤️"),
        Jogo("timemania", "Timemania", 1, 80, 10, 7, emoji="💛"),
        Jogo("diadesorte", "Dia de Sorte", 1, 31, 7, 7, tem_mes=True, emoji="🍀"),
        Jogo("supersete", "Super Sete", 0, 9, 7, 7, colunas=7, emoji="🎰"),
        Jogo("maismilionaria", "+Milionária", 1, 50, 6, 6, trevos=2, emoji="💰"),
    ]
}


def obter_jogo(slug: str) -> Jogo:
    slug = slug.lower().strip().replace("-", "").replace("_", "").replace("+", "mais")
    apelidos = {
        "mega": "megasena",
        "sena": "megasena",
        "facil": "lotofacil",
        "loto": "lotofacil",
        "dupla": "duplasena",
        "time": "timemania",
        "diasorte": "diadesorte",
        "milionaria": "maismilionaria",
        "super7": "supersete",
    }
    slug = apelidos.get(slug, slug)
    if slug not in JOGOS:
        validos = ", ".join(sorted(JOGOS))
        raise KeyError(f"Jogo desconhecido: {slug!r}. Jogos válidos: {validos}")
    return JOGOS[slug]
