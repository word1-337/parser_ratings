#!/usr/bin/env python3
"""Парсер кредитных рейтингов долговых инструментов с raexpert.ru.

Особенности:
- не требует внешних библиотек (только stdlib),
- умеет обходить несколько страниц рейтингов (если в HTML есть ссылки пагинации),
- извлекает эмиссию, кредитный рейтинг и дату рейтингового действия,
- сохраняет результат в JSON и опционально в CSV.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://raexpert.ru/ratings/debt_inst/"
DEFAULT_TIMEOUT_SEC = 45
DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
# Оставляем только реальные рейтинги формата ruAAA / ruA- / ruBB+ / ruD и т.п.
RATING_RE = re.compile(r"(?<!\w)ru(?:AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|CC|C|D)(?!\w)", re.IGNORECASE)
WITHDRAWN_RE = re.compile(r"\bотозван\b", re.IGNORECASE)
PAGE_HINT_RE = re.compile(r"(?:[?&](?:PAGEN_[^=]+|page)=\d+)", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class RatingRecord:
    issue: str
    rating: str
    date: str
    source_url: str


def _normalize_spaces(value: str) -> str:
    normalized = (
        value.replace("\xa0", " ")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("‑", "-")
    )
    return " ".join(normalized.split())


def fetch_html(url: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC, retries: int = 3, pause_sec: float = 1.2) -> str:
    """Загружает HTML с повторами попыток и User-Agent, чтобы снизить риск блокировок."""
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
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout_sec) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - фиксируем любую сетевую ошибку
            last_error = exc
            if attempt < retries:
                time.sleep(pause_sec * attempt)

    raise RuntimeError(f"Не удалось загрузить URL после {retries} попыток: {url}") from last_error


def html_to_text(source_html: str) -> str:
    """Грубое преобразование HTML в текст, достаточное для извлечения таблицы рейтингов."""
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", source_html)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article|table|tbody|thead|ul|ol)>", "\n", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return cleaned


def _pick_rating(details: str) -> str | None:
    rating_match = RATING_RE.search(details)
    if rating_match:
        return rating_match.group(0)

    if WITHDRAWN_RE.search(details):
        return "отозван"

    return None


def parse_records_from_text(text: str, source_url: str) -> list[RatingRecord]:
    """Парсинг записей из видимого текста страницы.

    На странице записи идут парами строк:
    - "Облигации ..."
    - "<эмитент> ruA-, 17.04.2026 ruA- — 17.04.2026"
    """
    lines = [_normalize_spaces(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    records: list[RatingRecord] = []

    for idx, line in enumerate(lines):
        if not line.startswith("Облигации "):
            continue

        issue = line

        # Собираем следующие 1-3 строки как блок деталей, пока не встретится новая эмиссия.
        details_parts: list[str] = []
        for look_ahead in range(idx + 1, min(idx + 4, len(lines))):
            candidate = lines[look_ahead]
            if candidate.startswith("Облигации "):
                break
            details_parts.append(candidate)

        details = " ".join(details_parts)
        if not details:
            continue

        date_match = DATE_RE.search(details)
        rating = _pick_rating(details)
        if not date_match or not rating:
            continue

        records.append(
            RatingRecord(
                issue=issue,
                rating=rating,
                date=date_match.group(0),
                source_url=source_url,
            )
        )

    return deduplicate_records(records)


def deduplicate_records(records: Iterable[RatingRecord]) -> list[RatingRecord]:
    unique: list[RatingRecord] = []
    seen: set[tuple[str, str, str]] = set()

    for item in records:
        key = (item.issue, item.rating, item.date)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique


def find_pagination_urls(source_html: str, base_url: str) -> list[str]:
    """Ищет ссылки пагинации в HTML и возвращает уникальные URL (включая base_url)."""
    hrefs = re.findall(r'(?i)href=["\']([^"\']+)["\']', source_html)
    pages = {base_url}

    for href in hrefs:
        if PAGE_HINT_RE.search(href):
            pages.add(urljoin(base_url, href))

    # Стабильный порядок: сначала базовая, потом остальные по строке.
    ordered = [base_url] + sorted(url for url in pages if url != base_url)
    return ordered


def collect_records(max_pages: int | None = None, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> list[RatingRecord]:
    """Собирает записи с первой и (если найдены) дополнительных страниц."""
    first_html = fetch_html(BASE_URL, timeout_sec=timeout_sec)
    page_urls = find_pagination_urls(first_html, BASE_URL)

    if max_pages is not None:
        page_urls = page_urls[:max_pages]

    all_records: list[RatingRecord] = []

    for page_url in page_urls:
        current_html = first_html if page_url == BASE_URL else fetch_html(page_url, timeout_sec=timeout_sec)
        text = html_to_text(current_html)
        parsed = parse_records_from_text(text, source_url=page_url)
        all_records.extend(parsed)

    return deduplicate_records(all_records)


def write_json(records: Iterable[RatingRecord], output: Path) -> None:
    payload = [asdict(record) for record in records]
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(records: Iterable[RatingRecord], output: Path) -> None:
    with output.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=["issue", "rating", "date", "source_url"])
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Парсер кредитного рейтинга и даты для https://raexpert.ru/ratings/debt_inst/"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("raexpert_debt_ratings.json"),
        help="Путь к JSON файлу результата (по умолчанию: raexpert_debt_ratings.json)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Дополнительно сохранить результат в CSV",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Ограничить количество страниц для обхода (по умолчанию: все найденные)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"HTTP timeout в секундах (по умолчанию: {DEFAULT_TIMEOUT_SEC})",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    records = collect_records(max_pages=args.max_pages, timeout_sec=args.timeout)
    if not records:
        raise RuntimeError(
            "Не удалось извлечь записи рейтингов. Проверьте доступность сайта и актуальность шаблона парсинга."
        )

    write_json(records, args.output)
    if args.csv:
        write_csv(records, args.csv)

    print(f"Сохранено записей: {len(records)}")
    print(f"JSON: {args.output}")
    if args.csv:
        print(f"CSV: {args.csv}")

    for item in records[:5]:
        print(f"- {item.issue} | {item.rating} | {item.date}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
