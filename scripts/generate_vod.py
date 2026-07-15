#!/usr/bin/env python3
"""
Gera playlists/filmes_series.m3u8: playlist M3U separada só com
Filmes e Séries (VOD), mesclando o conteúdo das listas do repositório
Ramys/Iptv-Brasil-2026:

  - CanaisBR06.m3u8 (lista principal, usada como base)
  - CanaisBR04.m3u8 (fonte extra: título extras que faltam na BR06)

Filmes/séries não têm um "guia de programação" tradicional (EPG), então
ficam fora do arquivo de canais ao vivo / do EPG e são publicados aqui em
uma playlist M3U própria, pronta para ser adicionada como uma segunda
lista no TiviMate (ou em qualquer outro player).

Conteúdo adulto/pornográfico (grupos como "FILMES | ADULTOS +18") é
sempre removido, de ambas as listas — ver is_adult_group() em common.py.

Sobre a mesclagem: a BR04 tem majoritariamente os MESMOS títulos que a
BR06 (95%+ de sobreposição nos testes), e cada lista também repete
alguns títulos internamente (o mesmo filme catalogado em mais de uma
categoria, por exemplo). Por isso a deduplicação é GLOBAL — não importa
se a repetição é dentro da mesma lista ou entre listas diferentes, só a
primeira ocorrência de cada título fica na playlist final. A chave usada
é o título normalizado (acentos/maiúsculas/espaços) — mas marcadores
como "[L]"/"[LEG]" (legendado) e "[4K]" são preservados de propósito:
uma versão legendada ou 4K do mesmo título NÃO é tratada como duplicata
da versão "normal" (tem uma chave diferente) e continua saindo como um
item separado, dando ao usuário as duas opções.

Sobre as listas CanaisBR01, 02, 03 e 05: BR01/BR02/BR05 não têm nenhum
conteúdo de VOD (só canais ao vivo) e BR03 é uma cópia da BR04 com
streams fora do ar (credenciais expiradas) — nenhuma das quatro é usada
aqui.

Nota de implementação: as duas listas somam ~580 mil entradas e quase
tudo é VOD (o filtro de grupo não reduz muito o volume). Para não
estourar a memória, o processamento é feito em streaming — uma fonte
é baixada, escaneada linha a linha e gravada direto no arquivo de saída
por vez, sem acumular listas gigantes de objetos em memória.
"""

from __future__ import annotations

import gc
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fetch_text, is_adult_group, normalize_vod_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
PLAYLISTS_DIR.mkdir(exist_ok=True)

OUT_M3U = PLAYLISTS_DIR / "filmes_series.m3u8"

# Listas M3U de origem, em ordem de prioridade: se o mesmo título (mesmo
# nome normalizado) aparecer em mais de uma lista, a primeira que o
# contiver "ganha" e as demais ocorrências são descartadas.
SOURCE_PLAYLIST_URLS = [
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR06.m3u8",
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR04.m3u8",
]

# Prefixos (em minúsculo) de group-title considerados "Filmes e Séries".
VOD_GROUP_PREFIXES = (
    "filmes",
    "series",
    "doramas",
    "novelas",
    "mini series",
)

GROUP_RE = re.compile(r'group-title="([^"]*)"')
NAME_RE = re.compile(r'tvg-name="([^"]*)"')


def is_vod_group(group_title: str) -> bool:
    if is_adult_group(group_title):
        return False
    return group_title.strip().lower().startswith(VOD_GROUP_PREFIXES)


def iter_vod_lines(text: str):
    """Percorre o texto do M3U linha a linha (sem materializar listas
    grandes de objetos) e produz (extinf_line, url_line, title) só para
    as entradas de VOD (sem conteúdo adulto) que tiverem uma URL.
    """
    lines = text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if line.startswith("#EXTINF"):
            url_line = lines[i + 1] if i + 1 < n else ""
            i += 2
            if not url_line or url_line.startswith("#"):
                continue
            group_match = GROUP_RE.search(line)
            group_title = group_match.group(1) if group_match else ""
            if not is_vod_group(group_title):
                continue
            name_match = NAME_RE.search(line)
            title = name_match.group(1) if name_match else line.rsplit(",", 1)[-1]
            yield line, url_line.strip(), title
        else:
            i += 1


def run() -> dict:
    print("=== Filmes e Séries (VOD) - IPTV Brasil 2026 ===")

    seen_keys: set[str] = set()
    stats = {"por_fonte": []}
    total_written = 0

    with OUT_M3U.open("w", encoding="utf-8") as out:
        out.write("#EXTM3U\n")

        for url in SOURCE_PLAYLIST_URLS:
            print(f"Baixando playlist: {url}")
            text = fetch_text(url)
            if not text.strip():
                print(f"  aviso: não foi possível baixar {url}, pulando esta fonte")
                stats["por_fonte"].append((url, 0, 0))
                continue

            total_entries = text.count("#EXTINF")
            vod_count = 0
            added = 0
            for extinf_line, url_line, title in iter_vod_lines(text):
                vod_count += 1
                key = normalize_vod_key(title)
                if key and key in seen_keys:
                    continue
                out.write(extinf_line)
                out.write("\n")
                out.write(url_line)
                out.write("\n")
                added += 1
                total_written += 1
                if key:
                    seen_keys.add(key)

            print(f"  -> {total_entries} entradas totais, {vod_count} itens de Filmes/Séries "
                  f"({added} novos, {vod_count - added} já existiam - mesma lista ou fonte anterior)")
            stats["por_fonte"].append((url, vod_count, added))

            # libera a memória do texto da fonte atual antes de baixar a próxima
            del text
            gc.collect()

    if total_written == 0:
        OUT_M3U.unlink(missing_ok=True)
        raise RuntimeError("nenhum item de VOD encontrado")

    print(f"\nArquivo gerado: {OUT_M3U} ({OUT_M3U.stat().st_size:,} bytes de "
          f"{len(stats['por_fonte'])} fonte(s))")
    print(f"Total de itens (filmes + episódios de séries): {total_written}")

    return {"itens_filmes_series": total_written}


def main() -> int:
    try:
        run()
    except RuntimeError as exc:
        print(f"ERRO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
