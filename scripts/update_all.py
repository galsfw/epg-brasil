#!/usr/bin/env python3
"""
Ponto de entrada único: gera TUDO (canais ao vivo + EPG + filmes/séries)
em uma única execução e grava um relatório combinado em
playlists/STATUS.txt.

Uso:
    python3 scripts/update_all.py

É isso que a GitHub Action roda a cada poucas horas para manter os
arquivos em playlists/ sempre atualizados.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_live  # noqa: E402
import generate_vod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
STATUS_FILE = PLAYLISTS_DIR / "STATUS.txt"


def main() -> int:
    PLAYLISTS_DIR.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)

    print("############################################")
    print("# Atualizando canais ao vivo + EPG          #")
    print("############################################")
    try:
        live_stats = generate_live.run()
    except RuntimeError as exc:
        print(f"ERRO ao gerar canais ao vivo/EPG: {exc}")
        return 1

    print("\n############################################")
    print("# Atualizando Filmes e Séries                #")
    print("############################################")
    try:
        vod_stats = generate_vod.run()
    except RuntimeError as exc:
        print(f"ERRO ao gerar Filmes/Séries: {exc}")
        return 1

    finished = datetime.now(timezone.utc)

    status_lines = [
        f"Última atualização (UTC): {finished.isoformat()}",
        f"Duração: {(finished - started).total_seconds():.1f}s",
        "",
        "== Canais ao vivo (playlists/canais_ao_vivo.m3u8 + canais_ao_vivo_epg.xml) ==",
        f"Canais na playlist (entradas): {live_stats['canais_na_playlist']}",
        f"Canais únicos (por tvg-id): {live_stats['canais_unicos_por_tvg_id']}",
        f"Canais com EPG casado: {live_stats['canais_com_epg_casado']}",
        f"  (dos quais herdados de uma variação de qualidade irmã: "
        f"{live_stats['canais_com_epg_herdado_de_irmao']})",
        f"Canais sem EPG disponível: {live_stats['canais_sem_epg']}",
        f"Canais no arquivo XMLTV final: {live_stats['canais_no_epg_final']}",
        f"Programas no arquivo XMLTV final: {live_stats['programas_no_epg_final']}",
        "",
        "== Filmes e Séries (playlists/<categoria>.m3u8) ==",
        f"Itens (filmes + episódios de séries): {vod_stats['itens_filmes_series']}",
        "Arquivos: " + ", ".join(vod_stats["arquivos_filmes_series"]),
        "",
    ]
    STATUS_FILE.write_text("\n".join(status_lines), encoding="utf-8")

    print("\n============================================")
    print(f"Concluído. Relatório em: {STATUS_FILE}")
    print("============================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
