import os
import unittest
from unittest.mock import patch

from dashboard.limits import TraceLimits


class TraceLimitsTest(unittest.TestCase):
    def test_defaults_keep_batch_size_as_a_fixed_constant(self):
        with patch.dict(os.environ, {}, clear=True):
            limits = TraceLimits.from_env()

        self.assertEqual(limits.max_records, 1_000_000)
        self.assertEqual(limits.max_download_records, 10_000)
        self.assertEqual(limits.batch_size, 1000)

    def test_from_env_reads_only_the_two_trace_capacity_limits(self):
        environment = {
            "LOTTERY_MAX_TRACE_RECORDS": "001234",
            "LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS": "567",
            "LOTTERY_TRACE_BATCH_SIZE": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            limits = TraceLimits.from_env()

        self.assertEqual(limits, TraceLimits(1234, 567, 1000))

    def test_from_env_rejects_non_positive_integer_strings(self):
        for value in ("", "0", "-1", "1.5", " 1", "+1"):
            for name in (
                "LOTTERY_MAX_TRACE_RECORDS",
                "LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS",
            ):
                with self.subTest(name=name, value=value):
                    with patch.dict(os.environ, {name: value}, clear=True):
                        with self.assertRaises(ValueError):
                            TraceLimits.from_env()


if __name__ == "__main__":
    unittest.main()
