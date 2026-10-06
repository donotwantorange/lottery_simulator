from django.test import SimpleTestCase

from dashboard.api.errors import APIError
from dashboard.api.pools import _page
from dashboard.api.query import query_integer


class QueryIntegerTests(SimpleTestCase):
    def test_decimal_boundaries_and_leading_zeroes(self):
        self.assertEqual(query_integer("0" * 1023 + "7", "page"), 7)
        for value in ("0" * 1024 + "7", "9" * 5000, "", "-1", "1.0", "abc", 7, None):
            with self.subTest(value_type=type(value).__name__, length=len(value) if isinstance(value, str) else None):
                with self.assertRaises(APIError) as caught:
                    query_integer(value, "page")
                self.assertEqual(caught.exception.status, 400)

    def test_page_defaults_bounds_and_text_types(self):
        self.assertEqual(_page(None, "page", 1, 10), 1)
        self.assertEqual(_page("00010", "page", 1, 10), 10)
        for value in ("0", "11", 1):
            with self.subTest(value=value):
                with self.assertRaises(APIError):
                    _page(value, "page", 1, 10)
