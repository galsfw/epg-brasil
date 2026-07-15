# IPTV Brasil 2026 — Canais ao Vivo + EPG + Filmes/Séries

Gera automaticamente, a partir das listas públicas do
[Ramys/Iptv-Brasil-2026](https://github.com/Ramys/Iptv-Brasil-2026)
(`CanaisBR06.m3u8` como base + `CanaisBR04.m3u8` como fonte extra),
os arquivos prontos para usar no **TiviMate** (ou qualquer player compatível
com M3U/XMLTV). Tudo fica em uma única pasta, `playlists/`, para ser fácil
de achar o que você precisa.

## 📂 Onde estão os arquivos (é só olhar em `playlists/`)

| Arquivo | O que é | Para que serve |
|---|---|---|
| `playlists/canais_ao_vivo.m3u8` | Playlist só de **TV ao vivo**, já filtrada | Adicione como sua lista principal |
| `playlists/canais_ao_vivo_epg.xml` (e `.xml.gz`) | Guia de programação (**EPG/XMLTV**) desses mesmos canais | Adicione como fonte de EPG da lista acima |
| `playlists/filmes_series.m3u8` | Playlist separada só de **Filmes e Séries** (VOD) | Adicione como uma **segunda lista** |
| `playlists/STATUS.txt` | Relatório da última atualização (contagens, hora) | Só para conferência/depuração |

Os dois "pacotes" — canais ao vivo (playlist + EPG) e filmes/séries — vivem
lado a lado na mesma pasta, sempre com esses mesmos nomes, então depois da
primeira configuração você nunca precisa procurar de novo: é só apontar o
player para a URL fixa de cada arquivo.

Todos são regenerados sozinhos por uma GitHub Action (cron a cada 6h) —
depois de publicado, você não precisa mexer em mais nada.

## 🧹 O que é filtrado / removido

- **Conteúdo adulto/pornográfico** (grupos como "CANAIS | ADULTOS +18" e
  "FILMES | ADULTOS +18"): removido de `canais_ao_vivo.m3u8` **e** de
  `filmes_series.m3u8`. 

`canais_ao_vivo.m3u8` e `canais_ao_vivo_epg.xml` contêm somente TV ao vivo
de verdade (Globo, SBT, RecordTV, Band, SporTV, ESPN, HBO, Telecine,
Premiere, canais Abertos/Estaduais etc.), com a grade real casada a partir
de fontes públicas de EPG.

## 🔀 De onde vêm os canais e o conteúdo de VOD

O repositório Ramys/Iptv-Parasil-2026 publica várias listas (`CanaisBR01`
a `CanaisBR06`). Elas foram checadas uma a uma quanto à saúde dos streams:

| Lista | Uso neste projeto | Motivo |
|---|---|---|
| `CanaisBR06` | ✅ Base (canais ao vivo + VOD) | Principal, mais completa e atualizada |
| `CanaisBR04` | ✅ Fonte extra (canais ao vivo + VOD) | Majoritariamente funcional nos testes; adiciona ~300 canais e ~250 mil itens de VOD que não estão na BR06 |
| `CanaisBR03` | ❌ Não usada | Mesmo conteúdo da BR04, mas com credenciais de stream expiradas (praticamente tudo fora do ar) |
| `CanaisBR01`, `CanaisBR02` | ❌ Não usadas | Servidores retornando erro de autenticação (401) em quase todos os streams testados |
| `CanaisBR05` | ❌ Não usada | Servidor não responde (timeout total nos testes) |

## 🔗 Como funciona o casamento de canais (M3U ⇄ EPG)

A playlist usa `tvg-id`s próprios (ex.: `globo.br`, `sportv.br`,
`recordtvsãopaulo.br`) que raramente batem com o `id` usado pelas fontes
públicas de EPG. O gerador:

1. Baixa a playlist e filtra os canais "ao vivo" (removendo ASMR/Copa do
   Mundo/VOD, como explicado acima);
2. Baixa várias fontes de EPG (XMLTV) gratuitas para o Brasil:
   - `epgshare01.online` (BR1 e BR2)
   - `limaalef/BrazilTVEPG` (`globo.xml`, `epg.xml`, `claro.xml`,
     `vivoplay.xml`, `maissbt.xml`)
   - `open-epg.com` — apenas os arquivos do Brasil (`brazil1.xml.gz` a
     `brazil5.xml.gz`, os únicos disponíveis lá para o país no momento)
3. Tenta casar cada canal, nesta ordem:
   1. **ID exato** (normalizado, sem acento/maiúsculas);
   2. **Nome exato** (nome do canal normalizado);
   3. **Fuzzy match** de nome (similaridade ≥ 90%);
   4. **Fallback por rede nacional**: afiliadas regionais de Globo, SBT,
      RecordTV, Band e RedeTV! sem grade própria publicada herdam a
      grade do canal "mãe" nacional (ex.: uma afiliada da Globo sem EPG
      específico usa a grade da Globo São Paulo).
4. Gera um `canais_ao_vivo_epg.xml` cujo `<channel id="...">` é
   **idêntico ao `tvg-id`** da playlist — não é preciso reatribuir EPG
   manualmente no player.

Hoje, cerca de **97% dos canais de TV aberta/afiliadas regionais** (com
`tvg-id` terminando em `.br`) e a maioria dos canais a cabo/streaming
ficam com grade real. Canais muito de nicho, sem nenhuma fonte pública de
dados, ficam sem `<channel>` no XML (o player mostra "sem informação"
para eles, sem quebrar o restante do guia).

## 🗂 Estrutura do projeto

```
epg-br/
├── playlists/                        ← TUDO que você vai usar está aqui
│   ├── canais_ao_vivo.m3u8
│   ├── canais_ao_vivo_epg.xml
│   ├── canais_ao_vivo_epg.xml.gz
│   ├── filmes_series.m3u8
│   └── STATUS.txt
├── scripts/
│   ├── common.py            # download, parsing de M3U, normalização e filtro de conteúdo adulto (compartilhado)
│   ├── generate_live.py     # mescla BR06+BR04, gera canais_ao_vivo.m3u8 + canais_ao_vivo_epg.xml(.gz)
│   ├── generate_vod.py      # mescla BR06+BR04, gera filmes_series.m3u8
│   └── update_all.py        # roda os dois geradores e grava playlists/STATUS.txt
├── .github/workflows/update-epg.yml   # roda tudo sozinho, de 6 em 6h
└── README.md
```
## 📺 Como configurar no aplicativo

### 1) Canais ao vivo + EPG
1. **Configurações → Listas de reprodução → Adicionar** e cole a URL de
   `canais_ao_vivo.m3u8`.
2. **Configurações → EPG → Fontes de EPG → Adicionar** e cole a URL de
   `canais_ao_vivo_epg.xml` (ou `.xml.gz`).
3. Volte em **Listas de reprodução → [sua lista] → Fonte de EPG** e
   habilite a fonte que você acabou de adicionar.
4. Abra o guia de canais — os canais casados (Globo, SBT, RecordTV, Band,
   SporTV, ESPN, HBO, Telecine, Premiere, afiliadas regionais etc.) já
   aparecem com a grade.

### 2) Filmes e Séries (lista separada)
1. **Configurações → Listas de reprodução → Adicionar** de novo, agora
   com a URL de `filmes_series.m3u8`.
2. Não é preciso configurar EPG para essa lista — filmes/séries não usam
   guia de programação; o TiviMate organiza pelas categorias
   (`group-title`) e mostra o pôster (`tvg-logo`) normalmente.

## 🛠 Rodando localmente (opcional, para testar/depurar)

```bash
cd epg-br
python3 scripts/update_all.py       # gera tudo de uma vez (recomendado)

# ou, se quiser rodar só uma parte:
python3 scripts/generate_live.py    # só canais ao vivo + EPG
python3 scripts/generate_vod.py     # só filmes e séries
```

Todos os scripts usam apenas a biblioteca padrão do Python (3.9+), sem
dependências externas.

## ⚠️ Aviso

Este projeto apenas organiza e casa metadados de EPG públicos com uma
playlist de terceiros; não hospeda, transmite ou redistribui nenhum
stream de vídeo. Os links de streaming continuam sendo os mesmos
publicados originalmente pelo repositório
[Ramys/Iptv-Brasil-2026](https://github.com/Ramys/Iptv-Brasil-2026).
