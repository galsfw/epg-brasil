# Documentação Técnica — IPTV Brasil 2026

> Este arquivo é a documentação **técnica** do projeto (arquitetura,
> scripts, fontes de dados, regras de filtro/deduplicação, automação via
> GitHub Actions). Se você só quer **usar** as playlists/EPG no seu
> player de IPTV, veja o [`README.md`](../README.md) na raiz do
> projeto — ele tem um tutorial simples, sem esses detalhes internos.

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
| `playlists/canais_ao_vivo.m3u8` | Playlist só de **TV ao vivo**, já filtrada | Adicione como sua lista principal no TiviMate |
| `playlists/canais_ao_vivo_epg.xml` (e `.xml.gz`) | Guia de programação (**EPG/XMLTV**) desses mesmos canais | Adicione como fonte de EPG da lista acima |
| `playlists/filmes_e_series1.m3u8`, `filmes_e_series2.m3u8`, `filmes_e_series3.m3u8`, ... | Playlist(s) de **Filmes, Séries, Novelas, Doramas e Minisséries** juntos | Adicione cada uma como lista extra no TiviMate |
| `playlists/STATUS.txt` | Relatório da última atualização (contagens, hora) | Só para conferência/depuração |

### Por que Filmes/Séries virou vários arquivos em vez de um só?

O GitHub **recusa qualquer arquivo maior que 100 MB** enviado direto no
repositório (sem usar Git LFS). O conteúdo de VOD mesclado (Ramys BR06 +
BR04) já passa de **110 MB** num arquivo único e só tende a crescer com o
tempo — foi exatamente isso que causou o erro
`File ... exceeds GitHub's file size limit of 100.00 MB` / `GH001: Large
files detected` ao tentar dar `git push`.

A solução foi dividir a saída de VOD em uma série de arquivos numerados
— `filmes_e_series1.m3u8`, `filmes_e_series2.m3u8`,
`filmes_e_series3.m3u8`, ... — todos misturando Filmes, Séries, Novelas,
Doramas e Minisséries juntos (sem separar por categoria: o TiviMate já
organiza tudo sozinho pelas categorias/`group-title` de cada item, então
não haveria vantagem em ter um arquivo por tipo). Um novo arquivo é
aberto automaticamente sempre que o atual passa de ~40 MB (bem abaixo do
limite de 100 MB do GitHub, com folga para crescer) — isso é feito
sozinho a cada execução, então mesmo que o catálogo dobre de tamanho no
futuro, nunca mais deve estourar o limite do GitHub.

Basta adicionar **cada arquivo `filmes_e_series*.m3u8` que existir** em
`playlists/` como uma lista separada no TiviMate (o app deixa juntar
quantas listas você quiser — elas aparecem juntas no mesmo catálogo,
organizadas pelas categorias/`group-title` de cada item).

Todos os arquivos são regenerados sozinhos por uma GitHub Action (cron a
cada 6h) — depois de publicado, você não precisa mexer em mais nada. A
cada execução, arquivos antigos que não são mais necessários (versões
anteriores por categoria, ou "partes" numeradas que sobraram de um
catálogo que encolheu) são apagados automaticamente, para não acumular
lixo no repositório.

### Agrupamento de episódios de série (ordenação)

Nas listas de origem, os episódios de uma mesma série **não vêm em
ordem sequencial** — é comum encontrar, por exemplo, "Breaking Bad
S03E12", bem mais adiante "Breaking Bad S05E01" e só depois "Breaking
Bad S02E01". Se a saída só seguisse a ordem de chegada dos itens (como
em versões anteriores deste script), cada player mostrava os episódios
de uma série espalhados/fora de ordem dentro da categoria.

Por isso, depois de filtrar e deduplicar, **todos os itens de VOD
passam por uma ordenação explícita** antes de serem gravados nos
arquivos finais (`generate_vod.py`, função `vod_sort_key`):

1. Primeiro pelo **título "base"** (sem o sufixo de temporada/episódio),
   normalizado (sem acentos, maiúsculo) — isso já junta todos os
   episódios de uma mesma série em sequência no arquivo.
2. Depois pelo **número da temporada** (`S01`, `S02`, ...).
3. Depois pelo **número do episódio** (`E01`, `E02`, ...).

Filmes (sem `SxxExx` no nome) são tratados como "temporada 0, episódio
0" e ficam ordenados só pelo título, junto dos demais.

Essa ordenação é feita com o utilitário `sort` do próprio sistema
operacional (`external_sort()` em `generate_vod.py`), que faz um "merge
sort" em disco em vez de carregar tudo na memória de uma vez — assim
continua funcionando mesmo com um catálogo de ~450 mil itens numa
máquina com pouca memória disponível (~1.9 GB no sandbox de
desenvolvimento). O fluxo é:

1. Cada fonte é baixada e escaneada linha a linha (streaming, como
   antes); para cada item de VOD não-duplicado, grava-se um registro
   `chave_de_ordenação` + separador de controle + `entrada_extinf` +
   separador + `url` num arquivo temporário
   (`.vod_tmp/vod_unsorted.tmp`), usando um caractere de controle como
   separador (nunca aparece em texto normal de M3U).
2. Depois que todas as fontes foram processadas, o arquivo temporário
   inteiro é ordenado com `sort -t <separador> -k1,1 -S 150M
   --parallel=2`, gerando `.vod_tmp/vod_sorted.tmp`.
3. O arquivo ordenado é lido em streaming e dividido nos arquivos finais
   (`filmes_e_series1.m3u8`, `_2`, `_3`, ...) pela mesma lógica de
   `PartedWriter` de antes.
4. A pasta temporária `.vod_tmp/` é sempre removida ao final (em um
   bloco `try/finally`), mesmo se a execução falhar no meio.

Como a ordenação acontece **antes** da divisão em partes, uma série
nunca fica cortada "no meio" de forma confusa: ela sempre aparece
inteira e em ordem dentro do arquivo onde começa (a única exceção, rara,
é quando uma série for tão grande a ponto de cair bem na fronteira de
tamanho entre duas partes — mesmo assim os episódios continuam em
ordem, só que a partir de um certo ponto passam a ficar no arquivo
seguinte).

Validado manualmente após a implementação: séries como "Breaking Bad",
"The Capture" e "A Grande Família" (que antes apareciam com episódios
espalhados por dezenas de milhares de linhas de distância) agora saem
com todos os episódios em sequência estrita de temporada/episódio. As
poucas "lacunas" remanescentes (ex.: falta o episódio 29 de uma
temporada) são lacunas reais na numeração da lista de origem, não um
efeito da ordenação.

## 🧹 O que é filtrado / removido

- **Conteúdo adulto/pornográfico** (grupos como "CANAIS | ADULTOS +18" e
  "FILMES | ADULTOS +18"): removido de `canais_ao_vivo.m3u8` **e** de
  todos os arquivos de VOD (`filmes_e_series1.m3u8`, `filmes_e_series2.m3u8`,
  ...). O filtro (`is_adult_group()` em `common.py`) olha
  só o nome do **grupo**, nunca palavras no título — isso evita remover
  por engano conteúdo legítimo que apenas contém termos parecidos, como o
  documentário "Pornhub: Sexo Bilionário", a minissérie "Gêmeas Trans", o
  filme de ação "xXx: Reativado" ou a série "Adultos" da Disney+.
- **ASMR** (grupo "Canais | Dormir e Relaxar" + qualquer canal com "ASMR"
  no nome, mesmo fora desse grupo, como o "K-ASMR"): removido de
  `canais_ao_vivo.m3u8` e do EPG — são loops sem grade real.
- **Copa do Mundo 2026** (grupo temporário com jogos avulsos, sem
  `tvg-id`): não entra em `canais_ao_vivo.m3u8` nem no EPG.
- **Filmes e Séries** (grupos `Filmes | *`, `Series | *`, `Doramas`,
  `Novelas`, `Novelas Turcas`, `Mini Series`): não entram mais junto com
  os canais de TV — vão exclusivamente para os arquivos de VOD
  (`filmes_e_series1.m3u8`, `filmes_e_series2.m3u8`, ...).

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

Tanto `canais_ao_vivo.m3u8` quanto os arquivos de VOD mesclam BR06 +
BR04, usando o nome/título normalizado como chave (acentos, maiúsculas e
espaços não contam) para não duplicar o mesmo conteúdo:

- **Canais ao vivo**: a deduplicação é feita **entre fontes diferentes**
  (BR06 vs. BR04) — dentro da mesma fonte, variações de **qualidade**
  (HD, FHD, 4K, H265 etc.) continuam todas na playlist, como streams
  alternativos do mesmo canal.
- **Filmes e séries**: a deduplicação é **global** — vale tanto para
  repetições dentro da mesma lista (algumas listas catalogam o mesmo
  filme em mais de uma categoria) quanto entre BR06 e BR04. Em ambos os
  casos, marcadores de **Legendado** (`[L]`/`[LEG]`) e **4K** ficam
  intactos na chave: uma versão legendada ou 4K nunca é tratada como
  duplicata da versão "normal" e continua saindo como item separado.

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
│   ├── filmes_e_series1.m3u8, filmes_e_series2.m3u8, ...  (partes automáticas)
│   └── STATUS.txt
├── scripts/
│   ├── common.py            # download, parsing de M3U, normalização e filtro de conteúdo adulto (compartilhado)
│   ├── generate_live.py     # mescla BR06+BR04+xKzin, gera canais_ao_vivo.m3u8 + canais_ao_vivo_epg.xml(.gz)
│   ├── generate_vod.py      # mescla BR06+BR04, gera filmes_e_series1.m3u8/2/3/... (dividido só por tamanho, para nunca passar do limite de 100 MB do GitHub)
│   └── update_all.py        # roda os dois geradores e grava playlists/STATUS.txt
├── .github/workflows/update-epg.yml   # roda tudo sozinho, de 6 em 6h
└── README.md
```

## 🚀 Como publicar isso "de verdade" (para funcionar sozinho)

Para o TiviMate conseguir **buscar sozinho** as atualizações, os arquivos
precisam estar acessíveis por uma URL pública estável. O jeito mais
simples e gratuito:

1. Crie um repositório no GitHub e suba a pasta `epg-br/` inteira
   (`scripts/` + `.github/workflows/` + este `README.md`).
2. Em **Settings → Actions → General → Workflow permissions**, marque
   **"Read and write permissions"** (necessário para a Action conseguir
   dar `git push` sozinha).
3. Rode a Action uma vez manualmente: aba **Actions → Atualizar canais ao
   vivo, EPG e Filmes/Séries → Run workflow**. Isso já cria a pasta
   `playlists/` com todos os arquivos dentro do repositório.
4. Use as URLs "raw" do GitHub nos seus apps (troque
   `SEU_USUARIO/SEU_REPO` pelos dados do seu repositório):
   - Canais ao vivo: `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/playlists/canais_ao_vivo.m3u8`
   - EPG: `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/playlists/canais_ao_vivo_epg.xml`
   - Filmes/Séries: `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/playlists/filmes_e_series1.m3u8`
     (e `filmes_e_series2.m3u8`, `filmes_e_series3.m3u8`, ... se existirem —
     confira quantos arquivos há em `playlists/` no seu repositório)

Depois disso a GitHub Action roda sozinha a cada 6 horas, refaz todos os
arquivos, e o TiviMate puxa a versão nova automaticamente sempre que
atualizar a lista/o guia.

> Alternativa sem GitHub: qualquer servidor/VPS com Python 3 e um `cron`
> rodando `python3 scripts/update_all.py` a cada poucas horas, servindo a
> pasta `playlists/` por HTTP, funciona do mesmo jeito.

## 📺 Como configurar no TiviMate

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

### 2) Filmes e Séries (listas separadas)
1. **Configurações → Listas de reprodução → Adicionar** de novo, uma vez
   para **cada** arquivo `filmes_e_series*.m3u8` que existir em
   `playlists/` (`filmes_e_series1.m3u8`, `filmes_e_series2.m3u8`,
   `filmes_e_series3.m3u8`, ...). O TiviMate deixa juntar quantas
   listas você quiser — elas aparecem lado a lado no mesmo catálogo,
   organizadas pelas categorias (Filmes, Séries, Novelas, Doramas,
   Minisséries) normalmente.
2. Não é preciso configurar EPG para essas listas — filmes/séries não
   usam guia de programação; o TiviMate organiza pelas categorias
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
