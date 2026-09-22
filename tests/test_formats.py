import platform
import unittest

from lottery_simulator.formats import (
    CONFIG_FORMAT_VERSION,
    DATABASE_SCHEMA_VERSION,
    JOB_FORMAT_VERSION,
    RECORD_FORMAT_VERSION,
    RESULT_FORMAT_VERSION,
    SAMPLING_VERSION,
    TRACE_EXPORT_FORMAT_VERSION,
    TRACE_STORE_FORMAT_VERSION,
    require_version,
    sampling_metadata,
)


class FormatsTest(unittest.TestCase):
    def test_format_versions_match_the_multi_trial_trace_contract(self):
        self.assertEqual(CONFIG_FORMAT_VERSION, 1)
        self.assertEqual(SAMPLING_VERSION, 1)
        self.assertEqual(RECORD_FORMAT_VERSION, 2)
        self.assertEqual(RESULT_FORMAT_VERSION, 2)
        self.assertEqual(JOB_FORMAT_VERSION, 2)
        self.assertEqual(DATABASE_SCHEMA_VERSION, 4)
        self.assertEqual(TRACE_STORE_FORMAT_VERSION, 1)
        self.assertEqual(TRACE_EXPORT_FORMAT_VERSION, 1)

    def test_require_version_accepts_matching_integer(self):
        self.assertIsNone(require_version(1, 1, "任务"))

    def test_integer_version_rejects_bool_and_nonmatching_values(self):
        for value in (True, "1", None, 2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_version(value, 1, "任务")

    def test_sampling_metadata_describes_the_runtime(self):
        metadata = sampling_metadata()

        self.assertEqual(
            set(metadata),
            {
                "sampling_version",
                "rng_algorithm",
                "python_implementation",
                "python_version",
            },
        )
        self.assertEqual(metadata["sampling_version"], 1)
        self.assertEqual(metadata["rng_algorithm"], "python.random.Random")
        self.assertEqual(metadata["python_implementation"], platform.python_implementation())
        self.assertEqual(metadata["python_version"], platform.python_version())


if __name__ == "__main__":
    unittest.main()
