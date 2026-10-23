"""Validate separate hardware compliance and software termination thresholds."""
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from battery_cycler.core.models import CSV_COLUMNS, InputFileError
from battery_cycler.profiles.parser import input_parsing


class ProfileComplianceTests(unittest.TestCase):
    def parse(self, header, row):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'steps.csv'
            path.write_text(','.join(header) + '\n' + row + '\n')
            with redirect_stderr(io.StringIO()):
                return input_parsing(path)[0]

    def test_independent_compliance_and_cutoff(self):
        step = self.parse(CSV_COLUMNS, '500,VOLT,3.5,0.9,-0.5,0.5,3.6,200,4.3')
        self.assertEqual((step.source, step.compliance, step.compliance_lim, step.sw_compliance),
                         (3.5, 0.9, 3.6, 4.3))

    def test_legacy_and_blank_compliance_use_fallback(self):
        row = '500,VOLT,3.5,0.9,-0.5,0.5,3.6,200'
        self.assertIsNone(self.parse(CSV_COLUMNS[:-1], row).sw_compliance)
        self.assertIsNone(self.parse(CSV_COLUMNS, row + ',').sw_compliance)

    def test_invalid_compliance_rejected(self):
        for value in ('0', '-1', 'nan', 'inf', 'abc'):
            with self.subTest(value=value), self.assertRaises(InputFileError):
                self.parse(CSV_COLUMNS, '500,VOLT,3.5,0.9,-0.5,0.5,3.6,200,' + value)

    def test_measurement_only_allows_empty_source_fields(self):
        self.assertEqual(self.parse(CSV_COLUMNS, '2,MEAS,,,,,,,').mode, 'MEAS')
