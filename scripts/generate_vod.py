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
(e só tende a crescer com o tempo), a saída fica em uma ÚNICA série de
arquivos numerados — filmes_e_series1.m3u8, filmes_e_series2.m3u8,
filmes_e_series3.m3u8, ... — todos misturando Filmes, Séries, Novelas,
Doramas e Mini Séries juntos (sem separar por categoria; o TiviMate já
organiza tudo pelas categorias/group-title de cada item, então não há
necessidade de arquivos separados por tipo). Um novo arquivo é aberto
automaticamente sempre que o atual ultrapassa um limite de segurança
(bem abaixo dos 100 MB do GitHub) — continua funcionando mesmo que o
conteúdo dobre de tamanho no futuro, nunca mais deve estourar o limite.

Arquivos antigos (de execuções anteriores, incluindo os antigos por
categoria "filmes.m3u8"/"series.m3u8"/etc. e o monolítico
"filmes_series.m3u8") que não são mais necessários são apagados antes de
escrever os novos, para não deixar lixo obsoleto na pasta playlists/.

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

# Nome-base dos arquivos de saída: filmes_e_series1.m3u8, _2.m3u8, ...
OUTPUT_BASENAME = "filmes_e_series"

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

# Nomes usados em execuções anteriores deste projeto — apagados a cada
# execução para não deixar arquivos obsoletos versionados.
LEGACY_VOD_NAMES = ("filmes_series", "filmes", "series", "doramas", "novelas", "mini_series")


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


class PartedWriter:
    """Escreve uma sequência de entradas M3U em uma série de arquivos
    "<basename>1.m3u8" / "<basename>2.m3u8" / "<basename>3.m3u8" ...,
    abrindo um novo arquivo sempre que o atual ultrapassa MAX_PART_BYTES,
    para nunca esbarrar no limite de 100 MB do GitHub.
    """

    def __init__(self, basename: str):
        self.basename = basename
        self.part_index = 1
        self.file = None
        self.bytes_written = 0
        self.files_written: list[Path] = []
        self.items_per_file: list[int] = []
        self._items_in_current = 0
        self._open_new_part()

    def _part_path(self, index: int) -> Path:
        return PLAYLISTS_DIR / f"{self.basename}{index}.m3u8"

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
    """Remove arquivos de VOD gerados em execuções anteriores (nomes por
    categoria de uma versão antiga deste script, o monolítico
    "filmes_series.m3u8", e partes numeradas antigas do
    "filmes_e_series" que hoje não são mais necessárias porque o
    catálogo encolheu), para não deixar lixo obsoleto versionado no
    repositório.
    """
    for name in LEGACY_VOD_NAMES:
        (PLAYLISTS_DIR / f"{name}.m3u8").unlink(missing_ok=True)
        for path in PLAYLISTS_DIR.glob(f"{name}_*.m3u8"):
            path.unlink(missing_ok=True)

    for path in PLAYLISTS_DIR.glob(f"{OUTPUT_BASENAME}*.m3u8"):
        if re.fullmatch(rf"{re.escape(OUTPUT_BASENAME)}\d+", path.stem):
            path.unlink(missing_ok=True)


def run() -> dict:
    print("=== Filmes e Séries (VOD) - IPTV Brasil 2026 ===")

    cleanup_old_vod_files()

    seen_keys: set[str] = set()
    stats = {"por_fonte": []}
    writer = PartedWriter(OUTPUT_BASENAME)
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
        for extinf_line, url_line, title in iter_vod_lines(text):
            vod_count += 1
            key = normalize_vod_key(title)
            if key and key in seen_keys:
                continue
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

    writer.close()

    if total_written == 0:
        for path in writer.files_written:
            path.unlink(missing_ok=True)
        raise RuntimeError("nenhum item de VOD encontrado")

    print("\nArquivos gerados:")
    for path, count in zip(writer.files_written, writer.items_per_file):
        size = path.stat().st_size
        print(f"  {path.name}: {count} itens, {size:,} bytes")
    print(f"Total de itens (filmes + episódios de séries): {total_written}")

    return {
        "itens_filmes_series": total_written,
        "arquivos_filmes_series": [p.name for p in writer.files_written],
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
