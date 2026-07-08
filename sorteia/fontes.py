"""Download e cache dos resultados históricos das Loterias Caixa.

Duas fontes de dados, com fallback automático:

1. API comunitária (histórico completo em uma única requisição):
   https://loteriascaixa-api.herokuapp.com/api/{jogo}
2. API oficial do Portal de Loterias da Caixa (concurso a concurso):
   https://servicebus2.caixa.gov.br/portaldeloterias/api/{jogo}/{concurso}

Os resultados ficam em cache local (``dados/{jogo}.json``); as atualizações
seguintes baixam apenas os concursos que ainda faltam.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from .jogos import Jogo

API_COMUNITARIA = "https://loteriascaixa-api.herokuapp.com/api/{slug}"
API_CAIXA = "https://servicebus2.caixa.gov.br/portaldeloterias/api/{slug}"

DIRETORIO_DADOS = Path(os.environ.get("SORTEIA_DADOS", "dados"))

_HEADERS = {
    "User-Agent": "SorteIA/1.0 (github.com/ademiragencia/sorteia)",
    "Accept": "application/json",
}


def _contexto_ssl() -> ssl.SSLContext:
    return ssl.create_default_context()


def _get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_contexto_ssl()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _dezenas(bruto: dict) -> list[list[int]]:
    """Extrai as listas de dezenas de um concurso, em qualquer formato de API."""
    listas = []
    principal = bruto.get("dezenas") or bruto.get("listaDezenas") or []
    if principal:
        listas.append([int(d) for d in principal])
    segundo = (
        bruto.get("dezenas2")
        or bruto.get("dezenasSegundoSorteio")
        or bruto.get("listaDezenasSegundoSorteio")
        or []
    )
    if segundo:
        listas.append([int(d) for d in segundo])
    return listas


def _normalizar(bruto: dict) -> dict | None:
    """Converte o registro cru de qualquer uma das APIs para o formato interno."""
    concurso = bruto.get("concurso") or bruto.get("numero")
    listas = _dezenas(bruto)
    if not concurso or not listas:
        return None
    registro = {
        "concurso": int(concurso),
        "data": bruto.get("data") or bruto.get("dataApuracao") or "",
        "sorteios": listas,
    }
    mes = bruto.get("mesSorte") or bruto.get("nomeTimeCoracaoMesSorte")
    if mes:
        registro["mes"] = str(mes).strip().title()
    trevos = bruto.get("trevos") or bruto.get("trevosSorteados")
    if trevos:
        registro["trevos"] = [int(t) for t in trevos]
    return registro


def caminho_cache(jogo: Jogo) -> Path:
    return DIRETORIO_DADOS / f"{jogo.slug}.json"


def carregar_cache(jogo: Jogo) -> list[dict]:
    arquivo = caminho_cache(jogo)
    if arquivo.exists():
        return json.loads(arquivo.read_text(encoding="utf-8"))
    return []


def salvar_cache(jogo: Jogo, concursos: list[dict]) -> None:
    DIRETORIO_DADOS.mkdir(parents=True, exist_ok=True)
    concursos = sorted(concursos, key=lambda c: c["concurso"])
    caminho_cache(jogo).write_text(
        json.dumps(concursos, ensure_ascii=False), encoding="utf-8"
    )


def _baixar_comunitaria(jogo: Jogo) -> list[dict]:
    dados = _get_json(API_COMUNITARIA.format(slug=jogo.slug), timeout=120)
    registros = [r for r in (_normalizar(b) for b in dados) if r]
    if not registros:
        raise ValueError("API comunitária não retornou concursos")
    return registros


def _baixar_oficial(jogo: Jogo, existentes: dict[int, dict], log) -> list[dict]:
    ultimo = _get_json(API_CAIXA.format(slug=jogo.slug))
    numero_final = int(ultimo.get("numero") or ultimo.get("concurso"))
    registro = _normalizar(ultimo)
    if registro:
        existentes[registro["concurso"]] = registro
    faltantes = [n for n in range(1, numero_final + 1) if n not in existentes]
    url_base = API_CAIXA.format(slug=jogo.slug)
    for i, n in enumerate(faltantes):
        try:
            registro = _normalizar(_get_json(f"{url_base}/{n}"))
            if registro:
                existentes[registro["concurso"]] = registro
        except (urllib.error.URLError, ValueError, json.JSONDecodeError):
            continue
        if i and i % 100 == 0:
            log(f"    ... {i}/{len(faltantes)} concursos baixados")
            salvar_cache_parcial = list(existentes.values())
            # checkpoint para não perder progresso em históricos longos
            salvar_cache(jogo, salvar_cache_parcial)
        time.sleep(0.15)  # gentileza com a API oficial
    return list(existentes.values())


def atualizar(jogo: Jogo, log=print) -> list[dict]:
    """Atualiza o histórico local do jogo e retorna todos os concursos."""
    existentes = {c["concurso"]: c for c in carregar_cache(jogo)}
    log(f"{jogo.emoji} {jogo.nome}: {len(existentes)} concursos em cache")
    try:
        registros = _baixar_comunitaria(jogo)
        for r in registros:
            existentes[r["concurso"]] = r
        log(f"    histórico completo obtido da API comunitária "
            f"({len(existentes)} concursos)")
    except Exception as erro:  # noqa: BLE001 - fallback deliberado
        log(f"    API comunitária indisponível ({erro}); usando API oficial da Caixa")
        try:
            _baixar_oficial(jogo, existentes, log)
        except Exception as erro_oficial:  # noqa: BLE001
            log(f"    ⚠️  API oficial também falhou: {erro_oficial}")
            if not existentes:
                raise RuntimeError(
                    f"Não foi possível baixar o histórico de {jogo.nome}. "
                    "Verifique sua conexão com a internet."
                ) from erro_oficial
    concursos = sorted(existentes.values(), key=lambda c: c["concurso"])
    salvar_cache(jogo, concursos)
    log(f"    ✅ cache atualizado: {len(concursos)} concursos "
        f"(último: {concursos[-1]['concurso']} em {concursos[-1]['data'] or '?'})")
    return concursos
