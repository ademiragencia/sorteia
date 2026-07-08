# 🍀 SorteIA

**Sorteador palpiteiro inteligente das Loterias Caixa** — analisa o histórico
completo de todos os concursos já realizados e gera palpites estatisticamente
bem distribuídos para os 9 principais jogos da Caixa.

```
   _____            __       ________
  / ___/____  _____/ /____  /  _/   |
  \__ \/ __ \/ ___/ __/ _ \ / // /| |
 ___/ / /_/ / /  / /_/  __// // ___ |
/____/\____/_/   \__/\___/___/_/  |_|
```

> ⚠️ **Aviso honesto:** todo sorteio da Caixa é aleatório e independente do
> passado. Nenhum sistema — este incluso — aumenta a probabilidade real de
> ganhar. O SorteIA gera jogos "típicos" segundo o histórico real e evita
> combinações desequilibradas, mas a sorte continua sendo só sua.
> **Jogue com responsabilidade.**

## 🎰 Jogos suportados

| Jogo | Aposta | Extras |
|---|---|---|
| 💚 Mega-Sena | 6 números de 1–60 | |
| 💜 Lotofácil | 15 números de 1–25 | |
| 💙 Quina | 5 números de 1–80 | |
| 🧡 Lotomania | 50 números de 0–99 | |
| ❤️ Dupla Sena | 6 números de 1–50 | 2 sorteios por concurso |
| 💛 Timemania | 10 números de 1–80 | |
| 🍀 Dia de Sorte | 7 números de 1–31 | + Mês de Sorte |
| 🎰 Super Sete | 7 colunas de 0–9 | análise por coluna |
| 💰 +Milionária | 6 números de 1–50 | + 2 trevos |

## 🚀 Como usar

Requer apenas **Python 3.10+** — sem nenhuma dependência externa.

```bash
git clone https://github.com/ademiragencia/sorteia.git
cd sorteia

# 1. Baixa o histórico completo de todos os jogos (APIs públicas da Caixa)
python3 -m sorteia atualizar

# 2. Gera 3 palpites inteligentes para a Mega-Sena
python3 -m sorteia palpite megasena

# Mais exemplos:
python3 -m sorteia palpite lotofacil -n 5 -e quentes   # 5 jogos, números quentes
python3 -m sorteia palpite quina -e atrasados          # números mais atrasados
python3 -m sorteia analise megasena                    # estatísticas do histórico
python3 -m sorteia jogos                               # lista os jogos
```

Sem internet? Experimente o modo demonstração:

```bash
python3 -m sorteia palpite megasena --demo
```

## 🧠 Estratégias

| Estratégia | Como funciona |
|---|---|
| `inteligente` *(padrão)* | Gera centenas de candidatos ponderados e pontua cada um por **afinidade de pares** (números que historicamente saem juntos), **soma plausível** (faixa central do histórico), **proporção de ímpares** típica e **espalhamento pelo volante**. Devolve os melhores. |
| `quentes` | Favorece os números mais sorteados de toda a história do jogo. |
| `atrasados` | Favorece os números há mais tempo sem sair. |
| `equilibrado` | Mistura frequência histórica (45%), frequência recente (30%) e atraso (25%). |
| `surpresa` | Sorteio uniforme, sem viés — a linha de base honesta. |

Use `--semente 123` para gerar palpites reproduzíveis.

## 📊 Dados

Os históricos são baixados das APIs públicas de resultados e ficam em cache
na pasta `dados/`, atualizados de forma incremental:

1. **API comunitária** ([loteriascaixa-api](https://loteriascaixa-api.herokuapp.com)) — histórico completo em uma requisição;
2. **API oficial do Portal de Loterias da Caixa** — usada como fallback, concurso a concurso.

## 🧪 Testes

```bash
python3 -m unittest discover testes
```

## 📄 Licença

[MIT](LICENSE) — feito com 🍀 para quem gosta de jogar com inteligência.
