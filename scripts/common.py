"""
Funções compartilhadas pelos geradores do projeto (download com retry,
parsing de M3U e normalização de nomes/ids para o casamento com EPG).

Mantido em um único lugar para não duplicar lógica entre
generate_epg.py e generate_vod_m3u.py.
"""

from __future__ import annotations

import gzip
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = "Mozilla/5.0 (EPG-Brasil-Generator; +https://github.com/)"
TIMEOUT = 40
RETRIES = 3

# Playlist(s) M3U de origem. O pedido original aponta para CanaisBR06.m3u8;
# mantemos apenas essa por padrão.
PLAYLIST_URLS = [
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR06.m3u8",
]


# ---------------------------------------------------------------------------
# Download
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
    text = None
    for enc in ("utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="ignore")
    # Remove um BOM UTF-8 (\ufeff) que alguns provedores de EPG incluem no
    # início do arquivo; se não for removido, quebra checagens de prefixo
    # como `text.startswith("<?xml")` e o parser de XML.
    return text.lstrip("\ufeff")


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
    url: str = ""


ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


def parse_m3u(text: str) -> list[Channel]:
    """Faz o parsing de um M3U, retornando um Channel por entrada #EXTINF
    (com a URL do stream correspondente já anexada)."""
    channels: list[Channel] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR_RE.findall(line))
            display_name = line.rsplit(",", 1)[-1].strip()
            url_line = lines[i + 1] if i + 1 < len(lines) else ""
            channels.append(
                Channel(
                    tvg_id=attrs.get("tvg-id", "").strip(),
                    tvg_name=attrs.get("tvg-name", "").strip(),
                    display_name=display_name,
                    group_title=attrs.get("group-title", "").strip(),
                    tvg_logo=attrs.get("tvg-logo", "").strip(),
                    url=url_line.strip() if url_line and not url_line.startswith("#") else "",
                )
            )
            i += 2
        else:
            i += 1
    return channels


# ---------------------------------------------------------------------------
# Normalização de nomes/ids (para o casamento M3U <-> EPG)
# ---------------------------------------------------------------------------

STOPWORDS = {
    'HD', 'FHD', 'UHD', 'SD', '4K', 'H265', 'H264', 'ALT', 'DUAL', 'AUDIO',
    'LEGENDADO', 'LEG', 'DUBLADO', 'DUB', 'TV', 'BACKUP', 'BR', 'BRASIL',
    'BRAZIL', 'CANAL', 'THE',
}


def strip_accents(s: str) -> str:
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Turn any channel label into a canonical, comparable token string."""
    if not name:
        return ''
    name = name.strip()
    # drop quality / source qualifiers in [..] or (..)  e.g. [4K], (A), (B)
    name = re.sub(r'\[[^\]]*\]', ' ', name)
    name = re.sub(r'\([^)]*\)', ' ', name)
    name = strip_accents(name).upper()
    # drop a leading "CITY/UF" style prefix used by some EPG sources
    # e.g. "SAO.PAULO/SP..TCM.BR" -> "TCM.BR"
    name = re.sub(r'^[A-Z]+(?:[ .][A-Z]+)*\s*/\s*[A-Z]{2}[. ]+', '', name)
    # unify separators
    name = re.sub(r'[._\-/|!]+', ' ', name)
    tokens = [t for t in re.split(r'\s+', name) if t]
    tokens = [re.sub(r'[^A-Z0-9&+]', '', t) for t in tokens]
    tokens = [t for t in tokens if t and t not in STOPWORDS]
    return ' '.join(tokens)


def normalize_id(cid: str) -> str:
    if not cid:
        return ''
    cid = strip_accents(cid.strip().lower())
    cid = re.sub(r'\s+', '', cid)
    return cid


# Sufixos de qualidade/formato que aparecem "colados" ao nome de um canal
# para indicar apenas uma variante técnica do mesmo sinal (ex.: "TNT HD",
# "TNT FHD", "TNT H265", "TNT [4K]"). Usado só para agrupar variações do
# MESMO canal — é intencionalmente mais conservador que normalize_name()
# e não remove palavras que fazem parte do nome real (TV, Brasil, Canal),
# para não confundir canais diferentes (ex.: "TV Brasil" x "Canal Brasil").
QUALITY_SUFFIXES = {
    'HD', 'FHD', 'UHD', 'SD', '4K', 'H265', 'H264', 'ALT', 'DUAL', 'AUDIO',
    'LEGENDADO', 'LEG', 'DUBLADO', 'DUB', 'BACKUP',
}


def normalize_family_name(name: str) -> str:
    """Normaliza um nome de canal preservando as palavras do nome real,
    removendo apenas marcadores de qualidade/formato. Duas variantes do
    mesmo canal (ex.: "Globo HD" e "Globo FHD H265") caem na mesma chave;
    canais genuinamente diferentes (ex.: "TV Brasil" e "Canal Brasil")
    continuam com chaves distintas.
    """
    if not name:
        return ''
    name = name.strip()
    name = re.sub(r'\[[^\]]*\]', ' ', name)
    name = re.sub(r'\([^)]*\)', ' ', name)
    name = strip_accents(name).upper()
    name = re.sub(r'[._\-/|!]+', ' ', name)
    tokens = [t for t in re.split(r'\s+', name) if t]
    tokens = [re.sub(r'[^A-Z0-9&+]', '', t) for t in tokens]
    tokens = [t for t in tokens if t and t not in QUALITY_SUFFIXES]
    return ' '.join(tokens)


# ---------------------------------------------------------------------------
# Filtro de conteúdo adulto (compartilhado entre canais ao vivo e VOD)
# ---------------------------------------------------------------------------

# As listas do repositório marcam conteúdo adulto/pornográfico de forma
# consistente através do group-title (nunca só pelo título do item, que
# poderia gerar falsos positivos como o documentário "Pornhub: Sexo
# Bilionário", a minissérie "Gêmeas Trans", o canal musical "Stingray Hot
# Country" ou o filme de ação "xXx: Reativado"). Por isso o filtro
# verifica apenas o nome do grupo, nunca o título do item.
ADULT_GROUP_KEYWORDS = ("adulto", "+18", "xxx", "onlyfans")


def is_adult_group(group_title: str) -> bool:
    g = group_title.strip().lower()
    return any(k in g for k in ADULT_GROUP_KEYWORDS)


def normalize_vod_key(name: str) -> str:
    """Normaliza o título de um item de VOD (filme/episódio) só o
    suficiente para detectar duplicatas exatas entre listas diferentes
    (acentos, maiúsculas/minúsculas e espaços extras). Marcadores como
    "[L]"/"[LEG]" (legendado) e "[4K]" são preservados de propósito: uma
    versão legendada ou 4K de um título NÃO é considerada duplicata da
    versão "normal" e continua saindo como um item separado na playlist.
    """
    if not name:
        return ''
    key = strip_accents(name).upper()
    key = re.sub(r'\s+', ' ', key).strip()
    return key

