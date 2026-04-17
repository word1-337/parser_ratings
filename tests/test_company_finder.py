import unittest
from unittest.mock import patch

from company_finder.company_finder import (
    extract_company_urls,
    find_company_page_url,
    normalize_company_name,
    similarity_score,
)


class CompanyFinderTests(unittest.TestCase):
    def test_normalize_company_name_removes_legal_forms(self):
        self.assertEqual(normalize_company_name('АО "Самолет"'), "самолет")
        self.assertEqual(normalize_company_name("ГК Самолет"), "самолет")

    def test_extract_company_urls(self):
        html = """
        <a href=\"/database/companies/123456789/\">A</a>
        <a href=\"https://raexpert.ru/database/companies/987654321/\">B</a>
        <a href=\"/database/companies/123456789/\">A2</a>
        """
        self.assertEqual(
            extract_company_urls(html),
            [
                "https://raexpert.ru/database/companies/987654321/",
                "https://raexpert.ru/database/companies/123456789/",
            ],
        )

    def test_similarity_prefers_real_match(self):
        best = similarity_score("гк самолет", "ГК Самолет")
        other = similarity_score("гк самолет", "ПАО Лукойл")
        self.assertGreater(best, other)

    def test_find_company_page_url(self):
        search_html = """
        <a href=\"/database/companies/111111111/\">Самолет</a>
        <a href=\"/database/companies/222222222/\">Лукойл</a>
        """
        company_1_html = "<html><h1>ПАО «ГК Самолет»</h1></html>"
        company_2_html = "<html><h1>ПАО «ЛУКОЙЛ»</h1></html>"

        with patch(
            "company_finder.company_finder.fetch_html",
            side_effect=[search_html, company_1_html, company_2_html],
        ):
            result = find_company_page_url("ао самолет")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.url, "https://raexpert.ru/database/companies/111111111/")


if __name__ == "__main__":
    unittest.main()
