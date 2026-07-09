"""Testes da interface web (WSGI) — rode com: python -m unittest discover testes"""

import json
import time
import unittest

from sorteia import web
from sorteia.jogos import JOGOS
from sorteia.web import app


def chamar(caminho: str):
    if "?" in caminho:
        rota, consulta = caminho.split("?", 1)
    else:
        rota, consulta = caminho, ""
    estado = {}

    def start_response(status, cabecalhos):
        estado["status"] = int(status.split()[0])
        estado["cabecalhos"] = dict(cabecalhos)

    corpo = b"".join(app({"PATH_INFO": rota, "QUERY_STRING": consulta},
                         start_response))
    if "json" in estado["cabecalhos"]["Content-Type"]:
        return estado["status"], json.loads(corpo)
    return estado["status"], corpo


class TestRotas(unittest.TestCase):
    def test_pagina_inicial(self):
        status, corpo = chamar("/")
        self.assertEqual(status, 200)
        self.assertIn(b"SorteIA", corpo)
        self.assertNotIn(b"github", corpo.lower())

    def test_manifesto_e_icones(self):
        status, corpo = chamar("/manifest.webmanifest")
        self.assertEqual(status, 200)
        self.assertEqual(corpo["short_name"], "SorteIA")
        status, corpo = chamar("/icone-192.png")
        self.assertEqual(status, 200)
        self.assertEqual(corpo[:8], b"\x89PNG\r\n\x1a\n")

    def test_rota_inexistente(self):
        status, corpo = chamar("/nada")
        self.assertEqual(status, 404)


class TestApiPalpite(unittest.TestCase):
    def test_palpite_demo_completo(self):
        status, d = chamar("/api/palpite?jogo=megasena&n=2&demo=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(d["palpites"]), 2)
        self.assertIn("loteriasonline.caixa.gov.br", d["aposta_url"])
        self.assertIn("estimativa", d["proximo"])
        self.assertEqual(d["ultimo_concurso"]["numero"], d["base_concursos"])


class TestApiStatus(unittest.TestCase):
    def test_status_demo(self):
        status, d = chamar("/api/status?jogo=megasena&demo=1")
        self.assertEqual(status, 200)
        self.assertEqual(d["ultimo"]["numero"], d["total_concursos"])
        self.assertTrue(d["ultimo"]["premiacoes"])
        self.assertIn("estimativa", d["proximo"])

    def test_status_duplasena_dois_sorteios(self):
        status, d = chamar("/api/status?jogo=duplasena&demo=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(d["ultimo"]["dezenas2"]), 6)


class TestMesclarUltimo(unittest.TestCase):
    def setUp(self):
        self.jogo = JOGOS["megasena"]
        web._memoria_ultimo.clear()

    def tearDown(self):
        web._memoria_ultimo.clear()

    def _injetar(self, registro):
        # simula um "último concurso" fresco vindo da API oficial
        web._memoria_ultimo[self.jogo.slug] = (time.time(), registro)

    def test_substitui_mesmo_concurso_com_dados_frescos(self):
        cache = [{"concurso": 100, "sorteios": [[1, 2, 3, 4, 5, 6]],
                  "proximo": {"estimativa": 1_000_000.0}}]
        fresco = {"concurso": 100, "sorteios": [[1, 2, 3, 4, 5, 6]],
                  "proximo": {"estimativa": 2_000_000.0}}
        self._injetar(fresco)
        saida = web._mesclar_ultimo(self.jogo, cache)
        self.assertEqual(saida[-1]["proximo"]["estimativa"], 2_000_000.0)
        self.assertEqual(len(saida), 1)

    def test_anexa_concurso_novo(self):
        cache = [{"concurso": 100, "sorteios": [[1, 2, 3, 4, 5, 6]]}]
        fresco = {"concurso": 101, "sorteios": [[7, 8, 9, 10, 11, 12]]}
        self._injetar(fresco)
        saida = web._mesclar_ultimo(self.jogo, cache)
        self.assertEqual(len(saida), 2)
        self.assertEqual(saida[-1]["concurso"], 101)

    def test_ignora_ultimo_mais_antigo_que_o_cache(self):
        cache = [{"concurso": 100, "sorteios": [[1, 2, 3, 4, 5, 6]]}]
        self._injetar({"concurso": 99, "sorteios": [[7, 8, 9, 10, 11, 12]]})
        saida = web._mesclar_ultimo(self.jogo, cache)
        self.assertEqual(len(saida), 1)
        self.assertEqual(saida[-1]["concurso"], 100)


class TestApiConferir(unittest.TestCase):
    def test_conferir_demo(self):
        status, d = chamar("/api/conferir?jogo=megasena&numeros=1,2,3,4,5,6&demo=1")
        self.assertEqual(status, 200)
        self.assertEqual(d["numeros"], [1, 2, 3, 4, 5, 6])
        self.assertLessEqual(d["ultimo"]["acertos"], 6)
        self.assertEqual(sum(d["historico"]["distribuicao"].values()),
                         d["historico"]["total_sorteios"])
        self.assertEqual(d["faixa_premiada_min"], 4)

    def test_conferir_supersete_posicional(self):
        status, d = chamar("/api/conferir?jogo=supersete&numeros=1,2,3,4,5,6,7&demo=1")
        self.assertEqual(status, 200)
        self.assertLessEqual(d["historico"]["melhor"], 7)

    def test_conferir_duplasena_conta_dois_sorteios(self):
        status, d = chamar("/api/conferir?jogo=duplasena&numeros=1,2,3,4,5,6&demo=1")
        self.assertEqual(status, 200)
        # modo demo gera 500 concursos; Dupla Sena tem 2 sorteios por concurso
        self.assertEqual(d["historico"]["total_sorteios"], 1000)

    def test_validacoes(self):
        casos = [
            "/api/conferir?jogo=megasena&numeros=1,2,3&demo=1",        # poucos
            "/api/conferir?jogo=megasena&numeros=1,2,3,4,5,99&demo=1", # fora do volante
            "/api/conferir?jogo=megasena&numeros=1,1,2,3,4,5&demo=1",  # repetido
            "/api/conferir?jogo=supersete&numeros=1,2,3&demo=1",       # colunas erradas
            "/api/conferir?jogo=megasena&numeros=&demo=1",             # vazio
        ]
        for caso in casos:
            status, d = chamar(caso)
            self.assertEqual(status, 400, caso)
            self.assertIn("erro", d)

    def test_aposta_maior_permitida(self):
        status, d = chamar(
            "/api/conferir?jogo=megasena&numeros=1,2,3,4,5,6,7,8,9,10&demo=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(d["numeros"]), 10)


if __name__ == "__main__":
    unittest.main()
