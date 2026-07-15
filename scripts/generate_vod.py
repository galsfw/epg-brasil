#!/usr/bin/env python3
"""
Gera a(s) playlist(s) de Filmes e Séries (VOD) em playlists/, mesclando
o conteúdo das listas do repositório Ramys/Iptv-Brasil-2026:

  - CanaisBR06.m3u8 (lista principal, usada como base)
  - CanaisBR04.m3u8 (fonte extra: título extras que faltam na BR06)

Filmes/séries não têm um "guia de programação" tradicional (EPG), então
ficam fora do arquivo de canais ao vivo / do EPG e são publicados aqui em
playlist(s) M3U próprias, prontas para serem adicionadas como listas
extras no TiviMate (ou em qualquer outro player).

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

Divisão em vários arquivos (IMPORTANTE):
GitHub recusa qualquer arquivo comum acima de 100 MB (sem Git LFS). Como
o conteúdo de VOD mesclado passa facilmente de 100 MB num arquivo único
(e só tende a crescer com o tempo), a saída é dividida automaticamente:

1. Primeiro por categoria (Filmes, Séries, Novelas, Doramas, Mini Séries)
   — o próprio TiviMate já mostra isso como listas separadas, então é
   uma divisão natural e amigável.
2. Dentro de uma categoria, se o arquivo ultrapassar um limite de
   segurança (bem abaixo dos 100 MB do GitHub), um novo "part" é aberto
   automaticamente (ex.: series_1.m3u8, series_2.m3u8, ...). Isso é
   automático e continua funcionando mesmo que o conteúdo dobre de
   tamanho no futuro — nunca mais deve estourar o limite do GitHub.

Arquivos antigos de "parts" que não são mais necessários (porque uma
categoria encolheu) são apagados antes de escrever os novos, para não
deixar lixo obsoleto na pasta playlists/.

Nota de implementação: as duas listas somam ~580 mil entradas e quase
tudo é VOD (o filtro de grupo não reduz muito o volume). Para não
estourar a memória, o processamento é feito em streaming — uma fonte
é baixada, escaneada linha a linha e gravada direto no(s) arquivo(s) de
saída, sem acumular listas gigantes de objetos em memória.
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

# Limite de segurança por arquivo: bem abaixo do limite real do GitHub
# (100 MB) para deixar folga para o crescimento entre uma atualização e
# a próxima.
MAX_PART_BYTES = 40 * 1024 * 1024  # 40 MB

# Listas M3U de origem, em ordem de prioridade: se o mesmo título (mesmo
# nome normalizado) aparecer em mais de uma lista, a primeira que o
# contiver "ganha" e as demais ocorrências são descartadas.
SOURCE_PLAYLIST_URLS = [
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR06.m3u8",
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR04.m3u8",
]

# Prefixo (em minúsculo) de group-title -> categoria/base do nome de
# arquivo de saída. A ordem importa: prefixos mais específicos primeiro
# ("mini series" antes de "series", já que "mini series" também começa
# com essas letras não, mas por clareza mantemos explícito).
VOD_CATEGORIES = [
    ("mini series", "mini_series"),
    ("filmes", "filmes"),
    ("series", "series"),
    ("doramas", "doramas"),
    ("novelas", "novelas"),
]

GROUP_RE = re.compile(r'group-title="([^"]*)"')
NAME_RE = re.compile(r'tvg-name="([^"]*)"')


def classify_vod_group(group_title: str) -> str | None:
    """Retorna o nome-base da categoria (para nome de arquivo) se o
    group-title for de Filmes/Séries/etc., ou None se não for VOD ou for
    conteúdo adulto (sempre removido).
    """
    if is_adult_group(group_title):
        return None
    g = group_title.strip().lower()
    for prefix, category in VOD_CATEGORIES:
        if g.startswith(prefix):
            return category
    return None


def iter_vod_lines(text: str):
    """Percorre o texto do M3U linha a linha (sem materializar listas
    grandes de objetos) e produz (extinf_line, url_line, title,
    categoria) só para as entradas de VOD (sem conteúdo adulto) que
    tiverem uma URL.
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
            category = classify_vod_group(group_title)
            if category is None:
                continue
            name_match = NAME_RE.search(line)
            title = name_match.group(1) if name_match else line.rsplit(",", 1)[-1]
            yield line, url_line.strip(), title, category
        else:
            i += 1


class PartedWriter:
    """Escreve uma sequência de entradas M3U em um ou mais arquivos
    "<categoria>.m3u8" / "<categoria>_2.m3u8" / "<categoria>_3.m3u8" ...,
    abrindo um novo arquivo sempre que o atual ultrapassa MAX_PART_BYTES,
    para nunca esbarrar no limite de 100 MB do GitHub.
    """

    def __init__(self, category: str):
        self.category = category
        self.part_index = 1
        self.file = None
        self.bytes_written = 0
        self.files_written: list[Path] = []
        self.items_per_file: list[int] = []
        self._items_in_current = 0
        self._open_new_part()

    def _part_path(self, index: int) -> Path:
        if index == 1:
            return PLAYLISTS_DIR / f"{self.category}.m3u8"
        return PLAYLISTS_DIR / f"{self.category}_{index}.m3u8"

    def _open_new_part(self):
        path = self._part_path(self.part_index)
        self.file = path.open("w", encoding="utf-8")
        self.file.write("#EXTM3U\n")
        self.bytes_written = len("#EXTM3U\n")
        self.files_written.append(path)
        self._items_in_current = 0

    def write_entry(self, extinf_line: str, url_line: str):
        chunk = extinf_line + "\n" + url_line + "\n"
        chunk_bytes = len(chunk.encode("utf-8"))
        if self.bytes_written + chunk_bytes > MAX_PART_BYTES and self._items_in_current > 0:
            self.file.close()
            self.items_per_file.append(self._items_in_current)
            self.part_index += 1
            self._open_new_part()
        self.file.write(chunk)
        self.bytes_written += chunk_bytes
        self._items_in_current += 1

    def close(self):
        if self.file is not None:
            self.file.close()
            self.items_per_file.append(self._items_in_current)
            self.file = None


def cleanup_old_vod_files():
    """Remove arquivos de VOD gerados em execuções anteriores (incluindo
    o antigo filmes_series.m3u8 monolítico e "parts" de categorias que
    hoje têm menos partes do que tinham antes), para não deixar lixo
    obsoleto versionado no repositório.
    """
    old_monolithic = PLAYLISTS_DIR / "filmes_series.m3u8"
    old_monolithic.unlink(missing_ok=True)

    categories = [c for _, c in VOD_CATEGORIES]
    for path in PLAYLISTS_DIR.glob("*.m3u8"):
        stem = path.stem
        for cat in categories:
            if stem == cat or re.fullmatch(rf"{re.escape(cat)}_\d+", stem):
                path.unlink(missing_ok=True)
                break


def run() -> dict:
    print("=== Filmes e Séries (VOD) - IPTV Brasil 2026 ===")

    cleanup_old_vod_files()

    seen_keys: set[str] = set()
    stats = {"por_fonte": [], "por_categoria": {}}
    writers: dict[str, PartedWriter] = {}
    total_written = 0

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
        for extinf_line, url_line, title, category in iter_vod_lines(text):
            vod_count += 1
            key = normalize_vod_key(title)
            if key and key in seen_keys:
                continue
            writer = writers.get(category)
            if writer is None:
                writer = PartedWriter(category)
                writers[category] = writer
            writer.write_entry(extinf_line, url_line)
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

    for category, writer in writers.items():
        writer.close()
        stats["por_categoria"][category] = {
            "itens": sum(writer.items_per_file),
            "arquivos": [p.name for p in writer.files_written],
        }

    if total_written == 0:
        raise RuntimeError("nenhum item de VOD encontrado")

    print("\nArquivos gerados:")
    for category, info in stats["por_categoria"].items():
        for path, count in zip(info["arquivos"], writers[category].items_per_file):
            size = (PLAYLISTS_DIR / path).stat().st_size
            print(f"  {path}: {count} itens, {size:,} bytes")
    print(f"Total de itens (filmes + episódios de séries): {total_written}")

    return {
        "itens_filmes_series": total_written,
        "arquivos_filmes_series": [
            name for info in stats["por_categoria"].values() for name in info["arquivos"]
        ],
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
