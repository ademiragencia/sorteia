"""Interface web do SorteIA — aplicativo WSGI em Python puro (PWA instalável).

Roda em qualquer servidor WSGI e no Vercel (entrypoint ``app.py``).

Rotas:
    GET /                     → página web do SorteIA
    GET /api/jogos            → lista de jogos suportados
    GET /api/palpite          → ?jogo=megasena&n=3&estrategia=inteligente[&demo=1]
    GET /api/analise          → ?jogo=megasena[&demo=1]
    GET /manifest.webmanifest → manifesto do PWA
    GET /sw.js                → service worker
    GET /icone-{180,192,512}.png → ícones gerados em tempo de execução
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# Em servidores serverless (Vercel) só /tmp é gravável.
os.environ.setdefault("SORTEIA_DADOS", "/tmp/sorteia-dados")

from . import __version__, icone
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


def _resposta(start_response, dados: bytes, tipo: str, status: str = "200 OK",
              cache: str = "no-store"):
    start_response(status, [
        ("Content-Type", tipo),
        ("Content-Length", str(len(dados))),
        ("Cache-Control", cache),
    ])
    return [dados]


def _json_resposta(start_response, corpo: dict, status: str = "200 OK"):
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    return _resposta(start_response, dados,
                     "application/json; charset=utf-8", status)


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
            return _resposta(start_response, PAGINA.encode("utf-8"),
                             "text/html; charset=utf-8",
                             cache="public, max-age=0, must-revalidate")
        if caminho == "/api/jogos":
            return _json_resposta(start_response, _api_jogos())
        if caminho == "/api/palpite":
            return _json_resposta(start_response, _api_palpite(parametros))
        if caminho == "/api/analise":
            return _json_resposta(start_response, _api_analise(parametros))
        if caminho == "/manifest.webmanifest":
            return _resposta(start_response, MANIFESTO.encode("utf-8"),
                             "application/manifest+json; charset=utf-8",
                             cache="public, max-age=3600")
        if caminho == "/sw.js":
            return _resposta(start_response, SERVICE_WORKER.encode("utf-8"),
                             "application/javascript; charset=utf-8",
                             cache="public, max-age=0, must-revalidate")
        if caminho in ("/icone-180.png", "/icone-192.png", "/icone-512.png"):
            tamanho = int(caminho.split("-")[1].split(".")[0])
            return _resposta(start_response, icone.gerar(tamanho), "image/png",
                             cache="public, max-age=86400")
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


MANIFESTO = json.dumps({
    "name": "SorteIA — Palpites das Loterias Caixa",
    "short_name": "SorteIA",
    "description": "Palpites inteligentes com base no histórico completo das Loterias Caixa.",
    "lang": "pt-BR",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#0b1020",
    "theme_color": "#0b1020",
    "icons": [
        {"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}, ensure_ascii=False)


SERVICE_WORKER = """const CACHE = "sorteia-v2";
const SHELL = ["/", "/manifest.webmanifest", "/icone-192.png", "/icone-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) =>
      Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copia = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copia));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
"""


PAGINA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>SorteIA 🍀 — palpites inteligentes das Loterias Caixa</title>
<meta name="description" content="Palpites inteligentes para Mega-Sena, Lotofácil, Quina e todos os jogos da Caixa, com base no histórico completo dos sorteios.">
<meta name="theme-color" content="#0b1020">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" type="image/png" sizes="192x192" href="/icone-192.png">
<link rel="apple-touch-icon" href="/icone-180.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="SorteIA">
<style>
:root{
  --fundo:#0b1020;--carta:#141c31;--carta2:#1a2440;--borda:#273455;
  --texto:#eef2fb;--suave:#95a3c2;--verde:#2ee383;--verde2:#14a659;
  --ouro:#ffcf4d;--sombra:0 18px 44px rgba(0,0,0,.45)
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html{scroll-behavior:smooth}
body{
  color:var(--texto);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  min-height:100vh;background:var(--fundo);overflow-x:hidden;
  padding-bottom:env(safe-area-inset-bottom)
}
body::before,body::after{
  content:"";position:fixed;z-index:-1;border-radius:50%;filter:blur(90px);opacity:.35;pointer-events:none
}
body::before{width:52vmax;height:52vmax;top:-22vmax;left:-14vmax;background:radial-gradient(circle,#1a7f4e,transparent 65%)}
body::after{width:46vmax;height:46vmax;bottom:-20vmax;right:-12vmax;background:radial-gradient(circle,#173a7a,transparent 65%)}
.container{max-width:760px;margin:0 auto;padding:28px 16px 56px}

header{text-align:center;margin-bottom:22px}
.logo{
  width:76px;height:76px;margin:0 auto 12px;border-radius:24px;
  background:linear-gradient(160deg,var(--verde),var(--verde2));
  display:flex;align-items:center;justify-content:center;font-size:2.4rem;
  box-shadow:0 10px 28px rgba(46,227,131,.35);animation:flutuar 4s ease-in-out infinite
}
@keyframes flutuar{50%{transform:translateY(-6px)}}
h1{font-size:2.5rem;letter-spacing:.5px;font-weight:800}
h1 span{background:linear-gradient(90deg,var(--verde),#7df0b4);-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--suave);margin-top:6px;font-size:.98rem}

.instalar{
  display:none;margin:14px auto 0;padding:10px 22px;border-radius:999px;border:1px solid var(--verde);
  background:rgba(46,227,131,.12);color:var(--verde);font-weight:700;font-size:.92rem;cursor:pointer
}
.instalar.visivel{display:block;animation:pulsar 2.4s ease-in-out infinite}
@keyframes pulsar{50%{box-shadow:0 0 0 10px rgba(46,227,131,0)}0%{box-shadow:0 0 0 0 rgba(46,227,131,.35)}}

.painel{
  background:linear-gradient(175deg,var(--carta),var(--carta2));
  border:1px solid var(--borda);border-radius:22px;padding:20px;margin-bottom:18px;box-shadow:var(--sombra)
}
.titulo{color:var(--suave);font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:1.4px;margin:4px 0 10px}

.grade-jogos{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.chip-jogo{
  border:1px solid var(--borda);background:#0f1730;color:var(--texto);border-radius:14px;
  padding:10px 6px;cursor:pointer;text-align:center;transition:all .15s;font-size:.82rem;line-height:1.35;
  min-width:0;overflow-wrap:break-word
}
.chip-jogo em{display:block;font-style:normal;font-size:1.35rem;margin-bottom:2px}
.chip-jogo small{display:block;color:var(--suave);font-size:.62rem;margin-top:1px}
.chip-jogo.ativo{border-color:var(--verde);background:rgba(46,227,131,.13);box-shadow:0 0 0 1px var(--verde),0 6px 18px rgba(46,227,131,.18);transform:translateY(-1px)}

.pilulas{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:4px}
.pilula{
  border:1px solid var(--borda);background:#0f1730;color:var(--suave);border-radius:999px;
  padding:8px 14px;font-size:.82rem;cursor:pointer;transition:all .15s;font-weight:600
}
.pilula.ativo{border-color:var(--verde);color:var(--verde);background:rgba(46,227,131,.12)}

.rodape-controles{display:flex;align-items:center;gap:12px;margin-top:16px;flex-wrap:wrap}
.stepper{display:flex;align-items:center;gap:0;border:1px solid var(--borda);border-radius:14px;overflow:hidden;background:#0f1730}
.stepper button{width:44px;height:48px;border:0;background:transparent;color:var(--verde);font-size:1.4rem;font-weight:800;cursor:pointer}
.stepper span{min-width:56px;text-align:center;font-weight:800;font-size:1.1rem}
.stepper small{display:block;color:var(--suave);font-weight:400;font-size:.6rem;text-transform:uppercase;letter-spacing:1px}
.gerar{
  flex:1 1 160px;min-width:0;height:52px;border:0;border-radius:16px;cursor:pointer;
  background:linear-gradient(135deg,var(--verde),var(--verde2));color:#04120a;
  font-weight:800;font-size:1.08rem;box-shadow:0 10px 26px rgba(46,227,131,.3);transition:transform .12s
}
.gerar:active{transform:scale(.98)}
.gerar:disabled{opacity:.6;cursor:wait}
.demo{display:flex;align-items:center;gap:8px;margin-top:14px;color:var(--suave);font-size:.8rem}
.demo input{accent-color:var(--verde);width:16px;height:16px}

.cabecalho-resultado{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.cabecalho-resultado small{color:var(--suave)}
.palpite{display:flex;flex-wrap:wrap;align-items:center;gap:7px;padding:12px 4px;border-bottom:1px dashed var(--borda)}
.palpite:last-of-type{border-bottom:0}
.rotulo{color:var(--suave);font-size:.72rem;min-width:52px;font-weight:700;text-transform:uppercase;letter-spacing:1px}
.bola{
  width:44px;height:44px;border-radius:50%;
  background:radial-gradient(circle at 30% 26%,rgba(255,255,255,.35),transparent 42%),linear-gradient(160deg,var(--verde),var(--verde2));
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.04rem;color:#04120a;
  box-shadow:0 5px 12px rgba(0,0,0,.45);animation:pop .38s cubic-bezier(.34,1.56,.64,1) backwards
}
@keyframes pop{from{transform:scale(.2) rotate(-18deg);opacity:0}}
.bola.trevo{background:radial-gradient(circle at 30% 26%,rgba(255,255,255,.4),transparent 42%),linear-gradient(160deg,var(--ouro),#d19a12)}
.extra{color:var(--ouro);font-size:.88rem;font-weight:700}
.afinidade{margin-left:auto;color:var(--suave);font-size:.72rem}
.ultimo{color:var(--suave);font-size:.82rem;margin-top:12px;line-height:1.5}
.erro{background:#381d27;border:1px solid #7c3242;color:#ffb9c5;border-radius:16px;padding:14px;margin-top:4px;font-size:.92rem;line-height:1.5}

.aviso{color:var(--suave);font-size:.78rem;line-height:1.6;text-align:center;margin-top:24px;padding:0 10px}
footer{text-align:center;color:#5f6d8c;font-size:.75rem;margin-top:26px}
.girando{display:inline-block;animation:girar 1s linear infinite}
@keyframes girar{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">🍀</div>
    <h1>Sorte<span>IA</span></h1>
    <p class="sub">Palpites inteligentes com base no histórico completo das Loterias Caixa</p>
    <button id="instalar" class="instalar">📲 Instalar o app no celular</button>
  </header>

  <div class="painel">
    <p class="titulo">1 · Escolha o jogo</p>
    <div id="jogos" class="grade-jogos"></div>
  </div>

  <div class="painel">
    <p class="titulo">2 · Estratégia</p>
    <div id="estrategias" class="pilulas"></div>
    <div class="rodape-controles">
      <div class="stepper">
        <button id="menos" aria-label="menos jogos">−</button>
        <span><span id="qtd">3</span><small>jogos</small></span>
        <button id="mais" aria-label="mais jogos">+</button>
      </div>
      <button id="gerar" class="gerar">🎰 Gerar palpites</button>
    </div>
    <label class="demo"><input type="checkbox" id="demo"> modo demo (dados sintéticos, sem baixar histórico)</label>
  </div>

  <div id="resultado"></div>

  <p class="aviso">⚠️ Todo sorteio da Caixa é aleatório e independente do passado. O SorteIA gera
  jogos estatisticamente bem distribuídos a partir do histórico real, mas nenhum sistema aumenta
  a chance real de ganhar. Jogue com responsabilidade.</p>

  <footer>SorteIA · feito com 🍀 e estatística</footer>
</div>

<script>
const rotulos={inteligente:"🧠 Inteligente",quentes:"🔥 Quentes",atrasados:"⏳ Atrasados",equilibrado:"⚖️ Equilibrado",surpresa:"🎲 Surpresa"};
let jogoAtivo="megasena",estrategiaAtiva="inteligente",quantidade=3;
const $=id=>document.getElementById(id);

async function carregar(){
  try{
    const d=await (await fetch("/api/jogos")).json();
    $("jogos").innerHTML=d.jogos.map(j=>
      `<button class="chip-jogo${j.slug===jogoAtivo?" ativo":""}" data-slug="${j.slug}">
         <em>${j.emoji}</em>${j.nome}<small>${j.descricao}</small></button>`).join("");
    $("estrategias").innerHTML=d.estrategias.map(e=>
      `<button class="pilula${e===estrategiaAtiva?" ativo":""}" data-e="${e}">${rotulos[e]||e}</button>`).join("");
    document.querySelectorAll(".chip-jogo").forEach(b=>b.onclick=()=>{
      jogoAtivo=b.dataset.slug;
      document.querySelectorAll(".chip-jogo").forEach(x=>x.classList.toggle("ativo",x===b));
    });
    document.querySelectorAll(".pilula").forEach(b=>b.onclick=()=>{
      estrategiaAtiva=b.dataset.e;
      document.querySelectorAll(".pilula").forEach(x=>x.classList.toggle("ativo",x===b));
    });
  }catch(e){
    $("resultado").innerHTML=`<div class="erro">😕 Não consegui carregar os jogos. Verifique a conexão e recarregue.</div>`;
  }
}
carregar();

$("menos").onclick=()=>{quantidade=Math.max(1,quantidade-1);$("qtd").textContent=quantidade};
$("mais").onclick=()=>{quantidade=Math.min(20,quantidade+1);$("qtd").textContent=quantidade};

function bola(n,i,trevo){
  const texto=jogoAtivo==="supersete"?n:String(n).padStart(2,"0");
  return `<span class="bola${trevo?" trevo":""}" style="animation-delay:${i*45}ms">${texto}</span>`;
}

$("gerar").onclick=async()=>{
  const botao=$("gerar");
  botao.disabled=true;botao.innerHTML='<span class="girando">🎰</span> Analisando histórico...';
  $("resultado").innerHTML="";
  try{
    const p=new URLSearchParams({jogo:jogoAtivo,n:quantidade,estrategia:estrategiaAtiva});
    if($("demo").checked)p.set("demo","1");
    const r=await fetch("/api/palpite?"+p);const d=await r.json();
    if(!r.ok)throw new Error(d.erro||"erro inesperado");
    let html=`<div class="painel"><div class="cabecalho-resultado"><strong>${d.emoji} ${d.nome}</strong>
      <small>${rotulos[d.estrategia]||d.estrategia} · ${d.base_concursos} concursos analisados${d.demo?" (demo)":""}</small></div>`;
    let seq=0;
    d.palpites.forEach((pal,i)=>{
      html+=`<div class="palpite"><span class="rotulo">Jogo ${i+1}</span>`;
      html+=pal.numeros.map(n=>bola(n,seq++,false)).join("");
      if(pal.trevos&&pal.trevos.length)html+=`<span class="extra">🍀</span>`+pal.trevos.map(t=>bola(t,seq++,true)).join("");
      if(pal.mes)html+=`<span class="extra">📅 ${pal.mes}</span>`;
      if(pal.afinidade)html+=`<span class="afinidade">afinidade ${(pal.afinidade*100).toFixed(0)}%</span>`;
      html+=`</div>`;
    });
    html+=`<p class="ultimo">Último concurso analisado: nº ${d.ultimo_concurso.numero}`+
      (d.ultimo_concurso.data?` (${d.ultimo_concurso.data})`:"")+
      ` — ${d.ultimo_concurso.dezenas.map(n=>String(n).padStart(2,"0")).join(" ")}</p></div>`;
    $("resultado").innerHTML=html;
    $("resultado").scrollIntoView({behavior:"smooth",block:"nearest"});
  }catch(erro){
    $("resultado").innerHTML=`<div class="erro">😕 ${erro.message}<br><small>Dica: marque o "modo demo" para testar sem depender das APIs de resultados.</small></div>`;
  }finally{
    botao.disabled=false;botao.innerHTML="🎰 Gerar palpites";
  }
};

// PWA: service worker + botão de instalação
if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js");
let eventoInstalar=null;
window.addEventListener("beforeinstallprompt",(e)=>{
  e.preventDefault();eventoInstalar=e;$("instalar").classList.add("visivel");
});
$("instalar").onclick=async()=>{
  if(!eventoInstalar)return;
  eventoInstalar.prompt();
  await eventoInstalar.userChoice;
  eventoInstalar=null;$("instalar").classList.remove("visivel");
};
window.addEventListener("appinstalled",()=>$("instalar").classList.remove("visivel"));
</script>
</body>
</html>
"""
