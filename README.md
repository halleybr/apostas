# ⚽ ApostaRadar

Site que agrega as **melhores apostas de futebol do dia**, monta uma **acumuladora confiável**
(máx. 3 jogos, odd combinada ≤ 4.00), busca **dicas do dia no YouTube** e **monitora jogos ao
vivo** gerando sinais de gols, escanteios e entradas.

Construído em **Python puro (stdlib) — zero dependências**. Roda em qualquer Python ≥ 3.10.

## Fontes usadas

| Fonte | O que fornece | Status |
|---|---|---|
| [Robobet](https://robobet.app) | API JSON pública: picks com probabilidade/confiança, EV por mercado, oportunidades de escanteios, histórico de acerto (70%+) | ✅ completa |
| [SokkerPro](https://sokkerpro.com) | API JSON pública: jogos do dia, placar ao vivo, escanteios, xG, chutes, posse, odds ao vivo e previsões por mercado | ✅ completa |
| [Windrawwin](https://www.windrawwin.com/predictions/today/) | Previsões 1X2 / over-under / BTTS, forma dos times, estatísticas, odds e a acumuladora diária oficial do site | ✅ completa |
| [PredictZ](https://www.predictz.com/predictions/) | Previsões 1X2 diárias com placar previsto, forma dos times, odds e refs bet365 | ✅ completa |
| [Betrush](https://www.betrush.com/) | Picks de tipsters com odd, casa e tipster (plataforma Betrush) | ✅ completa |
| [TipGol](https://www.tipgol.com/) | Picks de tipsters com odd, casa e tipster (mesma plataforma do Betrush, em espanhol) | ✅ completa |
| [OddsScanner](https://oddsscanner.com/br/futebol) | Palpites de hoje (análises de jogos do dia em pt-BR); o grid de odds exige sessão | ⚠️ parcial |
| [BettingExpert](https://www.bettingexpert.com/tips) | A lista de dicas é renderizada via JavaScript (server actions) — o site entrega links diretos e aviso | ⚠️ parcial |
| [AiScore](https://www.aiscore.com) | API usa protobuf com IDs ofuscados (anti-bot) — o site entrega links diretos de placar/previsões | ⚠️ parcial |
| YouTube | Dicas em vídeo do dia (parse de `ytInitialData`, sem API key) | ✅ |

## Como rodar

```bash
python server.py
# ou
python -X utf8 server.py
```

Abra **http://127.0.0.1:8000** no navegador.

- Porta/host: `PORT` e `HOST` (variáveis de ambiente), padrão `8000` / `127.0.0.1`.
- Opcional: `YOUTUBE_API_KEY=...` para usar a API oficial do YouTube no lugar do parse de busca.

## Endpoints da API

| Endpoint | Descrição |
|---|---|
| `GET /api/overview` | Tudo em uma resposta: previsões + acumuladora + YouTube + ao vivo |
| `GET /api/predictions` | Partidas do dia com seleções e confiabilidade por fonte |
| `GET /api/accumulator` | Acumuladora recomendada (3 variantes) + alternativas + histórico Robobet |
| `GET /api/youtube` | Vídeos de dicas de apostas do dia |
| `GET /api/live` | Jogos ao vivo + sinais (gol, escanteio, ritmo, entradas) |
| `GET /api/moments` | Melhores do momento: jogos ao vivo agitados + dicas de entrada (mais escanteio/gol, BTTS, over) |

Dados são cacheados em memória (previsões ~5 min, YouTube ~20 min, ao vivo ~45 s).

## Como funciona a acumuladora

1. Cada partida recebe **seleções** (ex.: "dupla chance casa/fora", "mais de 2.5 gols")
   coletadas das fontes que opinam sobre ela.
2. Cada seleção ganha um **índice de confiabilidade** que combina:
   - probabilidade média dos modelos (Robobet e SokkerPro);
   - número de fontes concordando (acordo entre Robobet / SokkerPro / Windrawwin / PredictZ / Betrush / TipGol);
   - picks oficiais da Robobet.
3. Todas as combinações de **1 a 3 jogos** com odd entre **1.10 e 4.00** são enumeradas e
   ranqueadas por confiabilidade. São oferecidas 3 variantes:
   - **Mais confiável** — maior confiabilidade;
   - **Equilibrada** — melhor relação confiabilidade × uso da odd;
   - **Maior odd (≤ 4.00)** — odd combinada mais alta ainda confiável.

## Melhores do momento

A aba **⚡ Melhores do Momento** analisa os jogos ao vivo do SokkerPro em tempo real
(intervalo ~60 s) e ranqueia os mais **agitados**: pressão (ataques perigosos), chutes a
gol, escanteios, gols e xG acumulado. Para os jogos em ritmo forte, gera **dicas de
aposta de momento**:

- 🚩 **Mais 1 escanteio até o fim** — ritmo de cantos alto (projeção ≥ 7.5/jogo);
- ⚽ **Mais 1 gol no jogo** — ritmo de gols ou xG restante alto;
- 🤝 **Ambos marcam** — os dois times com xG vivo e finalizações;
- 📈 **Total over 2.5** — jogo aberto com xG restante alto.

Cada dica traz probabilidade heurística e odd sugerida, com o placar, escanteios,
chutes, xG e pressão ao vivo de cada jogo.

A aba também mantém um **placar de Greens & Reds** das dicas de momento: cada dica
emitida é registrada com um snapshot do estado do jogo e, quando a partida termina
(status FT com placar/escanteios finais do SokkerPro), é liquidada como **✅ GREEN**
(acertou) ou **❌ RED** (errou), com taxa de acerto acumulada do dia.

Os **tempos dos jogos são atualizados em tempo real a partir da Robobet** (API
pública): jogos marcados como `finished` são removidos automaticamente das listas e
jogos ao vivo exibem o minuto atual (`time: "86'"`), além do placar ao vivo.

## Sinais ao vivo

Os jogos ao vivo são baseados na **Robobet** (`events/today`, polling ~45 s), que
fornece status, minuto e placar em tempo real; as estatísticas (cantos, chutes, posse,
xG, ataques perigosos) vêm do SokkerPro e são casadas por nome de time quando disponíveis.

- ⚽ **Gol** — quando o placar muda entre atualizações.
- 🚩 **Escanteio** — contagem sobe + ritmo (cantos/jogo projetado).
- 📈 **Over 2.5 no caminho** — projeção de gols por ritmo.
- 🔥 **Ritmo de ataque** — ataques perigosos/min acima de 1.0.
- 🎯 **Entrada ao vivo Robobet** — picks publicados para jogos em andamento.
- 🚩 **Pressão de escanteios** — oportunidade de cantos da Robobet ≥ 70% em jogo ao vivo.

## Estrutura

```
server.py                 servidor HTTP + API
app/fetch.py              fetch com cache, retry, descompressão gzip/deflate
app/htmlparse.py          mini-parser de DOM (stdlib)
app/normalize.py          normalização/fuzzy-match de nomes de times
app/scrapers/             windrawwin, robobet, sokkerpro, predictz, betrush, oddsscanner, bettingexpert, aiscore
app/aggregator.py         unificação das fontes + confiabilidade
app/accumulator.py        montagem da acumuladora (≤3 jogos, odd ≤4.00)
app/youtube.py            busca de dicas no YouTube
app/live.py               monitor ao vivo + sinais
app/moments.py            melhores do momento: análise de jogos ao vivo agitados + dicas de entrada
public/                   frontend (HTML/CSS/JS, pt-BR)
preview.html              preview estático com um snapshot dos dados (abrir direto no navegador)
```

> `preview.html` é um preview estático gerado a partir de um snapshot da API — dá para
> abrir direto no navegador para ver o layout sem rodar o servidor. Para regenerar,
> rode o servidor, chame `/api/overview` e incorpore o JSON em `window.__SNAPSHOT__`
> (o `public/app.js` já suporta esse modo).

## GitHub Pages (versão estática, sem servidor)

O repositório publica o site em **https://halleybr.github.io/apostas** via GitHub
Actions: a cada push na `main` (e 6x por dia) o workflow
`.github/workflows/pages.yml` roda a agregação real (todas as fontes + YouTube +
ao vivo), gera um **snapshot** com `tools/build_static.py` e publica na Pages.

O frontend detecta `window.__SNAPSHOT__` e renderiza direto do snapshot embutido —
funciona 100% estático, sem servidor. Para gerar localmente:

```bash
python tools/build_static.py site
# abre site/index.html no navegador (ou serve a pasta)
```

Requisito: nas configurações do repositório, Pages → Source → **GitHub Actions**.

## ⚠️ Aviso

Este projeto é **apenas informativo**. Apostas envolvem risco financeiro — **18+**.
Jogue com responsabilidade. As previsões são agregadas de fontes públicas, não garantem
resultado, e as odds mudam constantemente (verifique na sua casa de apostas antes de apostar).
