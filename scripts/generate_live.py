#!/usr/bin/env python3
"""
Gera os arquivos de CANAIS AO VIVO a partir da playlist Ramys/Iptv-Brasil-2026
(CanaisBR06.m3u8):

  - playlists/canais_ao_vivo.m3u8       -> playlist M3U só com TV ao vivo
  - playlists/canais_ao_vivo_epg.xml    -> guia de programação (XMLTV)
  - playlists/canais_ao_vivo_epg.xml.gz -> mesma coisa, comprimida

O que entra como "canal ao vivo": todo group-title que começa com
"Canais |" (Globo, SBT, RecordTV, Band, SporTV, ESPN, HBO, Telecine,
Premiere, canais Abertos/Estaduais etc.), EXCETO o grupo
"Canais | Dormir e Relaxar" (ASMR/chuva/natureza — loops sem grade real).
O grupo "Copa do Mundo 2026" já fica de fora por não começar com "Canais".

Para o EPG, cada tvg-id da playlist é casado com uma fonte pública de
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
from common import Channel, fetch_text, normalize_id, normalize_name, PLAYLIST_URLS  # noqa: E402
import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
PLAYLISTS_DIR.mkdir(exist_ok=True)

OUT_M3U = PLAYLISTS_DIR / "canais_ao_vivo.m3u8"
OUT_XML = PLAYLISTS_DIR / "canais_ao_vivo_epg.xml"
OUT_XML_GZ = PLAYLISTS_DIR / "canais_ao_vivo_epg.xml.gz"

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
]

LIVE_GROUP_PREFIX = "canais"

# Grupos que, apesar de começarem com "Canais", não são TV ao vivo de
# verdade e por isso ficam sempre de fora:
#  - "Canais | Dormir e Relaxar": loops de ASMR/chuva/natureza sem grade.
EXCLUDED_GROUPS = {
    "canais | dormir e relaxar",
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
    group = ch.group_title.lower()
    if group in EXCLUDED_GROUPS:
        return False
    name = (ch.display_name or ch.tvg_name).lower()
    if any(k in name for k in EXCLUDED_NAME_KEYWORDS):
        return False
    return group.startswith(LIVE_GROUP_PREFIX)


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
    sources = []
    for url in urls:
        print(f"Baixando EPG: {url}")
        text = fetch_text(url)
        if not text.strip():
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            print(f"  aviso: XML inválido em {url}: {exc}")
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

def build_xmltv(channels: list[Channel], sources: list[EpgSource]) -> tuple[ET.Element, int, int]:
    tv = ET.Element(
        "tv",
        attrib={
            "generator-info-name": "epg-br-auto-generator",
            "generator-info-url": "https://github.com/",
            "date": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000"),
        },
    )

    seen_ids = set()
    matched = 0
    unmatched = 0

    # Evita duplicar canais com o mesmo tvg-id (a playlist repete o mesmo
    # tvg-id para várias variantes de qualidade do mesmo canal).
    unique_channels: dict[str, Channel] = {}
    for ch in channels:
        if not ch.tvg_id:
            continue
        unique_channels.setdefault(ch.tvg_id, ch)

    programme_blocks = []

    for tvg_id, ch in sorted(unique_channels.items()):
        match = find_match(ch, sources)
        if not match:
            unmatched += 1
            continue
        src, src_cid = match
        matched += 1

        if tvg_id in seen_ids:
            continue
        seen_ids.add(tvg_id)

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

    return tv, matched, unmatched


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

    all_channels: list[Channel] = []
    for url in PLAYLIST_URLS:
        print(f"Baixando playlist: {url}")
        text = fetch_text(url)
        if not text.strip():
            raise RuntimeError("playlist vazia")
        parsed = common.parse_m3u(text)
        live = [c for c in parsed if is_live_channel(c)]
        print(f"  -> {len(parsed)} entradas totais, {len(live)} canais ao vivo")
        all_channels.extend(live)

    if not all_channels:
        raise RuntimeError("nenhum canal ao vivo encontrado")

    n_m3u = write_live_m3u(all_channels)
    print(f"\nPlaylist gerada: {OUT_M3U} ({n_m3u} entradas)")

    print()
    sources = load_epg_sources(EPG_SOURCES)
    if not sources:
        raise RuntimeError("nenhuma fonte de EPG pôde ser baixada")

    print("\nCasando canais da playlist com as fontes de EPG...")
    tv_root, matched, unmatched = build_xmltv(all_channels, sources)
    total_unique = matched + unmatched
    print(f"  -> {matched}/{total_unique} canais com programação encontrada")

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
