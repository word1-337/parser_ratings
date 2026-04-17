import unittest
from datetime import date

from parser_raexpert_debt import (
    attach_latest_press_release,
    deduplicate_records,
    find_pagination_urls,
    html_to_text,
    parse_records_from_anchor_stream,
    parse_records_from_html,
    parse_records_from_text,
)


SAMPLE_HTML = """
<html>
  <body>
    <table>
      <tr><th>Эмиссия</th><th>Рейтинг</th><th>Обновлен</th></tr>
      <tr><td><a href="/ratings/debt_inst/issue-a">Облигации Тест серии 01</a></td></tr>
      <tr>
        <td><a href="/ratings/company">ООО "ТЕСТ"</a> ruBB+, <a href="/releases/2026/apr10z">10.04.2026</a></td>
      </tr>
      <tr><td><a href="/ratings/debt_inst/issue-b">Облигации Тест серии 02</a></td></tr>
      <tr>
        <td><a href="/ratings/company">ООО "ТЕСТ"</a> ruA−, <a href="/releases/2026/apr17x">17.04.2026</a></td>
      </tr>
      <tr><td><a href="/ratings/debt_inst/issue-c">Облигации ДРУГОЙ серии 01</a></td></tr>
      <tr>
        <td><a href="/ratings/company-2">ПАО "ДРУГОЙ"</a> отозван, <a href="/releases/2026/apr01x">01.04.2026</a></td>
      </tr>
    </table>
  </body>
</html>
""".strip()




SAMPLE_DIV_HTML = """
<div>
  <a href="/ratings/debt_inst/item-x">Облигации ПРИМЕР серии 01</a>
  <a href="/ratings/company-x">ООО "ПРИМЕР"</a>
  <a href="/releases/2026/apr16a">ruA-</a>
  <a href="/releases/2026/apr16a">16.04.2026</a>
</div>
""".strip()

SAMPLE_TEXT = """
Эмиссия Рейтинг Прогноз Обновлен
Облигации Новабев Групп серии БО-П06
ПАО "НОВАБЕВ ГРУПП" отозван, 17.04.2026 отозван — 17.04.2026
Облигации АБЗ-1 серии 002Р-06
АО "АБЗ-1" ruA-, 17.04.2026 ruA- — 17.04.2026
""".strip()


class ParserTests(unittest.TestCase):
    def test_parse_records_from_html_extracts_press_release_link(self):
        records = parse_records_from_html(SAMPLE_HTML, "https://raexpert.ru/ratings/debt_inst/")
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].rating, "ruBB+")
        self.assertEqual(records[0].press_release_url, "https://raexpert.ru/releases/2026/apr10z")
        self.assertEqual(records[1].rating, "ruA-")
        self.assertEqual(records[1].press_release_url, "https://raexpert.ru/releases/2026/apr17x")
        self.assertEqual(records[2].rating, "отозван")

    def test_attach_latest_press_release_by_issuer(self):
        records = parse_records_from_html(SAMPLE_HTML, "https://raexpert.ru/ratings/debt_inst/")
        resolved = attach_latest_press_release(records, run_day=date(2026, 4, 17))

        issuer_records = [r for r in resolved if r.issuer == 'ООО "ТЕСТ"']
        self.assertEqual(len(issuer_records), 2)
        self.assertEqual(
            {r.press_release_url for r in issuer_records},
            {"https://raexpert.ru/releases/2026/apr17x"},
        )


    def test_parse_records_from_anchor_stream_without_table_rows(self):
        records = parse_records_from_anchor_stream(SAMPLE_DIV_HTML, "https://raexpert.ru/ratings/debt_inst/")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].issuer, 'ООО "ПРИМЕР"')
        self.assertEqual(records[0].rating, "ruA-")
        self.assertEqual(records[0].press_release_url, "https://raexpert.ru/releases/2026/apr16a")

    def test_parse_records_from_text_fallback(self):
        records = parse_records_from_text(SAMPLE_TEXT, "https://raexpert.ru/ratings/debt_inst/")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].press_release_url, "https://raexpert.ru/ratings/debt_inst/")

    def test_find_pagination_urls(self):
        html_doc = """
        <a href="/ratings/debt_inst/?PAGEN_1=2">2</a>
        <a href="/ratings/debt_inst/?PAGEN_1=3">3</a>
        <a href="/other">x</a>
        """
        pages = find_pagination_urls(html_doc, "https://raexpert.ru/ratings/debt_inst/")
        self.assertEqual(
            pages,
            [
                "https://raexpert.ru/ratings/debt_inst/",
                "https://raexpert.ru/ratings/debt_inst/?PAGEN_1=2",
                "https://raexpert.ru/ratings/debt_inst/?PAGEN_1=3",
            ],
        )

    def test_html_to_text_removes_tags(self):
        source = "<html><body><script>alert(1)</script><div>Облигации Тест</div></body></html>"
        text = html_to_text(source)
        self.assertIn("Облигации Тест", text)
        self.assertNotIn("alert(1)", text)

    def test_deduplicate_records(self):
        records = parse_records_from_html(SAMPLE_HTML, "https://raexpert.ru/ratings/debt_inst/")
        unique = deduplicate_records(records + records)
        self.assertEqual(len(unique), len(records))


if __name__ == "__main__":
    unittest.main()
