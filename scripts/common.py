"""
Funções compartilhadas pelos geradores do projeto (download com retry,
parsing de M3U e normalização de nomes/ids para o casamento com EPG).

Mantido em um único lugar para não duplicar lógica entre
generate_epg.py e generate_vod_m3u.py.
"""

from __future__ import annotations

import gzip
import random
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = "Mozilla/5.0 (EPG-Brasil-Generator; +https://github.com/)"
TIMEOUT = 40
RETRIES = 3

# Playlist(s) M3U de origem. O pedido original aponta para CanaisBR06.m3u8;
# mantemos apenas essa por padrão.
PLAYLIST_URLS = [
    "https://raw.githubusercontent.com/Ramys/Iptv-Brasil-2026/master/CanaisBR06.m3u8",
]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

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
    if url.endswith(".gz"):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    text = None
    for enc in ("utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="ignore")
    # Remove um BOM UTF-8 (\ufeff) que alguns provedores de EPG incluem no
    # início do arquivo; se não for removido, quebra checagens de prefixo
    # como `text.startswith("<?xml")` e o parser de XML.
    return text.lstrip("\ufeff")


# ---------------------------------------------------------------------------
# Checagem de saúde de uma fonte (detecta fonte inteira morta/expirada)
# ---------------------------------------------------------------------------

# Descoberta em 2026-07-16: quando o "acesso expirou" no provedor por trás
# de uma lista (credencial revogada, servidor desligado etc.), o servidor
# costuma continuar respondendo HTTP 200/OK só que devolvendo, para
# QUALQUER URL de stream, sempre os mesmos bytes (um vídeo/imagem de erro
# genérico tipo "SEU ACESSO EXPIROU", ou uma página padrão de "Welcome to
# nginx"). Do ponto de vista de um teste de "está no ar? sim/não" isso
# passaria despercebido — por isso comparamos o conteúdo de várias
# amostras entre si: pertencerem todas ao mesmo byte-a-byte é o sinal
# real de que a fonte morreu, mesmo que HTTP diga 200.
#
# Descoberta 2 (mesmo dia, ao testar a própria checagem): alguns
# provedores (ex.: play.pollarplay.com) limitam quantas conexões
# simultâneas/consecutivas um mesmo IP pode abrir, respondendo com um
# JSON de erro tipo {"message":"Maximum number of connections reached"}
# — uma fonte SAUDÁVEL pode disparar esse erro só por estarmos testando
# rápido demais, o que gera falso positivo de "fonte morta". Por isso:
# (a) esperamos um pouco entre cada amostra, (b) reconhecemos esse
# padrão de mensagem para não contar como "conteúdo genérico repetido",
# e (c) se o resultado inicial for "morta", fazemos uma segunda rodada
# (após uma pausa maior) antes de confirmar — só declaramos a fonte
# morta se as duas rodadas concordarem.
HEALTH_CHECK_SAMPLE_SIZE = 10
HEALTH_CHECK_READ_BYTES = 4096      # só os primeiros KB bastam para comparar
HEALTH_CHECK_TIMEOUT = 8
HEALTH_CHECK_MIN_OK_RATIO = 0.34    # abaixo disso, fonte é considerada morta
HEALTH_CHECK_DELAY_BETWEEN = 0.4    # segundos entre cada amostra (evita rate-limit)
HEALTH_CHECK_RETRY_DELAY = 8        # segundos de espera antes da segunda rodada

# Trechos característicos de respostas de "limite de conexões" que alguns
# provedores devolvem com HTTP 200 quando testados rápido demais — não
# devem ser tratados como "fonte morta", e sim como resultado
# inconclusivo desta amostra específica.
RATE_LIMIT_MARKERS = (
    b"maximum number of connections",
    b"too many connections",
    b"connection limit",
    b"max_connections",
)


def _sample_stream_bytes(url: str) -> bytes | None:
    """Baixa só os primeiros bytes de uma URL de stream (rápido, não
    baixa o vídeo inteiro) e devolve o conteúdo, ou None em caso de erro
    de rede/timeout.

    IMPORTANTE: mesmo quando o servidor responde com um HTTP de erro
    (4xx/5xx), ainda lemos o corpo da resposta — alguns provedores (ex.:
    play.pollarplay.com) respondem 500 com um corpo tipo
    {"message":"Maximum number of connections reached"} quando o limite
    de conexões simultâneas é atingido, e achamos isso mesmo estando com
    a fonte saudável, só testando rápido demais. Ler o corpo permite ao
    chamador (check_source_health) reconhecer esse padrão de rate-limit
    e não confundir com "fonte morta" de verdade.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HEALTH_CHECK_TIMEOUT) as resp:
            return resp.read(HEALTH_CHECK_READ_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            return exc.read(HEALTH_CHECK_READ_BYTES)
        except Exception:
            return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _run_health_pass(stream_urls: list[str], sample_size: int) -> tuple[bool, int, int, int]:
    """Executa uma rodada de amostragem e devolve (parece_viva,
    ok_count, failures, rate_limited_count) sem decidir sozinha — quem
    decide é check_source_health(), que pode rodar isto mais de uma vez.
    """
    sample = random.sample(stream_urls, min(sample_size, len(stream_urls)))
    contents: list[bytes] = []
    failures = 0
    rate_limited = 0

    for i, url in enumerate(sample):
        if i > 0:
            time.sleep(HEALTH_CHECK_DELAY_BETWEEN)
        content = _sample_stream_bytes(url)
        if content is None or len(content) == 0:
            failures += 1
            continue
        lowered = content.lower()
        if any(marker in lowered for marker in RATE_LIMIT_MARKERS):
            rate_limited += 1
            continue
        contents.append(content)

    ok_count = len(contents)
    considered = ok_count + failures  # exclui as "inconclusivas" por rate-limit
    ok_ratio = (ok_count / considered) if considered else 1.0  # sem dado -> não penaliza

    duplicated = 0
    if len(contents) >= 2:
        seen: dict[bytes, int] = {}
        for c in contents:
            seen[c] = seen.get(c, 0) + 1
        duplicated = max(seen.values())

    is_alive = True
    if considered > 0 and ok_ratio < HEALTH_CHECK_MIN_OK_RATIO:
        is_alive = False
    if len(contents) >= 3 and duplicated >= max(3, len(contents) // 2):
        is_alive = False

    return is_alive, ok_count, failures, rate_limited


def check_source_health(stream_urls: list[str], label: str = "") -> tuple[bool, str]:
    """Testa uma amostra aleatória de URLs de stream de uma fonte com
    requisições HTTP reais, para decidir se a fonte inteira está viva ou
    morta (credencial expirada, servidor fora do ar etc.) — sem precisar
    testar TODOS os itens, o que seria lento demais para rodar a cada
    atualização automática.

    Critério de "morta": muitas amostras retornam exatamente o mesmo
    conteúdo entre si (sinal de um único arquivo de erro genérico sendo
    reciclado para todas as URLs) ou falham (timeout/erro HTTP). Uma
    fonte saudável tem vídeos DIFERENTES uns dos outros. Respostas de
    "limite de conexões" (rate-limit do provedor, não relacionado à
    saúde real da fonte) são ignoradas na contagem, e um resultado
    inicial de "morta" é sempre confirmado com uma segunda rodada antes
    de ser aceito, para não confundir uma fonte saudável só temporariamente
    congestionada com uma fonte de verdade fora do ar.

    Retorna (esta_viva, motivo) — "esta_viva" é usado pelo chamador para
    decidir se processa essa fonte nesta execução ou pula (sem removê-la
    da lista de fontes: na próxima atualização automática ela é testada
    de novo do zero, então volta sozinha se o provedor original voltar a
    funcionar).
    """
    if not stream_urls:
        return False, "nenhuma URL de stream para testar"

    prefix = f"[{label}] " if label else ""

    alive1, ok1, fail1, rl1 = _run_health_pass(stream_urls, HEALTH_CHECK_SAMPLE_SIZE)
    if alive1:
        return True, (f"{prefix}{ok1} ok, {fail1} falhas, {rl1} rate-limited "
                       f"(1ª rodada) — conteúdo variado")

    # Primeira rodada sugeriu "morta" — confirma com uma segunda rodada
    # após uma pausa maior, para não confundir rate-limit/instabilidade
    # passageira do provedor com a fonte estando realmente fora do ar.
    time.sleep(HEALTH_CHECK_RETRY_DELAY)
    alive2, ok2, fail2, rl2 = _run_health_pass(stream_urls, HEALTH_CHECK_SAMPLE_SIZE)
    if alive2:
        return True, (f"{prefix}1ª rodada indicou morta ({ok1} ok/{fail1} falhas), "
                       f"mas 2ª rodada confirmou que está viva ({ok2} ok/{fail2} "
                       f"falhas) — provável instabilidade passageira, não fonte morta")

    return False, (f"{prefix}confirmado morta em 2 rodadas — 1ª: {ok1} ok/{fail1} "
                    f"falhas/{rl1} rate-limited; 2ª: {ok2} ok/{fail2} falhas/"
                    f"{rl2} rate-limited")


# ---------------------------------------------------------------------------
# M3U parsing
# ---------------------------------------------------------------------------

@dataclass
class Channel:
    tvg_id: str
    tvg_name: str
    display_name: str
    group_title: str
    tvg_logo: str = ""
    url: str = ""


ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


def parse_m3u(text: str) -> list[Channel]:
    """Faz o parsing de um M3U, retornando um Channel por entrada #EXTINF
    (com a URL do stream correspondente já anexada)."""
    channels: list[Channel] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR_RE.findall(line))
            display_name = line.rsplit(",", 1)[-1].strip()
            url_line = lines[i + 1] if i + 1 < len(lines) else ""
            channels.append(
                Channel(
                    tvg_id=attrs.get("tvg-id", "").strip(),
                    tvg_name=attrs.get("tvg-name", "").strip(),
                    display_name=display_name,
                    group_title=attrs.get("group-title", "").strip(),
                    tvg_logo=attrs.get("tvg-logo", "").strip(),
                    url=url_line.strip() if url_line and not url_line.startswith("#") else "",
                )
            )
            i += 2
        else:
            i += 1
    return channels


# ---------------------------------------------------------------------------
# Normalização de nomes/ids (para o casamento M3U <-> EPG)
# ---------------------------------------------------------------------------

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


# Sufixos de qualidade/formato que aparecem "colados" ao nome de um canal
# para indicar apenas uma variante técnica do mesmo sinal (ex.: "TNT HD",
# "TNT FHD", "TNT H265", "TNT [4K]"). Usado só para agrupar variações do
# MESMO canal — é intencionalmente mais conservador que normalize_name()
# e não remove palavras que fazem parte do nome real (TV, Brasil, Canal),
# para não confundir canais diferentes (ex.: "TV Brasil" x "Canal Brasil").
QUALITY_SUFFIXES = {
    'HD', 'FHD', 'UHD', 'SD', '4K', 'H265', 'H264', 'ALT', 'DUAL', 'AUDIO',
    'LEGENDADO', 'LEG', 'DUBLADO', 'DUB', 'BACKUP',
}


def normalize_family_name(name: str) -> str:
    """Normaliza um nome de canal preservando as palavras do nome real,
    removendo apenas marcadores de qualidade/formato. Duas variantes do
    mesmo canal (ex.: "Globo HD" e "Globo FHD H265") caem na mesma chave;
    canais genuinamente diferentes (ex.: "TV Brasil" e "Canal Brasil")
    continuam com chaves distintas.
    """
    if not name:
        return ''
    name = name.strip()
    name = re.sub(r'\[[^\]]*\]', ' ', name)
    name = re.sub(r'\([^)]*\)', ' ', name)
    name = strip_accents(name).upper()
    name = re.sub(r'[._\-/|!]+', ' ', name)
    tokens = [t for t in re.split(r'\s+', name) if t]
    tokens = [re.sub(r'[^A-Z0-9&+]', '', t) for t in tokens]
    tokens = [t for t in tokens if t and t not in QUALITY_SUFFIXES]
    return ' '.join(tokens)


# ---------------------------------------------------------------------------
# Filtro de conteúdo adulto (compartilhado entre canais ao vivo e VOD)
# ---------------------------------------------------------------------------

# As listas do repositório marcam conteúdo adulto/pornográfico de forma
# consistente através do group-title (nunca só pelo título do item, que
# poderia gerar falsos positivos como o documentário "Pornhub: Sexo
# Bilionário", a minissérie "Gêmeas Trans", o canal musical "Stingray Hot
# Country" ou o filme de ação "xXx: Reativado"). Por isso o filtro
# verifica apenas o nome do grupo, nunca o título do item.
ADULT_GROUP_KEYWORDS = ("adulto", "+18", "xxx", "onlyfans")


def is_adult_group(group_title: str) -> bool:
    g = group_title.strip().lower()
    return any(k in g for k in ADULT_GROUP_KEYWORDS)


def normalize_vod_key(name: str) -> str:
    """Normaliza o título de um item de VOD (filme/episódio) só o
    suficiente para detectar duplicatas exatas entre listas diferentes
    (acentos, maiúsculas/minúsculas e espaços extras). Marcadores como
    "[L]"/"[LEG]" (legendado) e "[4K]" são preservados de propósito: uma
    versão legendada ou 4K de um título NÃO é considerada duplicata da
    versão "normal" e continua saindo como um item separado na playlist.
    """
    if not name:
        return ''
    key = strip_accents(name).upper()
    key = re.sub(r'\s+', ' ', key).strip()
    return key

