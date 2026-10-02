import platform
import unittest

from lottery_simulator import formats


class FormatsTest(unittest.TestCase):
    def test_new_versions_are_separate_from_legacy_names(self):
        expected = {"RULE_FORMAT_VERSION": 1, "POOL_FORMAT_VERSION": 3,
                    "EXPERIMENT_FORMAT_VERSION": 2, "RESULT_FORMAT_VERSION": 4,
                    "EVENT_FORMAT_VERSION": 3, "SAMPLING_VERSION": 2,
                    "JOB_FORMAT_VERSION": 4, "DATABASE_SCHEMA_VERSION": 6,
                    "TRACE_STORE_FORMAT_VERSION": 2, "TRACE_EXPORT_FORMAT_VERSION": 2}
        for name, version in expected.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(formats, name), version)
                self.assertIs(type(getattr(formats, name)), int)
        self.assertEqual(formats.RULE_VERSION, "3.0")
        self.assertIs(type(formats.RULE_VERSION), str)
        self.assertEqual(formats.CONFIG_FORMAT_VERSION, 2)
        self.assertEqual(formats.RECORD_FORMAT_VERSION, 2)

    def test_require_version_accepts_matching_integer(self):
        self.assertIsNone(formats.require_version(1, 1, "任务"))

    def test_integer_version_rejects_bool_and_nonmatching_values(self):
        for value in (True, "1", None, 2, 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                formats.require_version(value, 1, "任务")

    def test_sampling_metadata_describes_the_runtime(self):
        metadata = formats.sampling_metadata()
        self.assertEqual(set(metadata), {"sampling_version", "rng_algorithm", "python_implementation", "python_version"})
        self.assertEqual(metadata["sampling_version"], 2)
        self.assertEqual(metadata["rng_algorithm"], "python.random.Random")
        self.assertEqual(metadata["python_implementation"], platform.python_implementation())
        self.assertEqual(metadata["python_version"], platform.python_version())


if __name__ == "__main__":
    unittest.main()
