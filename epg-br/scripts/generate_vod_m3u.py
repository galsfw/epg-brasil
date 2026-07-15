#!/usr/bin/env python3
"""
Gera um M3U separado contendo apenas Filmes e Séries (VOD) a partir da
playlist Ramys/Iptv-Brasil-2026 (CanaisBR06.m3u8).

Filmes/séries não têm um "guia de programação" tradicional (EPG), então
são mantidos fora do arquivo de canais ao vivo / fora do epg.xml e
publicados aqui em uma playlist M3U própria, pronta para ser adicionada
como uma segunda lista no TiviMate (ou em qualquer outro player).

Este script roda junto com o gerador de EPG na mesma GitHub Action
(.github/workflows/update-epg.yml), então o M3U de VOD também fica
sempre atualizado automaticamente.
"""

from __future__ import annotations

import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

USER_AGENT = "Mozilla/5.0 (EPG-Brasil-Generator; +https://github.com/)"
TIMEOUT = 40
RETRIES = 3

PLAYLIST_URLS = [
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR06.m3u8",
]

# Prefixos (em minúsculo) de group-title considerados "Filmes e Séries".
VOD_GROUP_PREFIXES = (
    "filmes",
    "series",
    "doramas",
    "novelas",
    "mini series",
)

ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


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
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def is_vod_group(group_title: str) -> bool:
    g = group_title.strip().lower()
    return g.startswith(VOD_GROUP_PREFIXES)


def extract_vod_entries(text: str) -> list[tuple[str, str]]:
    """Retorna lista de (linha_extinf, linha_url) para entradas VOD."""
    lines = text.splitlines()
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR_RE.findall(line))
            group_title = attrs.get("group-title", "")
            url_line = lines[i + 1] if i + 1 < len(lines) else ""
            if is_vod_group(group_title) and url_line and not url_line.startswith("#"):
                entries.append((line, url_line))
            i += 2
        else:
            i += 1
    return entries


def main() -> int:
    print("=== Gerador de M3U - Filmes e Séries (VOD) ===")
    print(f"Executado em: {datetime.now(timezone.utc).isoformat()}Z\n")

    all_entries: list[tuple[str, str]] = []
    for url in PLAYLIST_URLS:
        print(f"Baixando playlist: {url}")
        text = fetch_text(url)
        if not text.strip():
            print("  ERRO: playlist vazia, abortando.")
            return 1
        entries = extract_vod_entries(text)
        print(f"  -> {len(entries)} itens de Filmes/Séries encontrados")
        all_entries.extend(entries)

    if not all_entries:
        print("Nenhum item de VOD encontrado. Abortando.")
        return 1

    out_lines = ["#EXTM3U"]
    for extinf, url_line in all_entries:
        out_lines.append(extinf)
        out_lines.append(url_line)

    out_path = OUTPUT_DIR / "filmes_series.m3u8"
    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    print(f"\nArquivo gerado: {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"Total de itens (filmes + episódios de séries): {len(all_entries)}")

    report = OUTPUT_DIR / "last_update_vod.txt"
    report.write_text(
        f"Última atualização (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        f"Itens de Filmes/Séries no M3U: {len(all_entries)}\n",
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
