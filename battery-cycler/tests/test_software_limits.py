"""Software-limit transitions with a simulated clock and instrument."""
import csv
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from battery_cycler.core import runner
from battery_cycler.core.models import AppConfig, Measurement, TestStep
from battery_cycler.instruments.keithley2461 import measure, configure_step


class SoftwareLimitTests(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig('unused', 5025, Path('.'), Path('.'), 1, 7, 5)

    def run_step(self, readings, duration=1, timeout=3, mode="VOLT"):
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        step = TestStep(duration, mode, 4.2, 2, -1, 1, 0.1, timeout)
        output = io.StringIO()
        with patch.object(runner.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(runner.time, 'sleep', side_effect=sleep), \
             patch.object(runner, 'configure_step', return_value=2) as configure, \
             patch.object(runner, 'measure', side_effect=readings) as read, \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            runner._run_step(Mock(), csv.writer(output), output, self.config, step, 1, 0)
        return configure, read, list(csv.reader(io.StringIO(output.getvalue()))), clock[0]

    def test_upper_and_lower_limits_switch_to_current(self):
        for current, expected in ((1.2, 1), (-1.2, -1)):
            with self.subTest(current=current):
                configure, read, rows, _ = self.run_step([
                    Measurement(current, 4.2, 'VOLT'), Measurement(expected, 0.05, 'CSWL')])
                switched = configure.call_args_list[1].args[2]
                self.assertEqual((switched.mode, switched.source, switched.compliance), ('CURR', expected, 4.2))
                self.assertEqual([call.args[1] for call in read.call_args_list], ['VOLT', 'CSWL'])
                self.assertEqual(rows[-1][2], 'CSWL')

    def test_limit_timer_replaces_original_duration(self):
        _, read, _, elapsed = self.run_step([
            Measurement(2, 4.2, 'VOLT'), *[Measurement(1, 4.2, 'CSWL')] * 3])
        self.assertEqual(elapsed, 3)
        self.assertEqual(read.call_count, 4)

    def test_equal_bounds_do_not_switch(self):
        for current in (-1, 1):
            configure, _, _, _ = self.run_step([Measurement(current, 4.2, 'VOLT')] * 2)
            self.assertEqual(configure.call_count, 1)

    def test_indefinite_step_can_enter_software_limit(self):
        configure, _, _, _ = self.run_step([
            Measurement(2, 4.2, 'VOLT'), Measurement(1, -0.05, 'CSWL')], duration=-1)
        self.assertEqual(configure.call_count, 2)

    def test_current_mode_dual_transition(self):
        for voltage, expected in ((1.2, 1), (-1.2, -1)):
            with self.subTest(voltage=voltage):
                configure, read, rows, _ = self.run_step([
                    Measurement(4.2, voltage, 'CURR'),
                    Measurement(-0.05, expected, 'VSWL')], mode='CURR')
                switched = configure.call_args_list[1].args[2]
                self.assertEqual((switched.mode, switched.source, switched.compliance), ('VOLT', expected, 4.2))
                self.assertEqual(read.call_args_list[-1].args[1], 'VSWL')
                self.assertEqual(rows[-1][2], 'VSWL')

    def test_hardware_trip_cutoff_unchanged(self):
        for mode, reading in (
            ('VOLT', Measurement(0.5, 0.05, 'ILIM')),
            ('CURR', Measurement(0.05, 0.5, 'VLIM')),
        ):
            configure, read, _, _ = self.run_step([reading], mode=mode)
            self.assertEqual(configure.call_count, 1)
            self.assertEqual(read.call_count, 1)

    def test_hardware_trip_timer_resets(self):
        readings = [Measurement(0.5, 4.2, state) for state in
                    ('ILIM', 'VOLT', 'ILIM', 'ILIM', 'ILIM')]
        configure, _, _, elapsed = self.run_step(readings, duration=20, timeout=2)
        self.assertEqual(elapsed, 4)
        self.assertEqual(configure.call_count, 1)

    def test_vswl_reads_voltage_and_current_in_correct_order(self):
        client = Mock()
        client.query.return_value = '4.2,1'
        self.assertEqual(measure(client, 'VSWL'), Measurement(1, 4.2, 'VSWL'))

    def test_zero_timeout(self):
        _, read, _, _ = self.run_step([
            Measurement(2, 4.2, 'VOLT'), Measurement(1, 4.2, 'CSWL')], timeout=0)
        self.assertEqual(read.call_count, 2)

    def test_cswl_reads_voltage_and_current_in_correct_order(self):
        client = Mock()
        client.query.return_value = '1,4.2'
        self.assertEqual(measure(client, 'CSWL'), Measurement(1, 4.2, 'CSWL'))
        client.query.assert_called_once()

    def test_current_configuration_preserves_voltage_ceiling(self):
        client = Mock()
        configure_step(client, self.config, TestStep(1, 'CURR', -1, 9))
        commands = [call.args[0] for call in client.send.call_args_list]
        self.assertIn(':SOUR:FUNC CURR', commands)
        self.assertIn(':SOUR:CURR -1', commands)
        self.assertIn(':SOUR:CURR:VLIM 7', commands)


if __name__ == '__main__':
    unittest.main()
