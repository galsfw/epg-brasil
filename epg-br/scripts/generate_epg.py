#!/usr/bin/env python3
"""
Gerador automático de EPG (XMLTV) para a lista IPTV Brasil 2026
(https://github.com/Ramys/Iptv-Brasil-2026 - CanaisBR06.m3u8)

O script:
  1. Baixa a(s) playlist(s) M3U informadas em PLAYLIST_URLS;
  2. Extrai todos os canais "ao vivo" (group-title começando com "Canais");
  3. Baixa várias fontes públicas de EPG (XMLTV) para o Brasil;
  4. Casa cada tvg-id/nome de canal da playlist com um canal das fontes de
     EPG usando: (a) id exato, (b) nome exato normalizado, (c) fuzzy match,
     (d) fallback por rede nacional para afiliadas regionais (Globo, SBT,
     Record, Band, RedeTV!);
  5. Gera um único arquivo XMLTV (epg.xml e epg.xml.gz) cujo <channel id="">
     é EXATAMENTE igual ao tvg-id usado na playlist, pronto para uso no
     TiviMate e em qualquer app compatível com XMLTV.

Este script é usado tanto localmente quanto pela GitHub Action
(.github/workflows/update-epg.yml), que roda em um cron e faz commit
automático do resultado, mantendo o EPG sempre atualizado.
"""

from __future__ import annotations

import difflib
import gzip
import re
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import normalize_name, normalize_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

USER_AGENT = "Mozilla/5.0 (EPG-Brasil-Generator; +https://github.com/)"
TIMEOUT = 40
RETRIES = 3

# ---------------------------------------------------------------------------
# Fontes
# ---------------------------------------------------------------------------

# Playlist(s) M3U de origem (o pedido do usuário aponta para CanaisBR06.m3u8,
# mas o repositório publica outras listas parecidas; mantemos apenas a
# solicitada por padrão).
PLAYLIST_URLS = [
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR06.m3u8",
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
]

# Grupos considerados "canais ao vivo" (possuem grade real). Filmes, séries,
# VOD, playlists de música/ASMR etc. não têm EPG tradicional e são ignorados.
LIVE_GROUP_PREFIX = "canais"

# Grupos que, apesar de começarem com "Canais", não são canais de TV com
# programação real e por isso são sempre excluídos do EPG:
#  - "Canais | Dormir e Relaxar": loops de ASMR/chuva/natureza sem grade.
# Obs.: o grupo "Copa do Mundo 2026" já é excluído automaticamente porque
# seu group-title não começa com "Canais".
EXCLUDED_GROUPS = {
    "canais | dormir e relaxar",
}

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


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def http_get(url: str) -> bytes:
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            last_err = exc
            print(f"  aviso: falha ao baixar {url} (tentativa {attempt}/{RETRIES}): {exc}")
            time.sleep(2 * attempt)
    print(f"  ERRO: não foi possível baixar {url}: {last_err}")
    return b""


def fetch_text(url: str) -> str:
    raw = http_get(url)
    if not raw:
        return ""
    if url.endswith(".gz"):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# M3U parsing
# ---------------------------------------------------------------------------

@dataclass
class Channel:
    tvg_id: str
    tvg_name: str
    display_name: str
    group_title: str
    tvg_logo: str = ""


ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


def parse_m3u(text: str) -> list[Channel]:
    channels: list[Channel] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR_RE.findall(line))
            display_name = line.rsplit(",", 1)[-1].strip()
            channels.append(
                Channel(
                    tvg_id=attrs.get("tvg-id", "").strip(),
                    tvg_name=attrs.get("tvg-name", "").strip(),
                    display_name=display_name,
                    group_title=attrs.get("group-title", "").strip(),
                    tvg_logo=attrs.get("tvg-logo", "").strip(),
                )
            )
        i += 1
    return channels


def is_live_channel(ch: Channel) -> bool:
    group = ch.group_title.lower()
    if group in EXCLUDED_GROUPS:
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


def classify_network(ch: "Channel") -> str | None:
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
# XMLTV output
# ---------------------------------------------------------------------------

def build_xmltv(channels: list[Channel], sources: list[EpgSource]) -> tuple[ET.Element, int, int]:
    tv = ET.Element(
        "tv",
        attrib={
            "generator-info-name": "epg-br-auto-generator",
            "generator-info-url": "https://github.com/",
            "date": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S %z") or
                    datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S +0000"),
        },
    )

    seen_ids = set()
    matched = 0
    unmatched = 0

    # Evita duplicar canais com o mesmo tvg-id (a playlist repete o mesmo
    # tvg-id para várias variantes de qualidade do mesmo canal).
    unique_channels = {}
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
            icon = ET.SubElement(channel_el, "icon", {"src": ch.tvg_logo})

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


def main() -> int:
    print("=== Gerador de EPG - IPTV Brasil 2026 ===")
    print(f"Executado em: {datetime.now(timezone.utc).isoformat()}Z\n")

    all_channels: list[Channel] = []
    for url in PLAYLIST_URLS:
        print(f"Baixando playlist: {url}")
        text = fetch_text(url)
        if not text.strip():
            print("  ERRO: playlist vazia, abortando.")
            return 1
        parsed = parse_m3u(text)
        live = [c for c in parsed if is_live_channel(c)]
        print(f"  -> {len(parsed)} entradas totais, {len(live)} canais ao vivo")
        all_channels.extend(live)

    if not all_channels:
        print("Nenhum canal ao vivo encontrado. Abortando.")
        return 1

    print()
    sources = load_epg_sources(EPG_SOURCES)
    if not sources:
        print("ERRO: nenhuma fonte de EPG pôde ser baixada.")
        return 1

    print("\nCasando canais da playlist com as fontes de EPG...")
    tv_root, matched, unmatched = build_xmltv(all_channels, sources)
    total_unique = matched + unmatched
    print(f"  -> {matched}/{total_unique} canais com programação encontrada")

    indent(tv_root)
    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        tv_root, encoding="utf-8"
    )

    out_xml = OUTPUT_DIR / "epg.xml"
    out_gz = OUTPUT_DIR / "epg.xml.gz"
    out_xml.write_bytes(xml_bytes)
    with gzip.open(out_gz, "wb") as f:
        f.write(xml_bytes)

    print(f"\nArquivo gerado: {out_xml} ({len(xml_bytes):,} bytes)")
    print(f"Arquivo gerado: {out_gz} ({out_gz.stat().st_size:,} bytes)")

    n_channels = len(tv_root.findall("channel"))
    n_programmes = len(tv_root.findall("programme"))
    print(f"Total no XMLTV final: {n_channels} canais, {n_programmes} programas")

    # grava um pequeno relatório para debug/registro do último update
    report = OUTPUT_DIR / "last_update.txt"
    report.write_text(
        f"Última atualização (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        f"Canais na playlist (ao vivo, únicos): {total_unique}\n"
        f"Canais com EPG casado: {matched}\n"
        f"Canais sem EPG disponível: {unmatched}\n"
        f"Canais no arquivo final: {n_channels}\n"
        f"Programas no arquivo final: {n_programmes}\n",
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
