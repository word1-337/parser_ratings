#!/usr/bin/env python3
"""Парсер кредитных рейтингов долговых инструментов с raexpert.ru.

Извлекает по выпускам:
- эмиссию,
- эмитента,
- рейтинг,
- дату рейтингового действия,
- ссылку на последний актуальный (на дату запуска) пресс-релиз по эмитенту.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from dataclasses import asdict, dataclass, replace
from html.parser import HTMLParser
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://raexpert.ru/ratings/debt_inst/"
DEFAULT_TIMEOUT_SEC = 45
DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
RATING_RE = re.compile(r"(?<!\w)ru(?:AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|CC|C|D)(?!\w)", re.IGNORECASE)
WITHDRAWN_RE = re.compile(r"\bотозван\b", re.IGNORECASE)
PAGE_HINT_RE = re.compile(r"(?:[?&](?:PAGEN_[^=]+|page)=\d+)", re.IGNORECASE)
RELEASE_HREF_RE = re.compile(r"href=[\"\']([^\"\']*/releases/[^\"\']*)[\"\']", re.IGNORECASE)
TR_RE = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")


class AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current_href: str | None = None
        self._current_chunks: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value
                break
        self._current_href = href
        self._current_chunks = []

    def handle_data(self, data: str) -> None:
        if self._current_href is None:
            return
        self._current_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        text = _normalize_spaces("".join(self._current_chunks))
        self.anchors.append((text, self._current_href))
        self._current_href = None
        self._current_chunks = []


def parse_records_from_anchor_stream(source_html: str, base_url: str) -> list[RatingRecord]:
    """Fallback для вёрстки без <tr>: извлекаем записи из последовательности ссылок."""
    parser = AnchorCollector()
    parser.feed(source_html)
    anchors = [(txt, urljoin(base_url, href)) for txt, href in parser.anchors if txt]

    issue_indices = [idx for idx, (txt, _) in enumerate(anchors) if txt.startswith("Облигации ")]
    if not issue_indices:
        return []

    records: list[RatingRecord] = []
    for pos, issue_idx in enumerate(issue_indices):
        issue_text = anchors[issue_idx][0]
        end = issue_indices[pos + 1] if pos + 1 < len(issue_indices) else len(anchors)
        segment = anchors[issue_idx + 1 : end]
        if not segment:
            continue

        joined = " ".join(item[0] for item in segment)
        rating = _pick_rating(joined)
        date_match = DATE_RE.search(joined)

        release_candidates: list[tuple[date, str]] = []
        for txt, href in segment:
            if "/releases/" not in href:
                continue
            m = DATE_RE.search(txt)
            if not m:
                continue
            release_candidates.append((_parse_date(m.group(0)), href))

        if not rating or not date_match:
            continue

        issuer = ""
        issuer_url = ""
        for txt, href in segment:
            if txt.startswith("Облигации "):
                continue
            if DATE_RE.search(txt):
                continue
            if _pick_rating(txt):
                continue
            if "/releases/" in href:
                continue
            issuer = txt
            issuer_url = href
            break

        if not issuer:
            issuer = _pick_issuer(joined)

        if not issuer:
            continue

        release_href = ""
        release_day = _parse_date(date_match.group(0))
        if release_candidates:
            release_candidates.sort(key=lambda item: item[0], reverse=True)
            release_day, release_href = release_candidates[0]
        elif issuer_url:
            release_href = issuer_url
        else:
            release_href = base_url

        records.append(
            RatingRecord(
                issue=issue_text,
                issuer=issuer,
                issuer_url=issuer_url,
                rating=rating,
                date=release_day.strftime("%d.%m.%Y"),
                press_release_url=release_href,
            )
        )

    return deduplicate_records(records)


@dataclass(slots=True, frozen=True)
class RatingRecord:
    issue: str
    issuer: str
    issuer_url: str
    rating: str
    date: str
    press_release_url: str


def _normalize_spaces(value: str) -> str:
    normalized = (
        value.replace("\xa0", " ")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("‑", "-")
    )
    return " ".join(normalized.split())


def _strip_tags(raw_html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article|table|tbody|thead|ul|ol|td|th)>", "\n", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return cleaned


def fetch_html(url: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC, retries: int = 3, pause_sec: float = 1.2) -> str:
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
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                time.sleep(pause_sec * attempt)

    raise RuntimeError(f"Не удалось загрузить URL после {retries} попыток: {url}") from last_error


def _pick_rating(details: str) -> str | None:
    rating_match = RATING_RE.search(details)
    if rating_match:
        return rating_match.group(0)
    if WITHDRAWN_RE.search(details):
        return "отозван"
    return None


def _pick_issuer(details: str) -> str:
    rating_match = RATING_RE.search(details)
    if rating_match:
        return _normalize_spaces(details[: rating_match.start()].strip(" ,"))

    withdrawn_match = WITHDRAWN_RE.search(details)
    if withdrawn_match:
        return _normalize_spaces(details[: withdrawn_match.start()].strip(" ,"))

    return ""


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y").date()


def find_pagination_urls(source_html: str, base_url: str) -> list[str]:
    hrefs = re.findall(r'(?i)href=["\']([^"\']+)["\']', source_html)
    pages = {base_url}
    for href in hrefs:
        if PAGE_HINT_RE.search(href):
            pages.add(urljoin(base_url, href))
    return [base_url] + sorted(url for url in pages if url != base_url)


def parse_records_from_html(source_html: str, base_url: str) -> list[RatingRecord]:
    """Парсит таблицу рейтингов и подтягивает ссылку на пресс-релиз из строки детали."""
    records: list[RatingRecord] = []
    current_issue: str | None = None

    for row_html in TR_RE.findall(source_html):
        row_text = _normalize_spaces(_strip_tags(row_html))
        if not row_text:
            continue

        if row_text.startswith("Облигации "):
            current_issue = row_text
            continue

        if current_issue is None:
            continue

        date_match = DATE_RE.search(row_text)
        rating = _pick_rating(row_text)
        if not date_match or not rating:
            continue

        issuer = _pick_issuer(row_text)
        if not issuer:
            continue

        release_match = RELEASE_HREF_RE.search(row_html)
        release_url = urljoin(base_url, release_match.group(1)) if release_match else ""
        company_match = re.search(r"href=[\"\']([^\"\']*/database/companies/\d+/?)[\"\']", row_html, re.IGNORECASE)
        issuer_url = urljoin(base_url, company_match.group(1)) if company_match else ""
        if not release_url:
            release_url = issuer_url

        records.append(
            RatingRecord(
                issue=current_issue,
                issuer=issuer,
                issuer_url=issuer_url,
                rating=rating,
                date=date_match.group(0),
                press_release_url=release_url,
            )
        )
        current_issue = None

    return deduplicate_records(records)


def html_to_text(source_html: str) -> str:
    return _strip_tags(source_html)


def parse_records_from_text(text: str, base_url: str) -> list[RatingRecord]:
    """Fallback-парсер (без ссылок на пресс-релизы), если табличный HTML не распознан."""
    lines = [_normalize_spaces(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    records: list[RatingRecord] = []
    for idx, line in enumerate(lines):
        if not line.startswith("Облигации "):
            continue

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
        issuer = _pick_issuer(details)
        if not date_match or not rating or not issuer:
            continue

        records.append(
            RatingRecord(
                issue=line,
                issuer=issuer,
                issuer_url="",
                rating=rating,
                date=date_match.group(0),
                press_release_url=base_url,
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


def attach_latest_press_release(records: list[RatingRecord], run_day: date) -> list[RatingRecord]:
    """Для каждого эмитента ставит ссылку на самый свежий пресс-релиз <= дате запуска."""
    latest_by_issuer: dict[str, tuple[date, str]] = {}

    for item in records:
        if not item.press_release_url:
            continue
        item_day = _parse_date(item.date)
        if item_day > run_day:
            continue

        prev = latest_by_issuer.get(item.issuer)
        if prev is None or item_day > prev[0]:
            latest_by_issuer[item.issuer] = (item_day, item.press_release_url)

    result: list[RatingRecord] = []
    for item in records:
        latest = latest_by_issuer.get(item.issuer)
        release_url = latest[1] if latest else (item.press_release_url or item.issuer_url or BASE_URL)
        result.append(replace(item, press_release_url=release_url))

    return result


def collect_records(max_pages: int | None = None, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> list[RatingRecord]:
    first_html = fetch_html(BASE_URL, timeout_sec=timeout_sec)
    page_urls = find_pagination_urls(first_html, BASE_URL)
    if max_pages is not None:
        page_urls = page_urls[:max_pages]

    all_records: list[RatingRecord] = []
    for page_url in page_urls:
        current_html = first_html if page_url == BASE_URL else fetch_html(page_url, timeout_sec=timeout_sec)
        parsed = parse_records_from_html(current_html, BASE_URL)
        if not parsed:
            parsed = parse_records_from_anchor_stream(current_html, BASE_URL)
        if not parsed:
            parsed = parse_records_from_text(html_to_text(current_html), BASE_URL)
        all_records.extend(parsed)

    deduped = deduplicate_records(all_records)
    return attach_latest_press_release(deduped, run_day=date.today())


def write_json(records: Iterable[RatingRecord], output: Path) -> None:
    payload = [asdict(record) for record in records]
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(records: Iterable[RatingRecord], output: Path) -> None:
    with output.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=["issue", "issuer", "issuer_url", "rating", "date", "press_release_url"])
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Парсер кредитного рейтинга, даты и ссылки на пресс-релиз для https://raexpert.ru/ratings/debt_inst/"
    )
    parser.add_argument("--output", type=Path, default=Path("raexpert_debt_ratings.json"))
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    records = collect_records(max_pages=args.max_pages, timeout_sec=args.timeout)
    if not records:
        raise RuntimeError("Не удалось извлечь записи рейтингов.")

    write_json(records, args.output)
    if args.csv:
        write_csv(records, args.csv)

    print(f"Сохранено записей: {len(records)}")
    print(f"JSON: {args.output}")
    if args.csv:
        print(f"CSV: {args.csv}")

    for item in records[:5]:
        print(f"- {item.issue} | {item.rating} | {item.date} | {item.press_release_url}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
