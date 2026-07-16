#!/usr/bin/env python3
"""
Completa pôsteres (tvg-logo) que estão faltando nos arquivos de VOD
(filmes_e_series*.m3u8), buscando no TMDB (The Movie Database).

Por que só pôster, e não sinopse: o formato M3U não tem campo de
descrição/sinopse — só tvg-id, tvg-name, tvg-logo e group-title. Não há
como fazer um player que lê M3U mostrar sinopse, então este script só
mexe no `tvg-logo` (a única coisa que o M3U realmente aproveita).

Requer a variável de ambiente TMDB_API_KEY com uma chave gratuita do
TMDB (cadastro em https://www.themoviedb.org/settings/api). Se a
variável não estiver definida, o script não faz nada (sai sem erro) —
assim o pipeline principal (update_all.py) continua funcionando mesmo
sem a chave configurada.

CRITÉRIO DE CORRESPONDÊNCIA (rigoroso, para nunca colocar pôster errado):
1. Extrai o ano do título, se houver algo como "(1989)".
2. Busca no TMDB (filme: /search/movie; série: /search/tv) o título
   limpo (sem ano, sem marcadores [L]/[LEG]/[4K]).
3. De todos os resultados retornados, só aceita um candidato se:
   - o nome dele, normalizado (sem acento/maiúsculas), for EXATAMENTE
     igual ao título buscado (normalizado) — nunca aceita "parecido";
   - e, se o título original tinha um ano, o ano do candidato bate
     (tolerância de ±1 ano, pra cobrir divergência de data de estreia
     local vs. original).
4. Se houver mais de um candidato que passe nesses critérios, escolhe o
   com mais votos (vote_count) — não a "popularidade" (que pode
   favorecer um resultado errado mas mais famoso).
5. Se nada passar com confiança, o item fica sem pôster (não arrisca).

PÔSTERES "GENÉRICOS"/RECICLADOS (bug encontrado na fonte original, não
introduzido por este projeto): algumas listas de origem, quando não têm
o pôster real catalogado para um título, reciclam a imagem de outro
item qualquer em vez de deixar em branco. O efeito visível para quem
usa a playlist é grave: um app de IPTV pode mostrar, por exemplo, o
pôster de uma novela chinesa dentro do card da série "A Sombra do
Batman". Detectamos isso contando, para cada URL de pôster, quantos
títulos BASE distintos (nome normalizado, sem contar variação de
temporada/episódio) a usam — uma imagem de pôster de verdade pertence a
UM título só; se a mesma URL aparece em 2 ou mais títulos diferentes,
é quase certamente uma imagem genérica/reciclada, não a capa real de
nenhum deles (`find_generic_poster_urls()`). Esses itens são tratados
como "sem pôster" e passam pela mesma busca rigorosa no TMDB acima —
MAS, para não piorar nada, um pôster genérico só é substituído quando
uma nova correspondência confiável é encontrada; se a busca falhar, o
pôster antigo (ainda que genérico) permanece intacto, sem risco de
regressão.

CACHE: todo resultado (inclusive "não encontrado") é salvo em
tmdb_poster_cache.json, para que atualizações futuras não precisem
refazer buscas já feitas — só títulos novos gastam cota da API.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = ROOT / "playlists"
CACHE_FILE = ROOT / "scripts" / "tmdb_poster_cache.json"

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
REQUEST_TIMEOUT = 15
# TMDB permite ~40 req/s; ficamos bem abaixo disso de propósito para não
# arriscar erro 429 nem sobrecarregar a API de graça.
SLEEP_BETWEEN_REQUESTS = 0.15

NAME_RE = re.compile(r'tvg-name="([^"]*)"')
LOGO_RE = re.compile(r'tvg-logo="([^"]*)"')
EPISODE_RE = re.compile(r'^(.*?)\s*S(\d{1,3})E(\d{1,5})\s*$')

# Marcadores de legendado/4K aparecem em vários formatos nas listas de
# origem: "[L]", "[LEG]", "[4K]", mas também soltos sem colchetes tipo
# "(L)", "(LE)" ou só " L" no fim do título. Removidos antes de procurar
# o ano, para não atrapalhar (ex.: "Apocalypto 2006 (L)" só encontra o
# ano corretamente se o "(L)" já tiver sido removido antes).
MARKER_PATTERNS = [
    re.compile(r'\s*\[(?:L|LEG|LEGENDADO|4K)\]\s*', re.IGNORECASE),
    re.compile(r'\s*\((?:L|LE|LEG|LEGENDADO)\)\s*$', re.IGNORECASE),
    re.compile(r'\s+L\s*$'),  # "Hannah Montana: ... Aniversário L"
    re.compile(r'\s+4K\s*$', re.IGNORECASE),  # "Mufasa: O Rei Leão 2024 4K"
]

# Anos aparecem em vários formatos nas listas de origem: "(1989)",
# "( 2021 )" (com espaços dentro dos parênteses), "- 2022" ou
# "- Ultimato - 2009" (hífen antes de um ano no final do título), ou só
# "Nome 2022" (ano solto, sem separador, no final). Tentamos esses
# padrões em ordem até um bater — sempre exigindo que o ano fique bem no
# final da string (depois de já remover marcadores [L]/[LEG]/[4K]), para
# não confundir com números que fazem parte do próprio título (ex.:
# "1921", "Corrida Mortal 3").
YEAR_PATTERNS = [
    re.compile(r'\(\s*((?:19|20)\d{2})\s*\)\s*$'),   # (1989) ou ( 2021 ) no final
    re.compile(r'[-–—]\s*((?:19|20)\d{2})\s*$'),      # "... - 2022" no final
    re.compile(r'\(\s*((?:19|20)\d{2})\s*\)'),        # (1989) em qualquer posição
    # Ano solto no final, sem separador (ex.: "Apocalypto 2006",
    # "Control: O Poder da Mente 2022") — exige pelo menos uma outra
    # palavra antes, para não confundir um título que É só um número
    # de 4 dígitos (ex.: um filme chamado apenas "1921").
    re.compile(r'(?<=\w)\s+((?:19|20)\d{2})\s*$'),
]


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_title(s: str) -> str:
    s = strip_accents(s).upper()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_title(raw: str) -> tuple[str, str | None]:
    """Remove marcadores [L]/[LEG]/(L)/[4K] e o ano (em qualquer um dos
    formatos usados nas listas de origem) do título, devolvendo (título
    limpo, ano ou None).
    """
    t = raw
    for pattern in MARKER_PATTERNS:
        t = pattern.sub(" ", t).rstrip()

    year = None
    for pattern in YEAR_PATTERNS:
        m = pattern.search(t)
        if m:
            year = m.group(1)
            t = t[: m.start()] + " " + t[m.end():]
            break

    # remove hífen/travessão soltos que sobraram sozinhos no final depois
    # de tirar o ano (ex.: "100 Medos - 2022" -> "100 Medos -" ainda
    # precisa virar "100 Medos")
    t = re.sub(r'[-–—]\s*$', ' ', t)
    t = re.sub(r"\s+", " ", t).strip()
    return t, year



def http_get_json(url: str) -> dict | None:
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "epg-br-tmdb-enrich/1.0"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(1 * (attempt + 1))
    return None


def search_tmdb(title: str, year: str | None, media_type: str) -> str | None:
    """Busca no TMDB (media_type = 'movie' ou 'tv') e devolve a URL do
    pôster do melhor candidato que bater com confiança, ou None.
    """
    endpoint = "movie" if media_type == "movie" else "tv"
    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "language": "pt-BR",
        "include_adult": "false",
    }
    if year and media_type == "movie":
        params["year"] = year
    url = f"https://api.themoviedb.org/3/search/{endpoint}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    time.sleep(SLEEP_BETWEEN_REQUESTS)
    if not data:
        return None

    target_norm = norm_title(title)
    results = data.get("results", [])
    candidates = []
    for r in results:
        name = r.get("title") if media_type == "movie" else r.get("name")
        if not name or norm_title(name) != target_norm:
            continue
        date_field = r.get("release_date") if media_type == "movie" else r.get("first_air_date")
        cand_year = date_field[:4] if date_field and len(date_field) >= 4 else None
        if year and cand_year:
            try:
                if abs(int(cand_year) - int(year)) > 1:
                    continue
            except ValueError:
                pass
        poster = r.get("poster_path")
        if not poster:
            continue
        candidates.append((r.get("vote_count", 0) or 0, poster))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    top_votes = candidates[0][0]
    # Exige pelo menos 1 voto real no TMDB — com 0 votos não há sinal
    # nenhum de que aquele é o candidato "certo" (muitas vezes existem
    # vários registros diferentes com o mesmo nome genérico e 0 votos
    # cada, e escolher o primeiro seria essencialmente aleatório).
    if top_votes < 1:
        return None
    # Se dois ou mais candidatos empatam no topo, não há como desempatar
    # com confiança — melhor não colocar pôster do que arriscar errado.
    tied_at_top = sum(1 for votes, _ in candidates if votes == top_votes)
    if tied_at_top > 1:
        return None
    return TMDB_IMAGE_BASE + candidates[0][1]


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")


# Um pôster de verdade pertence a um único título. Se a mesma URL
# aparece associada a este número (ou mais) de títulos BASE distintos
# na playlist inteira, tratamos como "genérico/reciclado" da fonte
# original, não como o pôster real de nenhum desses títulos.
GENERIC_POSTER_MIN_DISTINCT_TITLES = 2


def _title_key_from_line(line: str) -> tuple[str, str | None, str] | None:
    """Extrai (título_limpo, ano, media_type) de uma linha #EXTINF, ou
    None se não tiver tvg-name utilizável.
    """
    name_m = NAME_RE.search(line)
    if not name_m or not name_m.group(1).strip():
        return None
    raw_name = name_m.group(1)
    ep_m = EPISODE_RE.match(raw_name)
    is_series = bool(ep_m)
    base_raw = ep_m.group(1) if ep_m else raw_name
    clean, year = clean_title(base_raw)
    if not clean:
        return None
    return clean, year, ("tv" if is_series else "movie")


def find_generic_poster_urls(paths: list[Path]) -> set[str]:
    """Varre todos os arquivos e devolve o conjunto de URLs de tvg-logo
    que aparecem associadas a 2 ou mais títulos BASE diferentes — sinal
    de que a fonte original reciclou uma imagem genérica em vez de
    catalogar o pôster real de cada um.
    """
    poster_to_titles: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#EXTINF"):
                    continue
                logo_m = LOGO_RE.search(line)
                if not logo_m or not logo_m.group(1).strip():
                    continue
                info = _title_key_from_line(line)
                if not info:
                    continue
                clean, _year, _media_type = info
                poster_to_titles[logo_m.group(1).strip()].add(norm_title(clean))

    return {
        url
        for url, titles in poster_to_titles.items()
        if len(titles) >= GENERIC_POSTER_MIN_DISTINCT_TITLES
    }


def collect_missing_titles(
    paths: list[Path], generic_posters: set[str]
) -> dict[str, tuple[str, str | None, str]]:
    """Varre os arquivos e devolve {chave_cache: (título_limpo, ano,
    media_type)} para títulos (filme ou série-base) que aparecem com
    tvg-logo vazio OU com um pôster "genérico" reciclado (ver
    find_generic_poster_urls) em pelo menos uma ocorrência.
    """
    missing: dict[str, tuple[str, str | None, str]] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#EXTINF"):
                    continue
                logo_m = LOGO_RE.search(line)
                has_logo = bool(logo_m and logo_m.group(1).strip())
                if has_logo and logo_m.group(1).strip() not in generic_posters:
                    continue  # já tem pôster de verdade (não genérico)
                info = _title_key_from_line(line)
                if not info:
                    continue
                clean, year, media_type = info
                key = f"{media_type}::{norm_title(clean)}::{year or ''}"
                missing[key] = (clean, year, media_type)
    return missing


def apply_posters(
    paths: list[Path], resolved: dict[str, str], generic_posters: set[str]
) -> int:
    """Reescreve os arquivos substituindo tvg-logo="" (ou um pôster
    "genérico" reciclado) por um pôster resolvido, quando existir.
    Retorna quantos itens foram atualizados.

    Importante: um pôster genérico só é trocado se uma correspondência
    NOVA e confiável foi encontrada (está em `resolved`) — se a busca no
    TMDB não achar nada confiável para aquele título, o pôster antigo
    (mesmo que genérico) é mantido intacto, para nunca piorar o que já
    existia.
    """
    updated_total = 0
    for path in paths:
        if not path.exists():
            continue
        lines_out = []
        changed = False
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("#EXTINF"):
                    logo_m = LOGO_RE.search(line)
                    has_logo = bool(logo_m and logo_m.group(1).strip())
                    needs_fix = not has_logo or logo_m.group(1).strip() in generic_posters
                    if needs_fix:
                        info = _title_key_from_line(line)
                        if info:
                            clean, year, media_type = info
                            key = f"{media_type}::{norm_title(clean)}::{year or ''}"
                            poster = resolved.get(key)
                            if poster:
                                if logo_m:
                                    line = line[:logo_m.start(1)] + poster + line[logo_m.end(1):]
                                else:
                                    line = line.replace(
                                        "#EXTINF:-1 ", f'#EXTINF:-1 tvg-logo="{poster}" ', 1
                                    )
                                updated_total += 1
                                changed = True
                lines_out.append(line)
        if changed:
            path.write_text("".join(lines_out), encoding="utf-8")
    return updated_total


def run() -> dict:
    if not TMDB_API_KEY:
        print("TMDB_API_KEY não definida — pulando enriquecimento de pôsteres (opcional).")
        return {"tmdb_consultas": 0, "tmdb_posteres_completados": 0}

    paths = sorted(PLAYLISTS_DIR.glob("filmes_e_series*.m3u8"))
    if not paths:
        print("Nenhum arquivo filmes_e_series*.m3u8 encontrado — pulando enriquecimento TMDB.")
        return {"tmdb_consultas": 0, "tmdb_posteres_completados": 0}

    print("=== Completando pôsteres faltantes/genéricos via TMDB ===")

    print("Procurando pôsteres 'genéricos' (mesma imagem reciclada em "
          "vários títulos diferentes, um bug da fonte original)...")
    generic_posters = find_generic_poster_urls(paths)
    print(f"Pôsteres genéricos detectados: {len(generic_posters)}")

    missing = collect_missing_titles(paths, generic_posters)
    print(f"Títulos únicos sem pôster (vazio ou genérico) a resolver: {len(missing)}")

    cache = load_cache()
    resolved: dict[str, str] = {}
    queries = 0
    hits = 0
    misses = 0

    for i, (key, (clean, year, media_type)) in enumerate(missing.items(), start=1):
        if key in cache:
            if cache[key]:
                resolved[key] = cache[key]
            continue
        queries += 1
        poster = search_tmdb(clean, year, media_type)
        cache[key] = poster or ""
        if poster:
            resolved[key] = poster
            hits += 1
        else:
            misses += 1
        if queries % 200 == 0:
            print(f"  ... {queries} consultas feitas ao TMDB até agora "
                  f"({hits} encontrados, {misses} não encontrados)")
            save_cache(cache)  # salva incrementalmente, por segurança

    save_cache(cache)
    print(f"Consultas novas ao TMDB: {queries} ({hits} encontrados, {misses} não encontrados)")
    print(f"Total de títulos com pôster resolvido (novo + cache): {len(resolved)}")

    updated = apply_posters(paths, resolved, generic_posters)
    print(f"Itens de VOD atualizados com novo pôster: {updated}")

    return {"tmdb_consultas": queries, "tmdb_posteres_completados": updated}


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
