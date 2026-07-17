#!/usr/bin/env python3
"""
Gera os arquivos de CANAIS AO VIVO a partir das listas de dois
repositórios públicos de IPTV Brasil:

  Ramys/Iptv-Brasil-2026:
    - CanaisBR06.m3u8 (lista principal, usada como base)
    - CanaisBR04.m3u8 (fonte extra: canais bons que faltam na BR06)

  xKzin/IPTV-Brazuka:
    - IPTV-Brazuka.m3u, IPTV-Brazuka2.m3u, IPTV-Brazuka4.m3u,
      IPTV-Brazuka5.m3u, IPTV-Brazuka6.m3u (fontes extras — ver nota
      abaixo sobre a IPTV-Brazuka3, que fica de fora)

  - playlists/canais_ao_vivo.m3u8       -> playlist M3U só com TV ao vivo
  - playlists/canais_ao_vivo_epg.xml    -> guia de programação (XMLTV)
  - playlists/canais_ao_vivo_epg.xml.gz -> mesma coisa, comprimida

O que entra como "canal ao vivo": todo group-title que começa com
"Canais" (Globo, SBT, RecordTV, Band, SporTV, ESPN, HBO, Telecine,
Premiere, canais Abertos/Estaduais etc.), EXCETO:
  - o grupo "Canais | Dormir e Relaxar" (ASMR/chuva/natureza — loops
    sem grade real) e qualquer canal com "ASMR" no nome;
  - qualquer grupo de conteúdo adulto/pornográfico (ex.: "CANAIS |
    ADULTOS +18"), filtrado por is_adult_group() em common.py.
Grupos de VOD/filmes/séries e o grupo temporário "Copa do Mundo 2026"
(sem tvg-id, sem grade) ficam de fora por não começarem com "Canais".

Como as listas do xKzin/IPTV-Brazuka usam outros nomes de grupo (ex.:
"Canais - Abertos", "CANAL 🚀 ABERTOS", ou sem separador nenhum, como em
"Abertos"), IS_LIVE_GROUP_EXTRA cobre esses formatos adicionais — sempre
como TV ao vivo de canais/emissoras, nunca VOD por filme/episódio.

Sobre as listas extras checadas e NÃO usadas:
  - Ramys CanaisBR01, 02, 03 e 05: streams fora do ar no momento
    (credenciais expiradas/servidor sem resposta). Só a CanaisBR04 se
    mostrou majoritariamente funcional nos testes.
  - xKzin IPTV-Brazuka3.m3u: mesmo formato das demais, mas com 100% dos
    streams retornando 404 nos testes (servidor/credenciais mortas).

Canais repetidos entre as fontes (mesmo nome normalizado) não são
duplicados na saída final — ver collect_live_channels().

Para o EPG, cada tvg-id/nome de canal é casado com uma fonte pública de
XMLTV usando, em ordem: id exato -> nome exato -> nome por fuzzy match ->
fallback pela grade nacional (Globo/SBT/RecordTV/Band/RedeTV!) quando o
canal é uma afiliada regional sem grade própria publicada.
"""

from __future__ import annotations

import difflib
import gzip
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    Channel,
    fetch_text,
    is_adult_group,
    normalize_family_name,
    normalize_id,
    normalize_name,
)
import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
PLAYLISTS_DIR.mkdir(exist_ok=True)

OUT_M3U = PLAYLISTS_DIR / "canais_ao_vivo.m3u8"
OUT_XML = PLAYLISTS_DIR / "canais_ao_vivo_epg.xml"
OUT_XML_GZ = PLAYLISTS_DIR / "canais_ao_vivo_epg.xml.gz"

# Listas M3U de origem, em ordem de prioridade: se o mesmo canal (mesmo
# nome normalizado) aparecer em mais de uma lista, a primeira que o
# contiver "ganha" e as demais ocorrências são descartadas.
SOURCE_PLAYLIST_URLS = [
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR06.m3u8",
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR04.m3u8",
    "https://raw.githubusercontent.com/xKzin/IPTV-Brazuka/main/IPTV-Brazuka.m3u",
    "https://raw.githubusercontent.com/xKzin/IPTV-Brazuka/main/IPTV-Brazuka2.m3u",
    "https://raw.githubusercontent.com/xKzin/IPTV-Brazuka/main/IPTV-Brazuka4.m3u",
    "https://raw.githubusercontent.com/xKzin/IPTV-Brazuka/main/IPTV-Brazuka5.m3u",
    "https://raw.githubusercontent.com/xKzin/IPTV-Brazuka/main/IPTV-Brazuka6.m3u",
]

# Fontes de EPG (XMLTV) públicas e gratuitas com programação real de canais
# brasileiros. São combinadas; a primeira fonte que tiver o canal "ganha".
EPG_SOURCES = [
    "https://epgshare01.online/epgshare01/epg_ripper_BR1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_BR2.xml.gz",
    "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/globo.xml",
    "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/epg.xml",
    "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/claro.xml",
    "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/vivoplay.xml",
    "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/maissbt.xml",
    "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/plutotv.xml",
    "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/xsports.xml",
    # Não usamos o globo-internacional.xml da mesma fonte: é a grade da
    # Globo Internacional (EUA), não de canais Globo do Brasil.
    # Open-EPG (open-epg.com) — apenas os arquivos do Brasil (brazil1..brazil5,
    # únicos disponíveis no momento; o site divide os canais BR em 5 partes).
    "https://www.open-epg.com/files/brazil1.xml.gz",
    "https://www.open-epg.com/files/brazil2.xml.gz",
    "https://www.open-epg.com/files/brazil3.xml.gz",
    "https://www.open-epg.com/files/brazil4.xml.gz",
    "https://www.open-epg.com/files/brazil5.xml.gz",
]

# Prefixos de group-title (já em minúsculo) que indicam "canal de TV ao
# vivo" nas diferentes listas usadas como fonte. A Ramys/Iptv-Brasil-2026
# usa "Canais | ..." / "Canais - ...", enquanto a xKzin/IPTV-Brazuka usa
# vários formatos: "Canais | ...", "Canais - ...", "CANAL <emoji> ..." ou
# até sem separador nenhum (ex.: "Abertos", "Filmes & Series" no sentido
# de canal linear de filmes, não VOD por título).
LIVE_GROUP_PREFIXES = ("canais", "canal ")

# Grupos "soltos" (sem o prefixo "canais"/"canal") que, em listas
# específicas, representam canais de TV ao vivo — não filmes/séries por
# título nem playlists de VOD. Comparados em minúsculo, sem espaços nas
# pontas.
EXTRA_LIVE_GROUPS = {
    # xKzin/IPTV-Brazuka6.m3u (sem prefixo "Canais" nos group-titles)
    "4k", "abertos", "agenda-esportiva", "agro negocios", "apple tv",
    "band", "casa do patrão", "combate ufc", "desenhos 24h",
    "discovery 24h", "discovery", "disney+ futebol", "disney+ outros",
    "disney+ tenis", "documentarios", "doramas 24h", "dual audio",
    "eleven esports-dazn", "espn", "esportes ppv", "esportes radical",
    "esportes", "eventos do dia", "filmes & series", "futebol americano",
    "futsal", "globo-capitais", "globo-centro oeste", "globo-nordeste",
    "globo-norte", "globo-sudeste", "globo-sul", "hbo max-tnt sports",
    "hbo", "infantil", "jogos do dia- copa do mundo fifa 2026",
    "legendados", "musicas", "nba-basquete", "noticias internacionais",
    "noticias", "paraguay", "paramount+", "pesca esportiva",
    "portugal abertos", "portugal esportes", "portugal notícias",
    "portugal reality", "portugal sportv", "portugal variedades",
    "premiere fc", "prime videos", "programas de tv 24h", "record tv",
    "religiosos", "run time", "sbt", "seriados 24h", "shows 24h",
    "sportv", "telecine", "variedades",
    # xKzin/IPTV-Brazuka4.m3u (grupos "MARATONA <emoji> ..." = canais
    # 24h em loop, mesmo conceito de "Canais | 24h Infantil" da BR06)
    "maratona ⏰ animes", "maratona ⏰ comedia",
}

# Grupos que, apesar de terem prefixo de "canal ao vivo", não são TV ao
# vivo de verdade e por isso ficam sempre de fora:
#  - "Canais | Dormir e Relaxar" / "Canais Para Relaxar": loops de
#    ASMR/chuva/natureza sem grade real.
# Grupos de conteúdo adulto/pornográfico (ex.: "CANAIS | ADULTOS +18")
# são removidos separadamente por is_adult_group(), em common.py.
EXCLUDED_GROUPS = {
    "canais | dormir e relaxar",
    "canais para relaxar",
}

# Palavras-chave que, se aparecerem no nome do canal (em qualquer grupo),
# indicam conteúdo de "relaxamento"/ASMR sem programação real e por isso
# são sempre excluídas (ex.: "K-ASMR" aparece fora do grupo dedicado).
EXCLUDED_NAME_KEYWORDS = ("asmr",)

# Redes nacionais cujas afiliadas regionais podem herdar a grade nacional
# quando não encontramos uma grade específica para a praça local.
NETWORK_FALLBACK_KEYWORDS = {
    "globo": ["globo", "rpc", "rbstv", "nsctv", "redeamazônica", "redeamazonica",
              "intertvcabugi", "eptv"],
    "record": ["record"],
    "sbt": ["sbt", "tvalterosa", "tvamazônia", "tvamazonia", "tvaratu",
            "tvmaralagoas", "tvpontanegra", "tvsãoluis", "tvsaoluis",
            "tvcapixaba", "tvtambaú", "tvtambau", "tvcidadeverde",
            "tvjangadeiro", "tvserradourada", "sbtgoianiatvserradourada"],
    "band": ["band"],
    "redetv": ["redetv", "tvguará", "tvguara", "tvimperial"],
}

NATIONAL_CANONICAL_NAME = {
    "globo": "GLOBO",
    "record": "RECORD",
    "sbt": "SBT",
    "band": "BAND",
    "redetv": "REDETV",
}

FUZZY_CUTOFF = 0.90


def is_live_channel(ch: Channel) -> bool:
    group = ch.group_title.strip().lower()
    if group in EXCLUDED_GROUPS:
        return False
    if is_adult_group(ch.group_title):
        return False
    name = (ch.display_name or ch.tvg_name).lower()
    if any(k in name for k in EXCLUDED_NAME_KEYWORDS):
        return False
    if group in EXTRA_LIVE_GROUPS:
        return True
    return group.startswith(LIVE_GROUP_PREFIXES)


def collect_live_channels(urls: list[str]) -> tuple[list[Channel], dict]:
    """Baixa cada playlist da lista, filtra os canais ao vivo e mescla
    tudo em uma única lista.

    A deduplicação só acontece ENTRE fontes diferentes: se um canal (por
    nome normalizado) já apareceu em uma fonte processada anteriormente,
    a ocorrência da fonte seguinte é descartada. Duplicatas DENTRO da
    mesma fonte são preservadas de propósito (ex.: variantes de
    qualidade "TNT", "TNT HD", "TNT FHD" continuam todas na playlist,
    dando ao usuário streams alternativos do mesmo canal).

    Antes de aceitar uma fonte, testamos sua SAÚDE com requisições HTTP
    reais numa amostra de streams (ver common.check_source_health()) —
    isso detecta fontes cujo provedor por trás expirou (credencial
    revogada, servidor reciclando um "erro genérico" com HTTP 200 em
    tudo, como descoberto em 2026-07-16 na fonte CanaisBR04). Uma fonte
    "morta" é pulada NESTA execução (0 canais entram dela), mas continua
    na lista `SOURCE_PLAYLIST_URLS` normalmente — na próxima atualização
    automática (a cada 6h) ela é testada de novo do zero, então volta
    sozinha caso o provedor original volte a funcionar, sem precisar
    editar código nenhum.
    """
    merged: list[Channel] = []
    seen_from_prior_sources: set[str] = set()
    stats = {"por_fonte": [], "fontes_mortas": []}

    for url in urls:
        print(f"Baixando playlist: {url}")
        text = fetch_text(url)
        if not text.strip():
            print(f"  aviso: não foi possível baixar {url}, pulando esta fonte")
            stats["por_fonte"].append((url, 0, 0))
            continue
        parsed = common.parse_m3u(text)
        live = [c for c in parsed if is_live_channel(c)]

        stream_urls = [c.url for c in live if c.url]
        is_alive, reason = common.check_source_health(stream_urls, label=url.rsplit("/", 1)[-1])
        print(f"  checagem de saúde: {reason}")
        if not is_alive:
            print(f"  aviso: fonte parece MORTA (credencial expirada/servidor fora do ar) "
                  f"— pulando {len(live)} canais desta fonte nesta execução")
            stats["por_fonte"].append((url, 0, 0))
            stats["fontes_mortas"].append(url)
            continue

        added = 0
        current_source_names: set[str] = set()
        for ch in live:
            key = normalize_name(ch.tvg_name or ch.display_name)
            if key and key in seen_from_prior_sources:
                continue
            merged.append(ch)
            added += 1
            if key:
                current_source_names.add(key)
        seen_from_prior_sources |= current_source_names

        print(f"  -> {len(parsed)} entradas totais, {len(live)} canais ao vivo "
              f"({added} mantidos, {len(live) - added} já existiam em fonte anterior)")
        stats["por_fonte"].append((url, len(live), added))

    if stats["fontes_mortas"]:
        print(f"\n{len(stats['fontes_mortas'])} fonte(s) de canais ao vivo pulada(s) "
              f"por parecerem mortas nesta execução:")
        for url in stats["fontes_mortas"]:
            print(f"  - {url}")

    return merged, stats


# ---------------------------------------------------------------------------
# EPG source parsing / indexing
# ---------------------------------------------------------------------------

@dataclass
class EpgSource:
    url: str
    tree: ET.Element = None
    by_id: dict = field(default_factory=dict)      # normalized id -> xml channel id
    by_name: dict = field(default_factory=dict)    # normalized name -> xml channel id


def load_epg_sources(urls: list[str]) -> list[EpgSource]:
    # Fontes de EPG cujo repositório/site de origem parece ter parado de
    # atualizar precisam de uma margem de tolerância maior que streams de
    # canal ao vivo — uma grade de EPG normalmente cobre só alguns dias
    # à frente, então qualquer coisa sem NENHUM programa daqui a
    # STALE_EPG_MAX_DAYS_BEHIND dias já é sinal de que o arquivo parou de
    # ser atualizado (descoberto em 2026-07-16: limaalef/plutotv.xml
    # estava com dados de outubro/2025, quase 10 meses parado, enquanto
    # as outras 6 fontes do mesmo repositório continuavam sendo
    # atualizadas normalmente a cada poucas horas).
    STALE_EPG_MAX_DAYS_BEHIND = 2
    today = datetime.now(timezone.utc).date()

    sources = []
    stale_sources = []
    for url in urls:
        print(f"Baixando EPG: {url}")
        text = fetch_text(url)
        if not text.strip():
            continue
        # Alguns provedores (ex.: open-epg.com) impõem um limite diário de
        # downloads por arquivo e, ao estourá-lo, respondem com HTML/texto
        # em vez do XML esperado. Detectamos esse caso para deixar o aviso
        # claro em vez de um genérico "XML inválido".
        stripped = text.lstrip()
        if not stripped.startswith("<?xml") and not stripped.startswith("<tv"):
            snippet = " ".join(text.split())[:160]
            print(f"  aviso: resposta não é XML (provável limite do provedor "
                  f"ou página de erro) em {url}: {snippet!r}")
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            print(f"  aviso: XML inválido em {url}: {exc}")
            continue

        # Checagem de ATUALIDADE: olha a data mais recente entre os
        # programas do arquivo. Se o "fim" da grade já ficou no passado
        # (a fonte parou de publicar dias novos), ela é tratada como
        # morta nesta execução — mas continua na lista de URLs, então
        # volta a ser usada sozinha se o mantenedor voltar a atualizá-la.
        max_prog_date = None
        for prog in root.findall("programme"):
            stop = prog.get("stop") or prog.get("start") or ""
            if len(stop) >= 8:
                try:
                    d = datetime.strptime(stop[:8], "%Y%m%d").date()
                    if max_prog_date is None or d > max_prog_date:
                        max_prog_date = d
                except ValueError:
                    continue
        if max_prog_date is not None:
            days_behind = (today - max_prog_date).days
            if days_behind > STALE_EPG_MAX_DAYS_BEHIND:
                print(f"  aviso: EPG parece DESATUALIZADO — o programa mais recente "
                      f"termina em {max_prog_date} ({days_behind} dias atrás) — "
                      f"pulando esta fonte nesta execução")
                stale_sources.append(url)
                continue

        src = EpgSource(url=url, tree=root)
        for ch in root.findall("channel"):
            cid = ch.get("id", "")
            if not cid:
                continue
            dn_el = ch.find("display-name")
            label = dn_el.text if dn_el is not None and dn_el.text else cid
            nid = normalize_id(cid)
            nname = normalize_name(label)
            src.by_id.setdefault(nid, cid)
            if nname:
                src.by_name.setdefault(nname, cid)
        n_prog = len(root.findall("programme"))
        print(f"  -> {len(src.by_id)} canais, {n_prog} programas")
        sources.append(src)

    if stale_sources:
        print(f"\n{len(stale_sources)} fonte(s) de EPG pulada(s) por parecerem "
              f"desatualizadas/abandonadas nesta execução:")
        for url in stale_sources:
            print(f"  - {url}")

    return sources


def classify_network(ch: Channel) -> str | None:
    haystacks = [ch.tvg_id.lower(), ch.tvg_name.lower(), ch.display_name.lower()]
    for net, keywords in NETWORK_FALLBACK_KEYWORDS.items():
        for haystack in haystacks:
            if any(k in haystack for k in keywords):
                return net
    return None


def find_match(ch: Channel, sources: list[EpgSource]):
    """Retorna (source, source_channel_id) ou None."""
    base_id = ch.tvg_id[:-3] if ch.tvg_id.lower().endswith(".br") else ch.tvg_id
    nid = normalize_id(base_id)
    candidate_names = {
        normalize_name(ch.tvg_name),
        normalize_name(ch.display_name),
        normalize_name(base_id),
    }
    candidate_names.discard("")

    # 1) id exato
    for src in sources:
        if nid and nid in src.by_id:
            return src, src.by_id[nid]

    # 2) nome exato
    for src in sources:
        for cname in candidate_names:
            if cname in src.by_name:
                return src, src.by_name[cname]

    # 3) fuzzy por nome
    for src in sources:
        name_keys = list(src.by_name.keys())
        for cname in candidate_names:
            close = difflib.get_close_matches(cname, name_keys, n=1, cutoff=FUZZY_CUTOFF)
            if close:
                return src, src.by_name[close[0]]

    # 4) fallback por rede nacional (afiliadas regionais herdam grade nacional)
    net = classify_network(ch)
    if net:
        national_name = normalize_name(NATIONAL_CANONICAL_NAME[net])
        for src in sources:
            if national_name in src.by_name:
                return src, src.by_name[national_name]

    return None


def inherit_from_siblings(
    unique_channels: dict[str, Channel],
    matches: dict[str, tuple],
) -> int:
    """Verifica variações de qualidade do mesmo canal (ex.: "TNT", "TNT HD",
    "TNT FHD", "TNT H265") que ficaram sem EPG enquanto uma variação irmã
    já foi casada com sucesso, e propaga o mesmo EPG para elas.

    Canais identificados como afiliada regional (Globo/SBT/RecordTV/Band/
    RedeTV! de uma praça específica) são sempre ignorados aqui, mesmo que
    tenham um "irmão" casado: praças diferentes podem ter programação
    local distinta, então herdar cegamente criaria um EPG errado.

    Retorna quantos canais foram corrigidos por essa herança.
    """
    families: dict[str, list[str]] = {}
    for tvg_id, ch in unique_channels.items():
        family_key = normalize_family_name(ch.tvg_name or ch.display_name)
        if not family_key:
            continue
        families.setdefault(family_key, []).append(tvg_id)

    fixed = 0
    for family_key, tvg_ids in families.items():
        if len(tvg_ids) < 2:
            continue

        matched_ids = [tid for tid in tvg_ids if matches.get(tid)]
        unmatched_ids = [tid for tid in tvg_ids if not matches.get(tid)]
        if not matched_ids or not unmatched_ids:
            continue

        # Se qualquer membro da família for uma afiliada regional, pulamos
        # a família inteira: praças diferentes do "mesmo" canal (ex.:
        # "Globo" em cidades distintas) podem ter grades diferentes.
        if any(classify_network(unique_channels[tid]) for tid in tvg_ids):
            continue

        donor_match = matches[matched_ids[0]]
        for tid in unmatched_ids:
            matches[tid] = donor_match
            fixed += 1

    return fixed


# ---------------------------------------------------------------------------
# Saída: M3U limpo de canais ao vivo
# ---------------------------------------------------------------------------

def write_live_m3u(channels: list[Channel]) -> int:
    lines = ["#EXTM3U"]
    for ch in channels:
        extinf = (
            f'#EXTINF:-1 tvg-id="{ch.tvg_id}" tvg-name="{ch.tvg_name}" '
            f'tvg-logo="{ch.tvg_logo}" group-title="{ch.group_title}",{ch.display_name}'
        )
        lines.append(extinf)
        lines.append(ch.url)
    OUT_M3U.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(channels)


# ---------------------------------------------------------------------------
# Saída: XMLTV
# ---------------------------------------------------------------------------

def build_xmltv(channels: list[Channel], sources: list[EpgSource]) -> tuple[ET.Element, int, int, int]:
    tv = ET.Element(
        "tv",
        attrib={
            "generator-info-name": "epg-br-auto-generator",
            "generator-info-url": "https://github.com/",
            "date": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000"),
        },
    )

    # Evita duplicar canais com o mesmo tvg-id (a playlist repete o mesmo
    # tvg-id para várias variantes de qualidade do mesmo canal).
    unique_channels: dict[str, Channel] = {}
    for ch in channels:
        if not ch.tvg_id:
            continue
        unique_channels.setdefault(ch.tvg_id, ch)

    matches: dict[str, tuple] = {}
    for tvg_id, ch in unique_channels.items():
        matches[tvg_id] = find_match(ch, sources)

    matched_direct = sum(1 for m in matches.values() if m)

    # Checagem extra: variações de qualidade do mesmo canal (HD/FHD/4K/
    # H265 etc.) que ficaram sem EPG enquanto uma variação irmã já foi
    # casada herdam o mesmo EPG, exceto afiliadas regionais (que podem
    # ter programação local diferente por praça).
    inherited = inherit_from_siblings(unique_channels, matches)

    matched = matched_direct + inherited
    unmatched = len(unique_channels) - matched

    programme_blocks = []
    for tvg_id, ch in sorted(unique_channels.items()):
        match = matches.get(tvg_id)
        if not match:
            continue
        src, src_cid = match

        channel_el = ET.SubElement(tv, "channel", {"id": tvg_id})
        dn = ET.SubElement(channel_el, "display-name")
        dn.text = ch.tvg_name or ch.display_name
        if ch.tvg_logo:
            ET.SubElement(channel_el, "icon", {"src": ch.tvg_logo})

        # copia todos os <programme> do canal de origem, remapeando o
        # atributo channel para o tvg-id da playlist.
        for prog in src.tree.findall("programme"):
            if prog.get("channel") != src_cid:
                continue
            new_prog = ET.fromstring(ET.tostring(prog))
            new_prog.set("channel", tvg_id)
            programme_blocks.append(new_prog)

    for p in programme_blocks:
        tv.append(p)

    return tv, matched, unmatched, inherited


def indent(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent(child, level + 1)
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def run() -> dict:
    """Executa a geração e retorna um dicionário com métricas (usado pelo
    script orquestrador scripts/update_all.py para montar o relatório)."""
    print("=== Canais ao vivo + EPG - IPTV Brasil 2026 ===")

    all_channels, source_stats = collect_live_channels(SOURCE_PLAYLIST_URLS)

    if not all_channels:
        raise RuntimeError("nenhum canal ao vivo encontrado")

    n_m3u = write_live_m3u(all_channels)
    print(f"\nPlaylist gerada: {OUT_M3U} ({n_m3u} entradas de {len(source_stats['por_fonte'])} fonte(s))")

    print()
    sources = load_epg_sources(EPG_SOURCES)
    if not sources:
        raise RuntimeError("nenhuma fonte de EPG pôde ser baixada")

    print("\nCasando canais da playlist com as fontes de EPG...")
    tv_root, matched, unmatched, inherited = build_xmltv(all_channels, sources)
    total_unique = matched + unmatched
    print(f"  -> {matched}/{total_unique} canais com programação encontrada "
          f"(dos quais {inherited} herdaram o EPG de uma variação de qualidade irmã)")

    indent(tv_root)
    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tv_root, encoding="utf-8")

    OUT_XML.write_bytes(xml_bytes)
    with gzip.open(OUT_XML_GZ, "wb") as f:
        f.write(xml_bytes)

    n_channels = len(tv_root.findall("channel"))
    n_programmes = len(tv_root.findall("programme"))

    print(f"\nArquivo gerado: {OUT_XML} ({len(xml_bytes):,} bytes)")
    print(f"Arquivo gerado: {OUT_XML_GZ} ({OUT_XML_GZ.stat().st_size:,} bytes)")
    print(f"Total no XMLTV final: {n_channels} canais, {n_programmes} programas")

    return {
        "canais_na_playlist": n_m3u,
        "canais_unicos_por_tvg_id": total_unique,
        "canais_com_epg_casado": matched,
        "canais_com_epg_herdado_de_irmao": inherited,
        "canais_sem_epg": unmatched,
        "canais_no_epg_final": n_channels,
        "programas_no_epg_final": n_programmes,
    }


def main() -> int:
    try:
        run()
    except RuntimeError as exc:
        print(f"ERRO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
