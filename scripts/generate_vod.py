#!/usr/bin/env python3
"""
Gera playlists/filmes_series.m3u8: playlist M3U separada só com
Filmes e Séries (VOD) a partir da playlist Ramys/Iptv-Brasil-2026
(CanaisBR06.m3u8).

Filmes/séries não têm um "guia de programação" tradicional (EPG), então
ficam fora do arquivo de canais ao vivo / do EPG e são publicados aqui em
uma playlist M3U própria, pronta para ser adicionada como uma segunda
lista no TiviMate (ou em qualquer outro player).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Channel, fetch_text, parse_m3u, PLAYLIST_URLS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
PLAYLISTS_DIR.mkdir(exist_ok=True)

OUT_M3U = PLAYLISTS_DIR / "filmes_series.m3u8"

# Prefixos (em minúsculo) de group-title considerados "Filmes e Séries".
VOD_GROUP_PREFIXES = (
    "filmes",
    "series",
    "doramas",
    "novelas",
    "mini series",
)


def is_vod_channel(ch: Channel) -> bool:
    return ch.group_title.strip().lower().startswith(VOD_GROUP_PREFIXES)


def write_vod_m3u(entries: list[Channel]) -> int:
    lines = ["#EXTM3U"]
    for ch in entries:
        extinf = (
            f'#EXTINF:-1 tvg-id="{ch.tvg_id}" tvg-name="{ch.tvg_name}" '
            f'tvg-logo="{ch.tvg_logo}" group-title="{ch.group_title}",{ch.display_name}'
        )
        lines.append(extinf)
        lines.append(ch.url)
    OUT_M3U.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(entries)


def run() -> dict:
    print("=== Filmes e Séries (VOD) - IPTV Brasil 2026 ===")

    all_entries: list[Channel] = []
    for url in PLAYLIST_URLS:
        print(f"Baixando playlist: {url}")
        text = fetch_text(url)
        if not text.strip():
            raise RuntimeError("playlist vazia")
        parsed = parse_m3u(text)
        vod = [c for c in parsed if is_vod_channel(c) and c.url]
        print(f"  -> {len(parsed)} entradas totais, {len(vod)} itens de Filmes/Séries")
        all_entries.extend(vod)

    if not all_entries:
        raise RuntimeError("nenhum item de VOD encontrado")

    n = write_vod_m3u(all_entries)
    print(f"\nArquivo gerado: {OUT_M3U} ({OUT_M3U.stat().st_size:,} bytes)")
    print(f"Total de itens (filmes + episódios de séries): {n}")

    return {"itens_filmes_series": n}


def main() -> int:
    try:
        run()
    except RuntimeError as exc:
        print(f"ERRO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
