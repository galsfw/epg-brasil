# 📺 IPTV Brasil 2026 — Canais ao Vivo, Guia de Programação e Filmes/Séries

Uma coleção pronta para usar no seu aplicativo de IPTV favorito, com
**canais de TV ao vivo**, **guia de programação (EPG)** e um catálogo
enorme de **filmes, séries, novelas e doramas**. Tudo atualizado
automaticamente, então você só precisa configurar uma vez.

## ✨ O que você encontra aqui

### 📡 Canais ao vivo
Uma playlist com **milhares de canais**, incluindo:
- TV aberta (Globo e afiliadas regionais, SBT, RecordTV, Band, RedeTV!)
- Canais a cabo/streaming (SporTV, Premiere, ESPN, HBO, Telecine, Discovery,
  Paramount+, Prime Video, Disney+, Max, Apple TV e muitos outros)
- Esportes, notícias, infantil, variedades, documentários, música, religiosos
- Canais internacionais (Portugal, Estados Unidos, América Latina)
- Rádios

Sempre que existir mais de uma opção de qualidade (HD, FHD, 4K, Dual
Áudio), todas ficam disponíveis como alternativas do mesmo canal — se uma
não estiver funcionando bem no seu link, dá para trocar por outra sem
precisar procurar em outro lugar.

### 🗓️ Guia de programação (EPG)
Um guia com a grade de **centenas de canais**, mostrando o que está
passando agora e o que vem a seguir — igual à sua TV a cabo. Basta
carregar esse arquivo junto com a playlist no seu player.

### 🎬 Filmes, séries, novelas e doramas
Um catálogo enorme com **centenas de milhares de títulos**, organizado
por categoria e por serviço de streaming de origem (Netflix, Prime
Video, HBO Max, Disney+, Paramount+, Apple TV, Globoplay, Star+ e mais),
incluindo:
- Filmes por gênero (ação, comédia, terror, drama, animação...)
- Séries completas, com os episódios organizados em ordem (temporada e
  episódio), fáceis de assistir em sequência
- Novelas (brasileiras e turcas)
- Doramas e animes
- Versões **legendadas** e em **4K**, quando disponíveis, sempre como
  opções extras ao lado da versão padrão

Como o catálogo é grande, ele vem dividido em alguns arquivos numerados
(`filmes_e_series1`, `filmes_e_series2`, ...) — é só adicionar todos no
seu player, que ele junta tudo automaticamente num catálogo só.

### 🔄 Sempre atualizado
Um robô atualiza esses arquivos sozinho a cada poucas horas, então você
configura uma vez e a lista/guia vão se mantendo em dia sem precisar
baixar nada de novo manualmente.

### ✅ Só entra o que está funcionando de verdade
Antes de usar qualquer fonte, o robô testa uma amostra de streams com
requisições reais. Se uma fonte inteira estiver fora do ar (provedor
expirado, servidor caído), ela é deixada de fora **daquela
atualização** — sem quebrar o resto da lista. Assim que a fonte voltar
a funcionar, ela entra de volta sozinha na atualização seguinte, sem
precisar de nenhuma ação manual.

---

## 🚀 Como instalar (tutorial rápido)

Funciona em praticamente qualquer aplicativo de IPTV — TiviMate, IPTV
Smarters, Smart IPTV, GSE Smart IPTV, VLC, etc. A ideia é sempre a
mesma: você adiciona a **playlist** (o link que termina em `.m3u8`) e,
se o app tiver essa opção, adiciona também o **guia de programação**
(o link que termina em `.xml`).

### Passo a passo (exemplo com o TiviMate, o mais usado)

1. Abra o TiviMate e vá em **Configurações → Listas de reprodução →
   Adicionar lista de reprodução**.
2. Escolha **"Link (URL)"** e cole o endereço da playlist de canais ao
   vivo. Dê um nome (ex.: "Canais ao Vivo") e confirme.
3. Repita o passo 2 para **cada arquivo de Filmes e Séries**
   (`filmes_e_series1`, `filmes_e_series2`, etc.) — cada um vira uma
   lista separada, mas todos aparecem juntos no catálogo.
4. Agora vá em **Configurações → EPG → Fontes de EPG → Adicionar fonte
   de EPG**, escolha **"Link (URL)"** e cole o endereço do guia de
   programação.
5. Volte em **Listas de reprodução**, escolha a lista de canais ao vivo,
   entre em **Fonte de EPG** e selecione a fonte que você acabou de
   adicionar.
6. Pronto! Abra o guia de canais — a programação já deve aparecer nos
   canais compatíveis, e o catálogo de filmes/séries já estará
   disponível organizado por categoria.

> 💡 Em outros aplicativos o caminho é parecido: procure por algo como
> "Adicionar playlist/lista M3U" e "Adicionar fonte de EPG/XMLTV" nas
> configurações. Se o seu app só aceitar **um** link de playlist, dá
> para juntar os arquivos de filmes/séries em sequência ou usar um app
> que aceite múltiplas listas (a maioria aceita).

### Onde pegar os links
Os links das playlists e do guia de programação ficam na pasta
`playlists/` deste projeto. Se você recebeu este material através de um
repositório no GitHub, use os links "raw" de cada arquivo (peça para
quem compartilhou o projeto com você, caso não tenha os links à mão).

---

## 🙏 Créditos e fontes

Este projeto não hospeda nem produz nenhum conteúdo — ele apenas reúne,
organiza e casa metadados de fontes públicas e gratuitas, que são os
verdadeiros responsáveis por disponibilizar os canais e o guia de
programação:

- **[Ramys/Iptv-Brasil-2026](https://github.com/Ramys/Iptv-Brasil-2026)**
  — playlists de canais ao vivo e catálogo de filmes/séries.
- **[xKzin/IPTV-Brazuka](https://github.com/xKzin/IPTV-Brazuka)** —
  playlists adicionais de canais ao vivo.
- **[limaalef/BrazilTVEPG](https://github.com/limaalef/BrazilTVEPG)** —
  guias de programação (EPG) de canais brasileiros.
- **[epgshare01.online](https://epgshare01.online/)** — guias de
  programação (EPG) do Brasil.
- **[open-epg.com](https://www.open-epg.com/)** — guias de programação
  (EPG) adicionais do Brasil.

Todo o crédito pelos links de streaming e pelos dados de programação é
dessas fontes originais. Este projeto só faz o trabalho de juntar tudo,
remover duplicatas e deixar pronto para usar.

> ⚠️ Este é um projeto de organização de metadados para uso pessoal. Os
> links de streaming continuam sendo os mesmos publicados originalmente
> pelas fontes listadas acima.
