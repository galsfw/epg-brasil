# EPG automático + M3U de Filmes/Séries — IPTV Brasil 2026

Este projeto gera, **automaticamente e periodicamente**, dois arquivos a
partir da playlist pública [Ramys/Iptv-Brasil-2026 — `CanaisBR06.m3u8`](https://github.com/Ramys/Iptv-Brasil-2026/blob/master/CanaisBR06.m3u8):

| Arquivo | O que é | Uso |
|---|---|---|
| `output/epg.xml` (e `output/epg.xml.gz`) | Guia de programação (XMLTV) só dos **canais de TV ao vivo** | Adicionar como fonte de EPG no TiviMate/outro app |
| `output/filmes_series.m3u8` | Playlist M3U separada só com **Filmes e Séries** (VOD) | Adicionar como uma **segunda lista** no TiviMate |

Ambos são regenerados sozinhos por uma GitHub Action (cron), então depois
de configurado uma vez você nunca mais precisa mexer manualmente.

## O que foi removido / separado

- **ASMR / "Dormir e Relaxar"** (ASMR, som de chuva, som de natureza,
  lofi, música para bebê etc.): excluído do EPG — são loops sem grade de
  programação real.
- **Copa do Mundo 2026**: excluído do EPG — são canais/eventos temporários
  sem `tvg-id` e sem guia de programação.
- **Filmes e Séries** (todos os grupos `Filmes | *`, `Series | *`,
  `Doramas`, `Novelas`, `Novelas Turcas`, `Mini Series`): não entram mais
  no EPG (nunca tiveram grade — são VOD) e agora saem em um **M3U próprio**
  (`filmes_series.m3u8`), atualizado junto com o EPG.

O `epg.xml` final contém somente os grupos que começam com `Canais |`
(TV ao vivo de verdade: Globo, SBT, RecordTV, Band, SporTV, ESPN, HBO,
Telecine, Premiere, canais Abertos/Estaduais, etc.), com a grade real
casada a partir de fontes públicas de EPG.

## Como funciona o casamento de canais (M3U ⇄ EPG)

A playlist usa `tvg-id`s próprios (ex.: `globo.br`, `sportv.br`,
`recordtvsãopaulo.br`) que raramente batem com o `id` usado pelas fontes
públicas de EPG. O script `scripts/generate_epg.py`:

1. Baixa a playlist e filtra os canais "ao vivo";
2. Baixa várias fontes de EPG (XMLTV) gratuitas para o Brasil:
   - `epgshare01.online` (BR1 e BR2)
   - `limaalef/BrazilTVEPG` (`globo.xml`, `epg.xml`, `claro.xml`,
     `vivoplay.xml`, `maissbt.xml`)
3. Tenta casar cada canal, nesta ordem:
   1. **ID exato** (normalizado, sem acento/maiúsculas);
   2. **Nome exato** (nome do canal normalizado);
   3. **Fuzzy match** de nome (similaridade ≥ 90%);
   4. **Fallback por rede nacional**: afiliadas regionais de Globo, SBT,
      RecordTV, Band e RedeTV! que não têm grade própria publicada
      herdam a grade do canal "mãe" nacional (ex.: uma afiliada da Globo
      sem EPG específico usa a grade da Globo São Paulo).
4. Gera um `epg.xml` cujo `<channel id="...">` é **idêntico ao `tvg-id`**
   da playlist — não é preciso reatribuir EPG manualmente no player.

No momento da última execução local, cerca de **87% dos canais de TV
aberta/afiliadas regionais (`.br`)** e a maioria dos canais a cabo/streaming
ficam com grade real. Canais muito de nicho, sem nenhuma fonte pública de
dados, ficam sem `<channel>` no XML (o player simplesmente mostra "sem
informação" para eles, sem quebrar o restante do guia).

## Arquivos do projeto

```
epg-br/
├── scripts/
│   ├── normalize.py          # normalização de nomes/ids para o matching
│   ├── generate_epg.py        # gera output/epg.xml e epg.xml.gz
│   └── generate_vod_m3u.py    # gera output/filmes_series.m3u8
├── output/
│   ├── epg.xml
│   ├── epg.xml.gz
│   ├── filmes_series.m3u8
│   ├── last_update.txt
│   └── last_update_vod.txt
└── .github/workflows/update-epg.yml   # roda tudo sozinho, de 6 em 6h
```

## Aviso

Este projeto apenas organiza e casa metadados de EPG públicos com uma
playlist de terceiros; não hospeda, transmite ou redistribui nenhum
stream de vídeo. Os links de streaming continuam sendo os mesmos
publicados originalmente pelo repositório
[Ramys/Iptv-Brasil-2026](https://github.com/Ramys/Iptv-Brasil-2026).
