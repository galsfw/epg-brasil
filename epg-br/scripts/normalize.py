"""Utilities to normalize channel names/ids so entries from the
Ramys/Iptv-Brasil-2026 M3U playlist can be matched against public XMLTV
EPG sources that use different naming/id conventions."""

import re
import unicodedata

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
