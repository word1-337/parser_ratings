import unittest

from parser_raexpert_debt import (
    deduplicate_records,
    find_pagination_urls,
    html_to_text,
    parse_records_from_text,
)


SAMPLE_TEXT = """
Эмиссия Рейтинг Прогноз Обновлен
Облигации Новабев Групп серии БО-П06
ПАО \"НОВАБЕВ ГРУПП\" отозван, 17.04.2026 отозван — 17.04.2026
Облигации АБЗ-1 серии 002Р-06
АО \"АБЗ-1\" ruA-, 17.04.2026 ruA- — 17.04.2026
Облигации Полюс серии ПБО-05
ПАО \"ПОЛЮС\" ruAAA, 17.04.2026 ruAAA — 17.04.2026
""".strip()


SAMPLE_HTML = """
<html>
  <body>
    <table>
      <tr><th>Эмиссия</th><th>Рейтинг</th><th>Обновлен</th></tr>
      <tr><td>Облигации Тест серии 01</td></tr>
      <tr><td>ООО \"ТЕСТ\" ruBB+, 01.01.2026 ruBB+ — 01.01.2026</td></tr>
      <tr><td>Облигации Тест серии 02</td></tr>
      <tr><td>ООО \"ТЕСТ\" ruA−, 02.01.2026 ruA− — 02.01.2026</td></tr>
    </table>
  </body>
</html>
""".strip()


class ParserTests(unittest.TestCase):
    def test_parse_records_from_text_extracts_rating_and_date(self):
        records = parse_records_from_text(SAMPLE_TEXT, source_url="https://example.local/page1")
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].rating, "отозван")
        self.assertEqual(records[0].date, "17.04.2026")
        self.assertEqual(records[1].rating, "ruA-")
        self.assertEqual(records[2].rating, "ruAAA")

    def test_parse_records_from_text_ignores_non_rating_tokens(self):
        text = """
        Облигации Тест выпуск
        ПАО \"РОМАШКА\" Под наблюдением, 11.11.2025
        """
        records = parse_records_from_text(text, source_url="https://example.local/page1")
        self.assertEqual(records, [])

    def test_parse_records_handles_unicode_minus(self):
        text = """
        Облигации Тест выпуск
        ПАО \"РОМАШКА\" ruA−, 11.11.2025 ruA− — 11.11.2025
        """
        records = parse_records_from_text(text, source_url="https://example.local/page1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].rating, "ruA-")

    def test_deduplicate_records(self):
        records = parse_records_from_text(SAMPLE_TEXT, source_url="https://example.local/page1")
        duplicated = records + records
        unique = deduplicate_records(duplicated)
        self.assertEqual(len(unique), len(records))

    def test_find_pagination_urls(self):
        html_doc = """
        <a href=\"/ratings/debt_inst/?PAGEN_1=2\">2</a>
        <a href=\"/ratings/debt_inst/?PAGEN_1=3\">3</a>
        <a href=\"/other\">x</a>
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

    def test_html_to_text_removes_script(self):
        source = "<html><body><script>alert(1)</script><div>Облигации Тест</div></body></html>"
        text = html_to_text(source)
        self.assertIn("Облигации Тест", text)
        self.assertNotIn("alert(1)", text)

    def test_parse_after_html_conversion(self):
        text = html_to_text(SAMPLE_HTML)
        records = parse_records_from_text(text, source_url="https://example.local/page1")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].rating, "ruBB+")
        self.assertEqual(records[1].rating, "ruA-")


if __name__ == "__main__":
    unittest.main()
