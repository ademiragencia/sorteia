"""Interface de linha de comando do SorteIA."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .analise import Estatisticas, analisar
from .demo import gerar_historico
from .fontes import atualizar, carregar_cache
from .jogos import JOGOS, Jogo, obter_jogo
from .palpite import ESTRATEGIAS, gerar

BANNER = r"""
   _____            __       ________
  / ___/____  _____/ /____  /  _/   |
  \__ \/ __ \/ ___/ __/ _ \ / // /| |
 ___/ / /_/ / /  / /_/  __// // ___ |
/____/\____/_/   \__/\___/___/_/  |_|
"""

AVISO = (
    "⚠️  Loteria é sorte: todo sorteio é aleatório e independente do passado.\n"
    "   O SorteIA analisa o histórico real e gera jogos estatisticamente bem\n"
    "   distribuídos, mas NENHUM sistema aumenta a chance real de ganhar.\n"
    "   Jogue com responsabilidade. 🍀"
)


def _obter_historico(jogo: Jogo, usar_demo: bool) -> list[dict]:
    if usar_demo:
        print(f"🧪 Modo demo: histórico sintético de {jogo.nome} (sem internet).")
        return gerar_historico(jogo)
    historico = carregar_cache(jogo)
    if not historico:
        print(f"Cache vazio para {jogo.nome}; baixando histórico completo...")
        historico = atualizar(jogo)
    return historico


def _estatisticas(jogo: Jogo, usar_demo: bool) -> Estatisticas:
    return analisar(jogo, _obter_historico(jogo, usar_demo))


def comando_jogos(_args) -> None:
    print("Jogos suportados:\n")
    for jogo in JOGOS.values():
        detalhes = f"{jogo.marcados} números de {jogo.minimo} a {jogo.maximo}"
        if jogo.colunas:
            detalhes = f"{jogo.colunas} colunas com dígitos de 0 a 9"
        if jogo.trevos:
            detalhes += f" + {jogo.trevos} trevos"
        if jogo.tem_mes:
            detalhes += " + Mês de Sorte"
        print(f"  {jogo.emoji} {jogo.slug:<15} {jogo.nome:<14} — {detalhes}")


def comando_atualizar(args) -> None:
    slugs = list(JOGOS) if args.jogo in (None, "todos") else [obter_jogo(args.jogo).slug]
    for slug in slugs:
        try:
            atualizar(JOGOS[slug])
        except RuntimeError as erro:
            print(f"❌ {erro}")


def comando_analise(args) -> None:
    jogo = obter_jogo(args.jogo)
    stats = _estatisticas(jogo, args.demo)
    print(f"\n{jogo.emoji} Análise de {jogo.nome} — {stats.total_concursos} concursos\n")

    def linha(titulo: str, itens: list[tuple[int, int]], unidade: str) -> None:
        corpo = "  ".join(f"{num:>2} ({valor}{unidade})" for num, valor in itens)
        print(f"  {titulo:<22} {corpo}")

    if jogo.colunas:
        print("  Dígito mais frequente por coluna:")
        for coluna, contagem in enumerate(stats.freq_colunas, start=1):
            digito, vezes = contagem.most_common(1)[0]
            print(f"    coluna {coluna}: {digito} ({vezes}x)")
    else:
        linha("🔥 Mais sorteados:", stats.mais_quentes(8), "x")
        linha("🧊 Menos sorteados:", stats.mais_frios(8), "x")
        linha("⏳ Mais atrasados:", stats.mais_atrasados(8), " conc.")
        p10, mediana, p90 = stats.faixa_de_soma()
        print(f"  Σ  Soma típica por sorteio: {p10}–{p90} (mediana {mediana})")
        print(f"  ◐  Quantidade típica de ímpares: {stats.impares_tipico()} de {jogo.sorteados}")
    if stats.freq_mes:
        mes, vezes = stats.freq_mes.most_common(1)[0]
        print(f"  📅 Mês de Sorte mais sorteado: {mes} ({vezes}x)")
    if stats.freq_trevos:
        trevos = "  ".join(f"{t} ({v}x)" for t, v in stats.freq_trevos.most_common(6))
        print(f"  🍀 Trevos por frequência: {trevos}")
    print()


def comando_palpite(args) -> None:
    jogo = obter_jogo(args.jogo)
    stats = _estatisticas(jogo, args.demo)
    palpites = gerar(stats, quantidade=args.quantidade,
                     estrategia=args.estrategia, semente=args.semente)
    print(f"\n{jogo.emoji} Palpites SorteIA para {jogo.nome} "
          f"(estratégia: {args.estrategia}, base: {stats.total_concursos} concursos)\n")
    for i, palpite in enumerate(palpites, start=1):
        nota = f"  [afinidade {palpite.pontuacao:.0%}]" if palpite.pontuacao else ""
        print(f"  Jogo {i}: {palpite.formatado()}{nota}")
    print(f"\n{AVISO}\n")


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sorteia",
        description="SorteIA — sorteador palpiteiro inteligente das Loterias Caixa",
    )
    parser.add_argument("--versao", action="version", version=f"SorteIA {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("jogos", help="lista os jogos suportados").set_defaults(func=comando_jogos)

    p_atualizar = sub.add_parser("atualizar", help="baixa/atualiza os históricos oficiais")
    p_atualizar.add_argument("jogo", nargs="?", default="todos",
                             help="jogo específico ou 'todos' (padrão)")
    p_atualizar.set_defaults(func=comando_atualizar)

    p_analise = sub.add_parser("analise", help="estatísticas do histórico de um jogo")
    p_analise.add_argument("jogo")
    p_analise.add_argument("--demo", action="store_true",
                           help="usa histórico sintético (sem internet)")
    p_analise.set_defaults(func=comando_analise)

    p_palpite = sub.add_parser("palpite", help="gera palpites para um jogo")
    p_palpite.add_argument("jogo")
    p_palpite.add_argument("-n", "--quantidade", type=int, default=3,
                           help="quantidade de jogos (padrão: 3)")
    p_palpite.add_argument("-e", "--estrategia", choices=ESTRATEGIAS,
                           default="inteligente", help="estratégia de geração")
    p_palpite.add_argument("--semente", type=int, default=None,
                           help="semente para resultados reproduzíveis")
    p_palpite.add_argument("--demo", action="store_true",
                           help="usa histórico sintético (sem internet)")
    p_palpite.set_defaults(func=comando_palpite)
    return parser


def main(argv: list[str] | None = None) -> int:
    print(BANNER)
    args = montar_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyError as erro:
        print(f"❌ {erro.args[0]}")
        return 2
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
