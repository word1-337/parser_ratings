#!/usr/bin/env python3
"""Поиск страницы эмитента на raexpert.ru по нестрогому названию компании."""

from __future__ import annotations

import argparse
import html
import re
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen

SEARCH_URL_TEMPLATE = "https://raexpert.ru/search/?q={query}"
COMPANY_LINK_RE = re.compile(r"https?://raexpert\.ru/database/companies/\d+/")
RELATIVE_COMPANY_LINK_RE = re.compile(r"/database/companies/\d+/")
TITLE_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
FALLBACK_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
TAG_RE = re.compile(r"(?s)<[^>]+>")

LEGAL_FORM_STOPWORDS = {
    "ао",
    "пао",
    "оао",
    "зао",
    "ооо",
    "гк",
    "пao",
    "oao",
    "zao",
    "ooo",
    "ao",
    "pjsc",
    "jsc",
    "llc",
    "inc",
}


@dataclass(slots=True, frozen=True)
class Candidate:
    url: str
    title: str
    score: float


def fetch_html(url: str, timeout_sec: int = 30, retries: int = 3, pause_sec: float = 1.0) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=timeout_sec) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - любая сетевая ошибка
            last_error = exc
            if attempt < retries:
                time.sleep(pause_sec * attempt)

    raise RuntimeError(f"Не удалось загрузить URL после {retries} попыток: {url}") from last_error


def _strip_tags(value: str) -> str:
    return html.unescape(TAG_RE.sub(" ", value))


def extract_title(page_html: str) -> str:
    for pattern in (TITLE_RE, FALLBACK_TITLE_RE):
        match = pattern.search(page_html)
        if match:
            return " ".join(_strip_tags(match.group(1)).split())
    return ""


def normalize_company_name(value: str) -> str:
    lowered = unicodedata.normalize("NFKC", value).lower().replace("ё", "е")
    lowered = re.sub(r"[\"'`«»„“”()]", " ", lowered)
    lowered = re.sub(r"[^\w\s-]", " ", lowered)
    lowered = lowered.replace("_", " ")

    tokens = [token for token in lowered.split() if token and token not in LEGAL_FORM_STOPWORDS]
    return " ".join(tokens)


def similarity_score(query: str, candidate_title: str) -> float:
    q_norm = normalize_company_name(query)
    c_norm = normalize_company_name(candidate_title)
    if not q_norm or not c_norm:
        return 0.0

    q_tokens = set(q_norm.split())
    c_tokens = set(c_norm.split())
    overlap = len(q_tokens & c_tokens) / max(len(q_tokens), 1)
    ratio = SequenceMatcher(None, q_norm, c_norm).ratio()

    # Весовой баланс: токены важнее, но строковая близость помогает на опечатках.
    return (0.65 * overlap) + (0.35 * ratio)


def extract_company_urls(search_html: str) -> list[str]:
    absolute = COMPANY_LINK_RE.findall(search_html)
    relative = [urljoin("https://raexpert.ru", path) for path in RELATIVE_COMPANY_LINK_RE.findall(search_html)]
    found = absolute + relative

    unique: list[str] = []
    seen: set[str] = set()
    for url in found:
        if url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def find_company_page_url(query: str, min_score: float = 0.45, timeout_sec: int = 30) -> Candidate | None:
    search_url = SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
    search_html = fetch_html(search_url, timeout_sec=timeout_sec)
    company_urls = extract_company_urls(search_html)
    if not company_urls:
        return None

    best: Candidate | None = None
    for url in company_urls:
        page_html = fetch_html(url, timeout_sec=timeout_sec)
        title = extract_title(page_html)
        score = similarity_score(query, title)

        candidate = Candidate(url=url, title=title, score=score)
        if best is None or candidate.score > best.score:
            best = candidate

    if best is None or best.score < min_score:
        return None
    return best


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Находит ссылку вида https://raexpert.ru/database/companies/XXXXXXXXX/ "
            "по нестрогому названию компании (например: 'самолет', 'гк самолет', 'ао самолет')."
        )
    )
    parser.add_argument("query", help="Название компании в свободной форме")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.45,
        help="Порог совпадения [0..1], по умолчанию 0.45",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout в секундах")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    candidate = find_company_page_url(args.query, min_score=args.min_score, timeout_sec=args.timeout)

    if candidate is None:
        print("Не удалось надежно определить страницу эмитента.")
        return 1

    print(candidate.url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
