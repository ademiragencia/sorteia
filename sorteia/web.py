"""Interface web do SorteIA — aplicativo WSGI em Python puro.

Roda em qualquer servidor WSGI e no Vercel (entrypoint ``app.py``).

Rotas:
    GET /                → página web do SorteIA
    GET /api/jogos       → lista de jogos suportados
    GET /api/palpite     → ?jogo=megasena&n=3&estrategia=inteligente[&demo=1]
    GET /api/analise     → ?jogo=megasena[&demo=1]
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# Em servidores serverless (Vercel) só /tmp é gravável.
os.environ.setdefault("SORTEIA_DADOS", "/tmp/sorteia-dados")

from . import __version__
from .analise import analisar
from .demo import gerar_historico
from .fontes import (
    API_CAIXA,
    _baixar_comunitaria,
    _get_json,
    _normalizar,
    carregar_cache,
    salvar_cache,
)
from .jogos import JOGOS, obter_jogo
from .palpite import ESTRATEGIAS, gerar

TTL_CACHE = 6 * 60 * 60          # 6 horas
LIMITE_FALLBACK = 400            # concursos recentes no fallback da API oficial
_memoria: dict[str, tuple[float, list[dict]]] = {}


def _historico_oficial_recente(jogo, limite: int = LIMITE_FALLBACK) -> list[dict]:
    """Fallback: baixa os últimos N concursos da API oficial em paralelo."""
    ultimo_bruto = _get_json(API_CAIXA.format(slug=jogo.slug), timeout=20)
    ultimo = _normalizar(ultimo_bruto)
    if not ultimo:
        raise ValueError("API oficial não retornou o último concurso")
    final = ultimo["concurso"]
    url_base = API_CAIXA.format(slug=jogo.slug)

    def baixar(n: int) -> dict | None:
        try:
            return _normalizar(_get_json(f"{url_base}/{n}", timeout=15))
        except Exception:  # noqa: BLE001 - concurso individual pode falhar
            return None

    numeros = range(max(1, final - limite + 1), final)
    with ThreadPoolExecutor(max_workers=12) as executor:
        registros = [r for r in executor.map(baixar, numeros) if r]
    registros.append(ultimo)
    if len(registros) < 10:
        raise ValueError("poucos concursos obtidos da API oficial")
    return sorted(registros, key=lambda c: c["concurso"])


def _historico(jogo, usar_demo: bool) -> list[dict]:
    if usar_demo:
        return gerar_historico(jogo)
    agora = time.time()
    em_memoria = _memoria.get(jogo.slug)
    if em_memoria and agora - em_memoria[0] < TTL_CACHE:
        return em_memoria[1]
    concursos = carregar_cache(jogo)
    if not concursos or agora - _memoria.get(jogo.slug, (0,))[0] > TTL_CACHE:
        try:
            concursos = _baixar_comunitaria(jogo)
        except Exception:  # noqa: BLE001 - fallback deliberado
            if not concursos:  # cache em disco vazio: tenta a API oficial
                concursos = _historico_oficial_recente(jogo)
        try:
            salvar_cache(jogo, concursos)
        except OSError:
            pass  # disco somente leitura: segue só com a memória
    _memoria[jogo.slug] = (agora, concursos)
    return concursos


def _json_resposta(start_response, corpo: dict, status: str = "200 OK"):
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(dados))),
        ("Cache-Control", "no-store"),
    ])
    return [dados]


def _api_jogos() -> dict:
    return {
        "jogos": [
            {
                "slug": j.slug,
                "nome": j.nome,
                "emoji": j.emoji,
                "descricao": (
                    f"{j.colunas} colunas de 0 a 9" if j.colunas
                    else f"{j.marcados} números de {j.minimo} a {j.maximo}"
                    + (f" + {j.trevos} trevos" if j.trevos else "")
                    + (" + Mês de Sorte" if j.tem_mes else "")
                ),
            }
            for j in JOGOS.values()
        ],
        "estrategias": list(ESTRATEGIAS),
        "versao": __version__,
    }


def _api_palpite(parametros: dict) -> dict:
    jogo = obter_jogo(parametros.get("jogo", ["megasena"])[0])
    quantidade = max(1, min(int(parametros.get("n", ["3"])[0]), 20))
    estrategia = parametros.get("estrategia", ["inteligente"])[0]
    usar_demo = parametros.get("demo", ["0"])[0] == "1"
    if estrategia not in ESTRATEGIAS:
        raise ValueError(f"estratégia inválida: {estrategia}")
    historico = _historico(jogo, usar_demo)
    stats = analisar(jogo, historico)
    palpites = gerar(stats, quantidade=quantidade, estrategia=estrategia)
    ultimo = historico[-1]
    return {
        "jogo": jogo.slug,
        "nome": jogo.nome,
        "emoji": jogo.emoji,
        "estrategia": estrategia,
        "demo": usar_demo,
        "base_concursos": stats.total_concursos,
        "ultimo_concurso": {
            "numero": ultimo["concurso"],
            "data": ultimo.get("data", ""),
            "dezenas": ultimo["sorteios"][0],
        },
        "palpites": [
            {
                "numeros": p.numeros,
                "trevos": p.trevos,
                "mes": p.mes,
                "afinidade": round(p.pontuacao, 3),
            }
            for p in palpites
        ],
    }


def _api_analise(parametros: dict) -> dict:
    jogo = obter_jogo(parametros.get("jogo", ["megasena"])[0])
    usar_demo = parametros.get("demo", ["0"])[0] == "1"
    stats = analisar(jogo, _historico(jogo, usar_demo))
    p10, mediana, p90 = stats.faixa_de_soma()
    return {
        "jogo": jogo.slug,
        "nome": jogo.nome,
        "demo": usar_demo,
        "total_concursos": stats.total_concursos,
        "mais_sorteados": stats.mais_quentes(10),
        "menos_sorteados": stats.mais_frios(10),
        "mais_atrasados": stats.mais_atrasados(10),
        "soma_tipica": {"p10": p10, "mediana": mediana, "p90": p90},
        "impares_tipico": stats.impares_tipico(),
    }


def app(environ, start_response):
    caminho = environ.get("PATH_INFO", "/") or "/"
    parametros = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
    try:
        if caminho == "/":
            dados = PAGINA.encode("utf-8")
            start_response("200 OK", [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(dados))),
            ])
            return [dados]
        if caminho == "/api/jogos":
            return _json_resposta(start_response, _api_jogos())
        if caminho == "/api/palpite":
            return _json_resposta(start_response, _api_palpite(parametros))
        if caminho == "/api/analise":
            return _json_resposta(start_response, _api_analise(parametros))
        return _json_resposta(start_response, {"erro": "rota não encontrada"},
                              "404 Not Found")
    except (KeyError, ValueError) as erro:
        return _json_resposta(start_response, {"erro": str(erro)}, "400 Bad Request")
    except Exception as erro:  # noqa: BLE001 - resposta amigável para falha de rede
        return _json_resposta(
            start_response,
            {"erro": "Não consegui baixar o histórico agora. Tente novamente em "
                     f"instantes ou use o modo demo. ({erro})"},
            "503 Service Unavailable",
        )


PAGINA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SorteIA 🍀 — palpites inteligentes das Loterias Caixa</title>
<meta name="description" content="SorteIA analisa o histórico completo das Loterias Caixa e gera palpites estatísticos para Mega-Sena, Lotofácil, Quina e mais.">
<style>
:root{--fundo:#0e1420;--carta:#171f2f;--borda:#26324a;--texto:#e8edf6;--suave:#9aa7bd;--verde:#28c76f;--verde2:#1f9d57;--ouro:#f5c542}
*{box-sizing:border-box;margin:0;padding:0}
body{background:linear-gradient(160deg,#0e1420 0%,#101a2e 100%);color:var(--texto);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;min-height:100vh}
.container{max-width:880px;margin:0 auto;padding:32px 20px 64px}
header{text-align:center;margin-bottom:28px}
h1{font-size:2.4rem;letter-spacing:.5px}
h1 span{color:var(--verde)}
.sub{color:var(--suave);margin-top:6px}
.painel{background:var(--carta);border:1px solid var(--borda);border-radius:16px;padding:20px;margin-bottom:20px}
label{display:block;color:var(--suave);font-size:.85rem;margin:12px 0 6px}
select,input[type=number]{width:100%;background:#0f1626;color:var(--texto);border:1px solid var(--borda);border-radius:10px;padding:10px 12px;font-size:1rem}
.linha{display:grid;grid-template-columns:2fr 2fr 1fr;gap:14px}
@media(max-width:640px){.linha{grid-template-columns:1fr}}
button{width:100%;margin-top:18px;background:linear-gradient(135deg,var(--verde),var(--verde2));color:#06130b;font-weight:700;font-size:1.1rem;border:0;border-radius:12px;padding:14px;cursor:pointer;transition:transform .1s}
button:hover{transform:translateY(-1px)}
button:disabled{opacity:.55;cursor:wait}
.demo{display:flex;align-items:center;gap:8px;margin-top:14px;color:var(--suave);font-size:.85rem}
.demo input{width:auto}
.jogo-cabecalho{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.jogo-cabecalho small{color:var(--suave)}
.palpite{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:12px;border-bottom:1px dashed var(--borda)}
.palpite:last-child{border-bottom:0}
.rotulo{color:var(--suave);font-size:.8rem;min-width:64px}
.bola{width:42px;height:42px;border-radius:50%;background:radial-gradient(circle at 30% 28%,#ffffff22,#0000),linear-gradient(160deg,var(--verde),var(--verde2));display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.02rem;color:#04120a;box-shadow:0 3px 8px #0006}
.bola.trevo{background:linear-gradient(160deg,var(--ouro),#c99b16)}
.extra{color:var(--ouro);font-size:.9rem;margin-left:4px}
.afinidade{margin-left:auto;color:var(--suave);font-size:.78rem}
.erro{background:#3a1d24;border:1px solid #7c3242;color:#ffb9c5;border-radius:12px;padding:14px;margin-top:16px}
.aviso{color:var(--suave);font-size:.82rem;line-height:1.5;text-align:center;margin-top:26px}
.ultimo{color:var(--suave);font-size:.85rem;margin-top:10px}
footer{text-align:center;color:var(--suave);font-size:.8rem;margin-top:34px}
footer a{color:var(--verde)}
.girando{display:inline-block;animation:girar 1s linear infinite}
@keyframes girar{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🍀 Sorte<span>IA</span></h1>
    <p class="sub">Palpites inteligentes com base no histórico completo das Loterias Caixa</p>
  </header>

  <div class="painel">
    <div class="linha">
      <div>
        <label for="jogo">Jogo</label>
        <select id="jogo"></select>
      </div>
      <div>
        <label for="estrategia">Estratégia</label>
        <select id="estrategia"></select>
      </div>
      <div>
        <label for="quantidade">Jogos</label>
        <input id="quantidade" type="number" min="1" max="20" value="3">
      </div>
    </div>
    <button id="gerar">🎰 Gerar palpites</button>
    <div class="demo">
      <input type="checkbox" id="demo">
      <label for="demo" style="margin:0">modo demo (dados sintéticos, sem baixar histórico)</label>
    </div>
  </div>

  <div id="resultado"></div>

  <p class="aviso">⚠️ Todo sorteio da Caixa é aleatório e independente do passado. O SorteIA gera
  jogos estatisticamente bem distribuídos a partir do histórico real, mas nenhum sistema aumenta
  a chance real de ganhar. Jogue com responsabilidade.</p>

  <footer>SorteIA — código aberto em <a href="https://github.com/ademiragencia/sorteia">github.com/ademiragencia/sorteia</a></footer>
</div>

<script>
const rotulos={inteligente:"🧠 Inteligente (recomendada)",quentes:"🔥 Números quentes",atrasados:"⏳ Mais atrasados",equilibrado:"⚖️ Equilibrado",surpresa:"🎲 Surpresa"};
const elJogo=document.getElementById("jogo"),elEstrategia=document.getElementById("estrategia"),
      elQtd=document.getElementById("quantidade"),elDemo=document.getElementById("demo"),
      elBotao=document.getElementById("gerar"),elResultado=document.getElementById("resultado");

async function carregarJogos(){
  const r=await fetch("/api/jogos");const d=await r.json();
  elJogo.innerHTML=d.jogos.map(j=>`<option value="${j.slug}">${j.emoji} ${j.nome} — ${j.descricao}</option>`).join("");
  elEstrategia.innerHTML=d.estrategias.map(e=>`<option value="${e}">${rotulos[e]||e}</option>`).join("");
}
carregarJogos();

function bolas(nums,ehColuna){return nums.map(n=>`<span class="bola">${ehColuna?n:String(n).padStart(2,"0")}</span>`).join("")}

elBotao.addEventListener("click",async()=>{
  elBotao.disabled=true;
  elBotao.innerHTML='<span class="girando">🎰</span> Analisando histórico...';
  elResultado.innerHTML="";
  try{
    const p=new URLSearchParams({jogo:elJogo.value,n:elQtd.value,estrategia:elEstrategia.value});
    if(elDemo.checked)p.set("demo","1");
    const r=await fetch("/api/palpite?"+p);const d=await r.json();
    if(!r.ok)throw new Error(d.erro||"erro inesperado");
    const ehColuna=d.jogo==="supersete";
    let html=`<div class="painel"><div class="jogo-cabecalho"><strong>${d.emoji} ${d.nome}</strong>
      <small>${rotulos[d.estrategia]||d.estrategia} · base: ${d.base_concursos} concursos${d.demo?" (demo)":""}</small></div>`;
    d.palpites.forEach((pal,i)=>{
      html+=`<div class="palpite"><span class="rotulo">Jogo ${i+1}</span>${bolas(pal.numeros,ehColuna)}`;
      if(pal.trevos&&pal.trevos.length)html+=`<span class="extra">🍀</span>`+pal.trevos.map(t=>`<span class="bola trevo">${t}</span>`).join("");
      if(pal.mes)html+=`<span class="extra">📅 ${pal.mes}</span>`;
      if(pal.afinidade)html+=`<span class="afinidade">afinidade ${(pal.afinidade*100).toFixed(0)}%</span>`;
      html+=`</div>`;
    });
    html+=`<p class="ultimo">Último concurso analisado: nº ${d.ultimo_concurso.numero}`+
      (d.ultimo_concurso.data?` (${d.ultimo_concurso.data})`:"")+
      ` — ${d.ultimo_concurso.dezenas.map(n=>String(n).padStart(2,"0")).join(" ")}</p></div>`;
    elResultado.innerHTML=html;
  }catch(erro){
    elResultado.innerHTML=`<div class="erro">😕 ${erro.message}<br><small>Dica: marque o "modo demo" para testar sem depender das APIs de resultados.</small></div>`;
  }finally{
    elBotao.disabled=false;elBotao.innerHTML="🎰 Gerar palpites";
  }
});
</script>
</body>
</html>
"""
