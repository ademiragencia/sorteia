"""Testes do SorteIA — rode com: python -m unittest discover testes"""

import unittest

from sorteia.analise import analisar
from sorteia.demo import gerar_historico
from sorteia.jogos import JOGOS, obter_jogo
from sorteia.palpite import ESTRATEGIAS, gerar


class TestJogos(unittest.TestCase):
    def test_apelidos(self):
        self.assertEqual(obter_jogo("mega").slug, "megasena")
        self.assertEqual(obter_jogo("Mega-Sena").slug, "megasena")
        self.assertEqual(obter_jogo("+milionaria").slug, "maismilionaria")

    def test_jogo_desconhecido(self):
        with self.assertRaises(KeyError):
            obter_jogo("federal")


class TestAnalise(unittest.TestCase):
    def test_analise_todos_os_jogos(self):
        for jogo in JOGOS.values():
            historico = gerar_historico(jogo, concursos=120)
            stats = analisar(jogo, historico)
            self.assertEqual(stats.total_concursos, 120)
            if jogo.colunas:
                self.assertEqual(len(stats.freq_colunas), jogo.colunas)
            else:
                # todo número sorteado ao menos uma vez em 120 concursos? não
                # necessariamente — mas a frequência nunca aponta fora do volante
                for numero in stats.frequencia:
                    self.assertGreaterEqual(numero, jogo.minimo)
                    self.assertLessEqual(numero, jogo.maximo)
                p10, mediana, p90 = stats.faixa_de_soma()
                self.assertLessEqual(p10, mediana)
                self.assertLessEqual(mediana, p90)

    def test_atraso_zerado_para_ultimo_sorteio(self):
        jogo = JOGOS["megasena"]
        historico = gerar_historico(jogo, concursos=50)
        stats = analisar(jogo, historico)
        for numero in historico[-1]["sorteios"][0]:
            self.assertEqual(stats.atraso[numero], 0)


class TestPalpites(unittest.TestCase):
    def test_todas_estrategias_todos_jogos(self):
        for jogo in JOGOS.values():
            stats = analisar(jogo, gerar_historico(jogo, concursos=80))
            for estrategia in ESTRATEGIAS:
                palpites = gerar(stats, quantidade=2, estrategia=estrategia, semente=7)
                self.assertEqual(len(palpites), 2)
                for palpite in palpites:
                    self.assertEqual(len(palpite.numeros), jogo.marcados)
                    if jogo.colunas:
                        for digito in palpite.numeros:
                            self.assertIn(digito, range(10))
                    else:
                        # sem repetição e dentro do volante
                        self.assertEqual(len(set(palpite.numeros)), jogo.marcados)
                        for numero in palpite.numeros:
                            self.assertGreaterEqual(numero, jogo.minimo)
                            self.assertLessEqual(numero, jogo.maximo)
                    if jogo.trevos:
                        self.assertEqual(len(palpite.trevos), jogo.trevos)
                        self.assertEqual(len(set(palpite.trevos)), jogo.trevos)
                    if jogo.tem_mes:
                        self.assertIsNotNone(palpite.mes)

    def test_semente_reproduz_resultado(self):
        jogo = JOGOS["lotofacil"]
        stats = analisar(jogo, gerar_historico(jogo, concursos=100))
        a = gerar(stats, quantidade=3, estrategia="inteligente", semente=123)
        b = gerar(stats, quantidade=3, estrategia="inteligente", semente=123)
        self.assertEqual([p.numeros for p in a], [p.numeros for p in b])

    def test_palpites_distintos(self):
        jogo = JOGOS["megasena"]
        stats = analisar(jogo, gerar_historico(jogo, concursos=100))
        palpites = gerar(stats, quantidade=5, estrategia="quentes", semente=1)
        chaves = {tuple(p.numeros) for p in palpites}
        self.assertEqual(len(chaves), 5)

    def test_estrategia_invalida(self):
        jogo = JOGOS["quina"]
        stats = analisar(jogo, gerar_historico(jogo, concursos=30))
        with self.assertRaises(ValueError):
            gerar(stats, estrategia="magica")


if __name__ == "__main__":
    unittest.main()
