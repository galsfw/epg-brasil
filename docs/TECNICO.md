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

### Marcação tvg-type="movie"/"series" (separar Filmes de Séries no player)

Playlists M3U puras (sem Xtream Codes) não têm um jeito 100%
padronizado/documentado de dizer a um player "isto é uma série, não um
filme". Isso causa um problema visível em players como o TiviMate: eles
têm abas próprias de "Filmes" e "Séries" na tela de **Gerenciar
Grupos**, mas sem uma marcação explícita todo o conteúdo de VOD cai
misturado (a aba "Séries" existe, mas fica vazia ou mostra tudo junto
com os filmes).

Por isso, cada item de `filmes_e_series*.m3u8` ganha um atributo
`tvg-type="movie"` ou `tvg-type="series"` (`generate_vod.py`, função
`tag_tvg_type()`), decidido pela própria presença do padrão de
temporada/episódio `SxxExx` no título — o mesmo critério já usado para
agrupar/ordenar episódios:

```
#EXTINF:-1 tvg-type="movie" tvg-name="Filme Exemplo (2024)" ...
#EXTINF:-1 tvg-type="series" tvg-name="Série Exemplo S01E01" ...
```

Importante: **`tvg-type` não é um atributo oficial do padrão M3U** —
é a convenção mais citada pela comunidade de IPTV para esse fim, mas
não há garantia documentada de que todo player (ou toda versão do
TiviMate) a reconheça. Se o player não entender o atributo, ele é
simplesmente ignorado como qualquer atributo desconhecido — não quebra
nem muda o comportamento anterior. Validado no catálogo completo
(446.349 itens): 34.229 marcados como `movie` e 412.120 como `series`,
0 divergências entre a marcação e a real presença de `SxxExx` no
título.

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
| `CanaisBR04` | ⚠️ Fonte extra, sujeita à checagem automática de saúde | Foi funcional em testes anteriores, mas em 2026-07-16 detectamos que o provedor por trás expirou — ver seção "Checagem automática de saúde" abaixo. Continua na lista de fontes e volta a ser usada sozinha se o provedor voltar ao ar. |
| `CanaisBR03` | ❌ Não usada | Mesmo conteúdo da BR04, mas com credenciais de stream expiradas (praticamente tudo fora do ar) |
| `CanaisBR01`, `CanaisBR02` | ❌ Não usadas | Servidores retornando erro de autenticação (401) em quase todos os streams testados |
| `CanaisBR05` | ❌ Não usada | Servidor não responde (timeout total nos testes) |

Tanto `canais_ao_vivo.m3u8` quanto os arquivos de VOD mesclam BR06 +
BR04 (quando BR04 estiver saudável), usando o nome/título normalizado
como chave (acentos, maiúsculas e espaços não contam) para não duplicar
o mesmo conteúdo:

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

### Checagem automática de saúde de cada fonte (fontes mortas saem e voltam sozinhas)

Em 2026-07-16, o usuário reportou (com fotos) uma tela de erro "SEU
ACESSO EXPIROU" ao tentar assistir canais como "+SBT TV ZYN HD" e "ABC
News Live". Investigando, descobrimos que **toda a fonte `CanaisBR04`**
(servidor `joyfrvr.cc`) tinha expirado: qualquer URL de stream — canal
ao vivo, filme ou série, não importa o ID — devolvia HTTP 200 mas
sempre **os mesmos bytes** (um arquivo de erro genérico reciclado, não
o vídeo real). Isso passaria despercebido num teste simples de "o
servidor respondeu?", então foi preciso comparar o *conteúdo* de várias
amostras entre si.

O mesmo teste, aplicado às fontes do xKzin/IPTV-Brazuka, revelou mais
3 fontes igualmente mortas na mesma data: `IPTV-Brazuka.m3u`
(`onlivex.pro`, devolvendo a página padrão "Welcome to nginx" em
tudo), `IPTV-Brazuka4.m3u` (`dns.p2.wtf`, 404 em tudo) e
`IPTV-Brazuka5.m3u` (`cerejadoce.live`, mesma página "nginx" que a
Brazuka1 — parecem ser o mesmo provedor por trás das duas).

Em vez de simplesmente remover essas URLs do código manualmente (o que
exigiria alguém perceber o problema e editar os scripts toda vez que
uma fonte pública cair), implementamos `common.check_source_health()`:

1. Depois de baixar e filtrar uma fonte, pega uma amostra aleatória de
   ~10 URLs de stream dela.
2. Faz uma requisição HTTP real em cada uma (com uma pequena pausa
   entre elas), lendo só os primeiros 4 KB (rápido — não baixa o vídeo
   inteiro). O corpo é lido mesmo quando o servidor responde com um
   código de erro HTTP (ver bug abaixo).
3. **Critério de "fonte morta"**:
   - menos de 34% das amostras respondem (timeout/erro de rede) → fonte
     fora do ar; OU
   - 3+ amostras (ou metade das que responderam, o que for maior)
     devolvem **exatamente o mesmo conteúdo** entre si → sinal de
     arquivo de erro genérico sendo reciclado para tudo.
4. Se a primeira rodada indicar "morta", uma **segunda rodada** é feita
   depois de uma pausa maior antes de aceitar o veredito — só confirma
   "morta de verdade" se as duas rodadas concordarem.
5. Se a fonte for considerada morta (nas duas rodadas), ela é **pulada
   nesta execução** (0 canais/itens entram dela) — mas a URL
   **continua** normalmente em `SOURCE_PLAYLIST_URLS`. Na próxima
   atualização automática (a cada 6h via GitHub Action), a mesma fonte
   é testada de novo do zero: se o provedor original voltar ao ar, ela
   passa a ser usada de novo automaticamente, sem precisar editar nada.

Essa checagem roda tanto em `generate_live.py` (canais ao vivo, testando
amostra dos streams já filtrados de cada fonte) quanto em
`generate_vod.py` (VOD, testando amostra dos primeiros ~2.000 itens de
cada fonte — suficiente para decidir sobre a fonte inteira, sem precisar
escanear as ~200-380 mil entradas todas só para montar a amostra).

#### Bug encontrado e corrigido: falso positivo por rate-limit do próprio provedor

Ao validar a implementação em produção, a fonte `CanaisBR06` — sabidamente
saudável — foi classificada erroneamente como "morta". Investigando,
descobrimos que o provedor por trás dela (`play.pollarplay.com`) tem um
limite de conexões simultâneas por IP, e responde com HTTP 500 + corpo
`{"message":"Maximum number of connections reached"}` quando esse
limite é atingido — o que aconteceu porque a própria checagem de saúde
(rodando repetidamente durante testes) estava gerando esse volume de
conexões. Dois problemas em cascata:

1. A implementação original descartava (`return None`) qualquer
   resposta HTTP ≥ 400 sem ler o corpo — então a mensagem de rate-limit
   nunca chegava a ser vista, e a amostra contava simplesmente como
   "falha", empurrando a fonte para "menos de 34% respondendo" ⇒ morta.
2. Mesmo lendo o corpo, uma mensagem de rate-limit genérica poderia ser
   confundida com "conteúdo de erro reciclado" (o mesmo padrão usado
   para detectar fontes de verdade mortas).

Corrigido com três mudanças em `common.py`:
- `_sample_stream_bytes()` agora lê o corpo da resposta mesmo em caso de
  erro HTTP (via `except urllib.error.HTTPError as exc: exc.read(...)`).
- Uma lista de marcadores de texto (`RATE_LIMIT_MARKERS`, ex.: `"maximum
  number of connections"`) é reconhecida e essas amostras são excluídas
  da contagem (nem "ok" nem "falha" nem "conteúdo repetido de erro") —
  ficam como resultado inconclusivo daquela amostra específica.
- Uma pequena pausa entre requisições (`HEALTH_CHECK_DELAY_BETWEEN`) e a
  segunda rodada de confirmação (`HEALTH_CHECK_RETRY_DELAY`) reduzem a
  chance de a própria checagem instabilizar temporariamente um provedor
  saudável.

Validado depois da correção: mesmo com a fonte BR06 sob rate-limit
pesado (10/10 amostras retornando a mensagem de limite de conexões), a
checagem corretamente reconheceu isso como inconclusivo e manteve a
fonte como viva, em vez de descartá-la por engano.

Testes de calibração finais (depois da correção): fontes conhecidas
como vivas (BR06, Brazuka2, Brazuka6) classificadas corretamente como
saudáveis mesmo sob rate-limit; fontes conhecidas como mortas (BR04,
Brazuka1, Brazuka4, Brazuka5) continuaram corretamente classificadas
como mortas — 0 falso positivo/negativo nos casos testados. Resultado
real de uma execução em produção: `canais_ao_vivo.m3u8` com 4.330
entradas e VOD com 196.754 itens (refletindo BR04 realmente fora do ar
e BR06 saudável).

### Checagem automática de atualidade das fontes de EPG

O mesmo dia (2026-07-16), verificamos também a saúde das 14 fontes de
`EPG_SOURCES` — não só "o arquivo baixa e é XML válido" (o que já era
checado), mas também "os dados são realmente atuais". Descobrimos que
`limaalef/BrazilTVEPG/plutotv.xml` estava tecnicamente OK (XML válido,
baixa sem erro) mas continha uma grade de **outubro/2025** — quase 10
meses parada, enquanto os outros 6 arquivos do mesmo repositório
continuavam sendo atualizados normalmente a cada poucas horas
(confirmado no histórico de commits do GitHub: todos os outros arquivos
tinham commits de minutos atrás, só o `plutotv.xml` estava parado desde
04/10/2025).

Isso não é só "uma fonte a menos": como essa fonte vem **antes** das
fontes `open-epg.com` na ordem de prioridade de `find_match()`, dois
canais reais da nossa lista ("Cultura" e "Jovem Pan News") batiam por
nome tanto no `plutotv.xml` morto quanto em fontes atuais — e, pela
ordem de busca (a primeira fonte que bater "ganha"), esses canais
estavam recebendo a **grade errada e desatualizada**, quando havia uma
grade atual disponível mais abaixo na lista.

Implementado em `load_epg_sources()` (`generate_live.py`): depois de
baixar e parsear cada fonte de EPG, olhamos a data mais recente entre
todos os `<programme>` do arquivo. Se essa data já ficou mais de
`STALE_EPG_MAX_DAYS_BEHIND` (2) dias no passado — ou seja, a fonte parou
de publicar dias novos — ela é tratada como desatualizada e pulada
**nesta execução**, mas continua em `EPG_SOURCES` normalmente: se o
mantenedor voltar a atualizá-la, ela volta a ser usada sozinha na
próxima atualização automática.

Validado: com a correção, `plutotv.xml` passou a ser pulado
automaticamente (mensagem: "o programa mais recente termina em
2025-10-12 (277 dias atrás)"), e os canais "Cultura"/"Jovem Pan News"
passaram a receber corretamente a grade atual do `open-epg.com` (dados
de 2026-07-15) em vez da grade morta.

### Pipeline resiliente: uma categoria zerada não derruba a outra

Em 2026-07-19, a GitHub Action falhou (`Process completed with exit
code 1`) e nada foi commitado. O log mostrava `CanaisBR06` (a fonte
BASE de VOD e uma das fontes de canais ao vivo) sendo classificada como
morta pela checagem de saúde — junto com `CanaisBR04`, que já sabíamos
morta desde 2026-07-16. Investigando com dois resolvedores de DNS
públicos e independentes (Google DNS e Cloudflare DNS, fora do
ambiente da Action), confirmamos que **o domínio `pollarplay.com`
deixou de existir de vez** (resposta `NXDOMAIN`/`Status: 3` — diferente
de casos anteriores como `joyfrvr.cc`/`onlivex.pro`, que continuavam
resolvendo e só serviam conteúdo de erro). Ou seja, desta vez a
checagem de saúde **acertou**: a fonte morreu de verdade.

O problema real não era a detecção, e sim o que aconteceu depois dela:
como as duas únicas fontes de `generate_vod.py` (`CanaisBR06` e
`CanaisBR04`) morreram ao mesmo tempo, `total_collected` ficou em 0 e o
código antigo fazia `raise RuntimeError("nenhum item de VOD
encontrado")`. Esse erro subia sem tratamento até `update_all.py`, que
retornava código de saída 1 **antes mesmo de tentar o commit/push** —
então nem as atualizações de canais ao vivo (que tinham rodado
normalmente, com `IPTV-Brazuka2` e `IPTV-Brazuka6` saudáveis) eram
salvas no repositório. Resultado: a Action ficaria falhando a cada 6h,
sem nunca gerar nada de novo, até alguém notar e mexer manualmente no
código.

Corrigido com mudanças em três arquivos:

1. **`generate_vod.py`**: quando `total_collected == 0` (nenhuma fonte
   de VOD saudável), em vez de lançar `RuntimeError`, gera um arquivo
   `filmes_e_series1.m3u8` vazio (só o cabeçalho `#EXTM3U`) e retorna
   normalmente com `itens_filmes_series: 0`. `cleanup_old_vod_files()`
   já cuida de remover partes antigas (`_2`, `_3`, `_4`, ...) que não
   fazem mais sentido com um catálogo vazio.
2. **`generate_live.py`**: mesma lógica — se não sobrar nenhum canal ao
   vivo, ou nenhuma fonte de EPG utilizável, os arquivos
   (`canais_ao_vivo.m3u8`, `canais_ao_vivo_epg.xml`/`.gz`) são gerados
   vazios/mínimos em vez de lançar exceção.
3. **`update_all.py`**: reescrito para rodar as duas etapas (`canais ao
   vivo + EPG` e `Filmes e Séries`) de forma **independente**, cada uma
   dentro do seu próprio `try/except Exception` — um erro inesperado
   numa etapa não impede a outra de rodar nem de ser salva. O
   `STATUS.txt` é sempre escrito ao final com o que foi possível
   apurar, incluindo avisos explícitos quando uma categoria ficou
   zerada e quais fontes foram puladas por parecerem mortas. O processo
   só termina com código de saída diferente de zero (falha de verdade,
   sem nada a commitar) se **as duas etapas** falharem de forma
   inesperada ao mesmo tempo — uma categoria "zerada" por falta de
   fontes saudáveis não conta como falha, porque os arquivos foram
   gerados normalmente (só que vazios).

Validado com testes que simulam os três cenários: (a) as duas fontes de
VOD mortas (cenário real de 2026-07-19) — pipeline conclui com sucesso,
canais ao vivo salvos normalmente, VOD fica vazio e documentado no
STATUS.txt; (b) uma exceção de verdade só na etapa de VOD — mesmo
resultado, canais ao vivo não são afetados; (c) exceção de verdade nas
duas etapas ao mesmo tempo — aí sim o processo termina com erro,
corretamente, já que não haveria nada de novo para salvar.

**Nota sobre o catálogo de VOD**: por decisão do usuário, o projeto
ficou **sem nenhuma fonte de VOD saudável** depois da queda do
`pollarplay.com` — `filmes_e_series1.m3u8` fica vazio até uma fonte
nova ser adicionada (ou até alguma das duas fontes atuais,
`CanaisBR06`/`CanaisBR04`, voltar ao ar sozinha, o que a checagem de
saúde detectaria automaticamente na atualização seguinte).

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

## 🖼️ Completar pôsteres faltantes/genéricos via TMDB (opcional, não roda sozinho)

O formato M3U não tem campo de sinopse/descrição — só `tvg-logo`
(pôster), então a única melhoria de metadados possível é completar/
corrigir os pôsteres. `scripts/tmdb_enrich.py` cobre dois casos:

1. **Pôster vazio** (`tvg-logo=""`): a maioria são filmes sem `(ano)`
   reconhecível no título ou títulos onde a versão brasileira difere
   muito do nome original cadastrado no TMDB.
2. **Pôster "genérico"/reciclado** (bug encontrado na fonte original,
   não introduzido por este projeto): algumas listas de origem, quando
   não têm o pôster real de um título, reciclam a imagem de outro item
   qualquer em vez de deixar em branco. Isso é detectado contando, para
   cada URL de pôster, quantos títulos BASE distintos a usam — uma
   imagem de pôster de verdade pertence a UM título só; se a mesma URL
   aparece em 2+ títulos diferentes, é tratada como genérica
   (`find_generic_poster_urls()`). Exemplo real encontrado e corrigido:
   a série "A Sombra do Batman" usava uma imagem de capa de uma novela
   chinesa sem relação nenhuma, porque essa mesma URL de imagem estava
   reciclada em 286 títulos diferentes na fonte original.

Em ambos os casos, o título limpo é buscado no TMDB e só aceito se:

1. o nome bater **exatamente** (sem acento/maiúsculas) com o candidato
   do TMDB;
2. quando o título tiver um ano reconhecível, o ano do candidato bater
   (±1 ano de tolerância);
3. o candidato tiver **pelo menos 1 voto** no TMDB (evita escolher ao
   acaso entre vários registros fantasmas com 0 votos cada, um problema
   real observado em testes com títulos genéricos como "Bandit");
4. não houver **empate** no topo entre dois ou mais candidatos (nesse
   caso, fica sem pôster em vez de arriscar errado).

Um pôster genérico só é **trocado** quando uma correspondência nova e
confiável é encontrada — se a busca falhar, o pôster antigo (mesmo que
genérico) é mantido intacto, para nunca arriscar piorar o que já
existia.

Validado no catálogo completo (446.349 itens, ~17.450 títulos únicos a
resolver): 2.170 pôsteres genéricos detectados, ~88% de taxa de acerto
geral (vazios + genéricos), 86.443 itens de VOD tiveram o pôster
corrigido/completado numa única rodada.

**Esse script NÃO roda automaticamente** dentro do `update_all.py` nem
da GitHub Action — é opcional e precisa ser chamado à parte, porque
depende de uma chave própria do TMDB:

```bash
export TMDB_API_KEY="sua_chave_aqui"   # cadastro grátis em themoviedb.org/settings/api
python3 scripts/tmdb_enrich.py
```

No catálogo completo, a primeira execução (sem nada em cache ainda)
leva ~1h20 (respeitando o limite de requisições do TMDB). Os resultados
(inclusive os "não encontrados", para não tentar de novo à toa) ficam
salvos em `scripts/tmdb_poster_cache.json` — rodar de novo no futuro só
gasta cota do TMDB nos títulos novos que ainda não estão no cache
(uma segunda rodada sobre a mesma base leva só alguns segundos).

> ⚠️ **IMPORTANTE — ordem de execução**: `python3 scripts/generate_vod.py`
> (chamado também por `update_all.py`) **sempre baixa tudo de novo da
> fonte original e reescreve os arquivos `filmes_e_series*.m3u8` do
> zero**, sem pôsteres corrigidos. Ou seja: sempre que
> `update_all.py`/`generate_vod.py` rodar depois de você ter usado o
> `tmdb_enrich.py`, as correções de pôster são perdidas e precisam ser
> reaplicadas — **rode `tmdb_enrich.py` sempre por último**, depois de
> `update_all.py`. Isso é rápido (segundos) graças ao cache, mas é fácil
> esquecer esse passo. Se quiser automatizar isso de vez, dá para
> adicionar um passo no `.github/workflows/update-epg.yml` chamando
> `python3 scripts/tmdb_enrich.py` (com `TMDB_API_KEY` configurada como
> GitHub Secret do repositório) logo depois do
> `python3 scripts/update_all.py` — isso não foi feito por padrão
> porque o usuário preferiu rodar manualmente quando quiser, em vez de
> deixar automático.

## ⚠️ Aviso

Este projeto apenas organiza e casa metadados de EPG públicos com uma
playlist de terceiros; não hospeda, transmite ou redistribui nenhum
stream de vídeo. Os links de streaming continuam sendo os mesmos
publicados originalmente pelo repositório
[Ramys/Iptv-Brasil-2026](https://github.com/Ramys/Iptv-Brasil-2026).

Os pôsteres completados via TMDB usam a API pública do TMDB
("This product uses the TMDB API but is not endorsed or certified by
TMDB"), respeitando o uso não-comercial gratuito.

