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

MARCAÇÃO tvg-type="movie"/"series" (para separar Filmes de Séries no
player): listas M3U puras (sem Xtream Codes) não têm um jeito 100%
padronizado/documentado de dizer a um player "isto é uma série, não um
filme" — alguns players como o TiviMate têm abas próprias de "Filmes" e
"Séries" na tela de Gerenciar Grupos, mas sem essa marcação eles não
conseguem diferenciar um do outro (tudo cai como "filme" ou fica
misturado). Por isso cada item ganha um atributo `tvg-type="movie"` ou
`tvg-type="series"` (função tag_tvg_type()), decidido pela própria
presença do padrão de temporada/episódio "SxxExx" no título — o mesmo
critério já usado para agrupar/ordenar episódios. Esse atributo não é
oficial do padrão M3U: se o player não o reconhecer, ele é simplesmente
ignorado e nada muda; não há garantia de que resolva 100% dos casos em
todo player, mas é a abordagem mais citada pela comunidade para tentar
essa separação sem trocar de Xtream Codes.

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

ORDENAÇÃO / AGRUPAMENTO DE SÉRIES (IMPORTANTE):
Nas listas de origem, os episódios de uma mesma série NÃO vêm em ordem
sequencial — é comum encontrar "Série X S03E12", bem mais adiante
"Série X S05E01" e só depois "Série X S02E01", por exemplo. Se a saída
só seguisse a ordem de chegada dos itens (como em versões anteriores
deste script), cada player ia mostrar os episódios de uma série
espalhados/fora de ordem dentro da categoria.

Por isso, depois de filtrar e deduplicar, TODOS os itens de VOD passam
por uma ordenação explícita antes de serem gravados nos arquivos finais:
  1. Primeiro pelo título "base" (sem o sufixo de temporada/episódio),
     normalizado (sem acentos, maiúsculo) — isso já junta todos os
     episódios de uma mesma série em sequência no arquivo.
  2. Depois pelo número da temporada (S01, S02, ...).
  3. Depois pelo número do episódio (E01, E02, ...).
Filmes (sem "SxxExx" no nome) são tratados como "temporada 0, episódio
0" e ficam ordenados só pelo título, junto dos demais.

Essa ordenação é feita com o utilitário `sort` do sistema (mesmo usado
em qualquer Linux), que faz um "merge sort" em disco em vez de carregar
tudo na memória de uma vez — assim continua funcionando mesmo com um
catálogo de ~450 mil itens numa máquina com pouca memória disponível.

Divisão em vários arquivos (IMPORTANTE):
GitHub recusa qualquer arquivo comum acima de 100 MB (sem Git LFS). Como
o conteúdo de VOD mesclado passa facilmente de 100 MB num arquivo único
(e só tende a crescer com o tempo), a saída fica em uma ÚNICA série de
arquivos numerados — filmes_e_series1.m3u8, filmes_e_series2.m3u8,
filmes_e_series3.m3u8, ... — todos misturando Filmes, Séries, Novelas,
Doramas e Mini Séries juntos, já na ordem descrita acima (sem separar
por categoria; o TiviMate já organiza tudo pelas categorias/group-title
de cada item, então não há necessidade de arquivos separados por tipo).
Um novo arquivo é aberto automaticamente sempre que o atual ultrapassa
um limite de segurança (bem abaixo dos 100 MB do GitHub) — continua
funcionando mesmo que o conteúdo dobre de tamanho no futuro, nunca mais
deve estourar o limite. Como a ordenação acontece ANTES da divisão em
partes, uma série nunca fica cortada "no meio" de forma confusa: ela
sempre aparece inteira e em ordem dentro do arquivo onde começou (a
única exceção, rara, é quando uma série for tão grande a ponto de cair
bem na fronteira de tamanho entre duas partes — mesmo assim os episódios
continuam em ordem, só que a partir de um certo ponto passam a ficar no
arquivo seguinte).

Arquivos antigos (de execuções anteriores, incluindo os antigos por
categoria "filmes.m3u8"/"series.m3u8"/etc. e o monolítico
"filmes_series.m3u8") que não são mais necessários são apagados antes de
escrever os novos, para não deixar lixo obsoleto na pasta playlists/.

Nota de implementação: as duas listas somam ~580 mil entradas e quase
tudo é VOD (o filtro de grupo não reduz muito o volume). Para não
estourar a memória, o processamento é feito em streaming — uma fonte é
baixada, escaneada linha a linha e gravada num arquivo temporário de
"registros para ordenar" (chave de ordenação + a entrada M3U), sem
acumular listas gigantes de objetos em memória; só depois de todas as
fontes processadas é que o arquivo temporário inteiro é ordenado em
disco e finalmente dividido nos arquivos de saída.
"""

from __future__ import annotations

import gc
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fetch_text, is_adult_group, normalize_vod_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
PLAYLISTS_DIR.mkdir(exist_ok=True)

TMP_DIR = ROOT / ".vod_tmp"

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
EXTINF_PREFIX_RE = re.compile(r'^(#EXTINF:-?\d+)\s+')

# Reconhece "S01E01", "S1E1", "S123E4567" etc. no final (ou perto do
# final) do título, para separar "título base" de "temporada/episódio".
EPISODE_RE = re.compile(r'^(.*?)\s*S(\d{1,3})E(\d{1,5})\s*$')


def tag_tvg_type(extinf_line: str, title: str) -> str:
    """Insere o atributo tvg-type="series" ou tvg-type="movie" logo no
    início da linha #EXTINF, com base em o título ter (ou não) o padrão
    de temporada/episódio "SxxExx".

    Isso é uma tentativa de fazer players como o TiviMate separarem de
    verdade Filmes e Séries em suas abas próprias — em listas M3U puras
    (sem Xtream Codes) não existe uma forma 100% padronizada/documentada
    de sinalizar isso, mas "tvg-type" é o atributo não-oficial mais
    citado para esse fim. Se o player não reconhecer, o atributo é
    simplesmente ignorado (não quebra nada) e o comportamento fica igual
    ao de antes.
    """
    media_type = "series" if EPISODE_RE.match(title) else "movie"
    return EXTINF_PREFIX_RE.sub(rf'\1 tvg-type="{media_type}" ', extinf_line, count=1)

# Separadores de controle usados só internamente no arquivo temporário de
# ordenação — nunca aparecem em texto normal de M3U, então são seguros
# como delimitadores de campo para o `sort` do sistema.
KEY_FIELD_SEP = "\x1f"    # separa norm/temporada/episódio dentro da chave
RECORD_SEP = "\x01"       # separa a chave do restante do registro

# Nomes usados em execuções anteriores deste projeto — apagados a cada
# execução para não deixar arquivos obsoletos versionados.
LEGACY_VOD_NAMES = ("filmes_series", "filmes", "series", "doramas", "novelas", "mini_series")


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def is_vod_group(group_title: str) -> bool:
    if is_adult_group(group_title):
        return False
    return group_title.strip().lower().startswith(VOD_GROUP_PREFIXES)


def vod_sort_key(title: str) -> str:
    """Gera uma chave de ordenação (título base normalizado + temporada +
    episódio, em campos de largura fixa) para que episódios da mesma
    série fiquem juntos e em ordem certa depois do `sort`.
    """
    m = EPISODE_RE.match(title)
    if m:
        base, season, episode = m.group(1), int(m.group(2)), int(m.group(3))
    else:
        base, season, episode = title, 0, 0
    norm = strip_accents(base).upper()
    norm = re.sub(r"\s+", " ", norm).strip()
    return f"{norm}{KEY_FIELD_SEP}{season:05d}{KEY_FIELD_SEP}{episode:06d}"


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


def external_sort(input_path: Path, output_path: Path) -> None:
    """Ordena um arquivo de registros (chave + \\x01 + resto) por chave,
    usando o utilitário `sort` do sistema — ele faz merge sort em disco
    (spillando para arquivos temporários conforme necessário) em vez de
    carregar tudo na memória de uma vez, o que é essencial num ambiente
    com pouca RAM disponível para um catálogo de ~450 mil itens.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"  # ordenação byte-a-byte, estável e previsível
    subprocess.run(
        [
            "sort",
            "-t", RECORD_SEP,
            "-k1,1",
            "-S", "150M",       # buffer de memória por "run" do sort
            "--parallel=2",
            "-T", str(TMP_DIR), # onde guardar os arquivos temporários do sort
            "-o", str(output_path),
            str(input_path),
        ],
        env=env,
        check=True,
    )


def run() -> dict:
    print("=== Filmes e Séries (VOD) - IPTV Brasil 2026 ===")

    cleanup_old_vod_files()

    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True)
    unsorted_path = TMP_DIR / "vod_unsorted.tmp"
    sorted_path = TMP_DIR / "vod_sorted.tmp"

    try:
        seen_keys: set[str] = set()
        stats = {"por_fonte": []}
        total_collected = 0

        with unsorted_path.open("w", encoding="utf-8") as staging:
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
                    dedup_key = normalize_vod_key(title)
                    if dedup_key and dedup_key in seen_keys:
                        continue
                    sort_key = vod_sort_key(title)
                    tagged_line = tag_tvg_type(extinf_line, title)
                    staging.write(
                        f"{sort_key}{RECORD_SEP}{tagged_line}{RECORD_SEP}{url_line}\n"
                    )
                    added += 1
                    total_collected += 1
                    if dedup_key:
                        seen_keys.add(dedup_key)

                print(f"  -> {total_entries} entradas totais, {vod_count} itens de Filmes/Séries "
                      f"({added} novos, {vod_count - added} já existiam - mesma lista ou fonte anterior)")
                stats["por_fonte"].append((url, vod_count, added))

                # libera a memória do texto da fonte atual antes de baixar a próxima
                del text
                gc.collect()

        # libera a memória do conjunto de chaves de deduplicação — não é
        # mais necessário depois que todas as fontes foram processadas
        del seen_keys
        gc.collect()

        if total_collected == 0:
            raise RuntimeError("nenhum item de VOD encontrado")

        print(f"\nOrdenando {total_collected} itens (agrupando episódios de cada "
              f"série/novela/dorama em sequência)...")
        external_sort(unsorted_path, sorted_path)

        writer = PartedWriter(OUTPUT_BASENAME)
        total_written = 0
        with sorted_path.open("r", encoding="utf-8") as sorted_file:
            for line in sorted_file:
                line = line.rstrip("\n")
                _, extinf_line, url_line = line.split(RECORD_SEP, 2)
                writer.write_entry(extinf_line, url_line)
                total_written += 1
        writer.close()

        if total_written != total_collected:
            print(f"  aviso: {total_collected} itens coletados mas {total_written} "
                  f"gravados após ordenação — verifique separadores de campo")

    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

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
