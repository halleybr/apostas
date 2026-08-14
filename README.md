# ⚽ Freebuff Bets

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

Dados são cacheados em memória (previsões ~5 min, YouTube ~20 min, ao vivo ~45 s).

## Como funciona a acumuladora

1. Cada partida recebe **seleções** (ex.: "dupla chance casa/fora", "mais de 2.5 gols")
   coletadas das fontes que opinam sobre ela.
2. Cada seleção ganha um **índice de confiabilidade** que combina:
   - probabilidade média dos modelos (Robobet e SokkerPro);
   - número de fontes concordando (acordo entre Robobet / SokkerPro / Windrawwin);
   - picks oficiais da Robobet.
3. Todas as combinações de **1 a 3 jogos** com odd entre **1.10 e 4.00** são enumeradas e
   ranqueadas por confiabilidade. São oferecidas 3 variantes:
   - **Mais confiável** — maior confiabilidade;
   - **Equilibrada** — melhor relação confiabilidade × uso da odd;
   - **Maior odd (≤ 4.00)** — odd combinada mais alta ainda confiável.

## Sinais ao vivo

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
app/scrapers/             windrawwin, robobet, sokkerpro, bettingexpert, aiscore
app/aggregator.py         unificação das fontes + confiabilidade
app/accumulator.py        montagem da acumuladora (≤3 jogos, odd ≤4.00)
app/youtube.py            busca de dicas no YouTube
app/live.py               monitor ao vivo + sinais
public/                   frontend (HTML/CSS/JS, pt-BR)
preview.html              preview estático com um snapshot dos dados (abrir direto no navegador)
```

> `preview.html` é um preview estático gerado a partir de um snapshot da API — dá para
> abrir direto no navegador para ver o layout sem rodar o servidor. Para regenerar,
> rode o servidor, chame `/api/overview` e incorpore o JSON em `window.__SNAPSHOT__`
> (o `public/app.js` já suporta esse modo).

## ⚠️ Aviso

Este projeto é **apenas informativo**. Apostas envolvem risco financeiro — **18+**.
Jogue com responsabilidade. As previsões são agregadas de fontes públicas, não garantem
resultado, e as odds mudam constantemente (verifique na sua casa de apostas antes de apostar).
