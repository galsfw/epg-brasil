#!/usr/bin/env python3
"""
Ponto de entrada único: gera TUDO (canais ao vivo + EPG + filmes/séries)
em uma única execução e grava um relatório combinado em
playlists/STATUS.txt.

Uso:
    python3 scripts/update_all.py

É isso que a GitHub Action roda a cada poucas horas para manter os
arquivos em playlists/ sempre atualizados.

RESILIÊNCIA (desde 2026-07-19): as duas etapas (canais ao vivo/EPG e
Filmes/Séries) rodam de forma INDEPENDENTE — um erro inesperado numa
delas não impede a outra de rodar e ser salva. Isso é importante porque
já aconteceu na prática: o domínio pollarplay.com (usado pela fonte de
VOD/canais CanaisBR06) saiu do ar por completo bem depois de a
CanaisBR04 já estar morta, zerando todas as fontes de VOD ao mesmo
tempo. Antes dessa mudança, um erro fatal na etapa de VOD travava
update_all.py inteiro ANTES do commit/push, então nem as atualizações
de canais ao vivo (que tinham funcionado normalmente) eram salvas no
repositório — a GitHub Action ficava falhando a cada 6h sem gerar nada
de novo. Agora, mesmo que uma das duas etapas fique zerada (sem nenhuma
fonte saudável), a outra continua sendo processada e salva; o
STATUS.txt deixa claro quando isso acontece, e o script só termina com
erro (exit code != 0) se as DUAS etapas falharem ao mesmo tempo — nesse
caso extremo não há nada de novo para commitar mesmo.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_live  # noqa: E402
import generate_vod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
STATUS_FILE = PLAYLISTS_DIR / "STATUS.txt"


def run_live_stage() -> tuple[dict | None, str | None]:
    """Roda a etapa de canais ao vivo + EPG. Retorna (stats, erro) —
    exatamente um dos dois é None.
    """
    print("############################################")
    print("# Atualizando canais ao vivo + EPG          #")
    print("############################################")
    try:
        return generate_live.run(), None
    except Exception as exc:  # noqa: BLE001 - qualquer falha aqui não pode
        # derrubar a etapa de VOD; registramos o traceback completo para
        # facilitar diagnóstico e seguimos em frente.
        print(f"ERRO ao gerar canais ao vivo/EPG: {exc}")
        traceback.print_exc()
        return None, str(exc)


def run_vod_stage() -> tuple[dict | None, str | None]:
    """Roda a etapa de Filmes e Séries (VOD). Retorna (stats, erro) —
    exatamente um dos dois é None.
    """
    print("\n############################################")
    print("# Atualizando Filmes e Séries                #")
    print("############################################")
    try:
        return generate_vod.run(), None
    except Exception as exc:  # noqa: BLE001 - mesma lógica do live_stage
        print(f"ERRO ao gerar Filmes/Séries: {exc}")
        traceback.print_exc()
        return None, str(exc)


def main() -> int:
    PLAYLISTS_DIR.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)

    live_stats, live_error = run_live_stage()
    vod_stats, vod_error = run_vod_stage()

    finished = datetime.now(timezone.utc)

    status_lines = [
        f"Última atualização (UTC): {finished.isoformat()}",
        f"Duração: {(finished - started).total_seconds():.1f}s",
        "",
        "== Canais ao vivo (playlists/canais_ao_vivo.m3u8 + canais_ao_vivo_epg.xml) ==",
    ]
    if live_stats is not None:
        status_lines += [
            f"Canais na playlist (entradas): {live_stats['canais_na_playlist']}",
            f"Canais únicos (por tvg-id): {live_stats['canais_unicos_por_tvg_id']}",
            f"Canais com EPG casado: {live_stats['canais_com_epg_casado']}",
            f"  (dos quais herdados de uma variação de qualidade irmã: "
            f"{live_stats['canais_com_epg_herdado_de_irmao']})",
            f"Canais sem EPG disponível: {live_stats['canais_sem_epg']}",
            f"Canais no arquivo XMLTV final: {live_stats['canais_no_epg_final']}",
            f"Programas no arquivo XMLTV final: {live_stats['programas_no_epg_final']}",
        ]
        if live_stats["canais_na_playlist"] == 0:
            status_lines.append(
                "  AVISO: 0 canais nesta execução — todas as fontes configuradas "
                "pareceram mortas (ver log da execução para detalhes)."
            )
        if live_stats.get("fontes_mortas"):
            status_lines.append(
                "  Fontes puladas por parecerem mortas: "
                + ", ".join(u.rsplit("/", 1)[-1] for u in live_stats["fontes_mortas"])
            )
    else:
        status_lines.append(f"ERRO INESPERADO nesta etapa: {live_error}")
    status_lines.append("")

    status_lines.append("== Filmes e Séries (playlists/filmes_e_series*.m3u8) ==")
    if vod_stats is not None:
        status_lines += [
            f"Itens (filmes + episódios de séries): {vod_stats['itens_filmes_series']}",
            "Arquivos: " + ", ".join(vod_stats["arquivos_filmes_series"]),
        ]
        if vod_stats["itens_filmes_series"] == 0:
            status_lines.append(
                "  AVISO: 0 itens nesta execução — todas as fontes configuradas "
                "pareceram mortas (ver log da execução para detalhes)."
            )
        if vod_stats.get("fontes_mortas"):
            status_lines.append(
                "  Fontes puladas por parecerem mortas: "
                + ", ".join(u.rsplit("/", 1)[-1] for u in vod_stats["fontes_mortas"])
            )
    else:
        status_lines.append(f"ERRO INESPERADO nesta etapa: {vod_error}")
    status_lines.append("")

    STATUS_FILE.write_text("\n".join(status_lines), encoding="utf-8")

    print("\n============================================")
    print(f"Concluído. Relatório em: {STATUS_FILE}")
    print("============================================")

    # Só falha o processo (exit code != 0) se as DUAS etapas quebraram de
    # forma inesperada — nesse caso extremo realmente não há nada de
    # novo pra commitar. Uma etapa "zerada" (sem fontes saudáveis, mas
    # sem erro de execução) não conta como falha: os arquivos foram
    # gerados normalmente, só que vazios, e isso já fica registrado no
    # STATUS.txt para quem for investigar depois.
    if live_error is not None and vod_error is not None:
        print("ERRO: as duas etapas (canais ao vivo/EPG e Filmes/Séries) "
              "falharam de forma inesperada nesta execução.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
