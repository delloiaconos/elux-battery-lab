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

    def run_step(self, readings, duration=1, timeout=3, mode="VOLT", source=4.2, sw_compliance=None):
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        step = TestStep(duration, mode, source, 2, -1, 1, 0.1, timeout, sw_compliance)
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
                self.assertEqual((switched.mode, switched.source, switched.compliance), ('CURR', expected, 7))
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
                self.assertEqual((switched.mode, switched.source, switched.compliance), ('VOLT', expected, 5))
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
        client.query.return_value = 'VOLT'
        configure_step(client, self.config, TestStep(1, 'CURR', -1, 9))
        commands = [call.args[0] for call in client.send.call_args_list]
        self.assertIn(':SOUR:FUNC CURR', commands)
        self.assertIn(':SOUR:CURR -1', commands)
        self.assertIn(':SOUR:CURR:VLIM 7', commands)

    def test_source_changes_disable_output_before_switching(self):
        for previous, mode, target in (
            ('VOLT', 'CURR', 'CURR'),
            ('CURR', 'VOLT', 'VOLT'),
            ('VOLT', 'MEAS', 'CURR'),
        ):
            with self.subTest(mode=mode):
                client = Mock()
                client.query.return_value = previous
                configure_step(client, self.config, TestStep(1, mode, 1, 2))
                commands = [call.args[0] for call in client.send.call_args_list]
                self.assertEqual(commands[:4], [':OUTP:SMOD HIMP', ':OUTP OFF',
                                               f':SOUR:FUNC {target}', ':OUTP:SMOD HIMP'])
                self.assertEqual(commands[-1], ':OUTP ON')
                self.assertEqual(commands.count(':OUTP ON'), 1)

    def test_same_function_keeps_output_enabled(self):
        for mode, response in (('CURR', 'CURR'), ('VOLT', 'VOLT'), ('MEAS', 'CURR')):
            with self.subTest(mode=mode):
                client = Mock()
                client.query.return_value = response
                configure_step(client, self.config, TestStep(1, mode, 1, 2))
                commands = [call.args[0] for call in client.send.call_args_list]
                self.assertNotIn(':OUTP OFF', commands)
                self.assertFalse(any(cmd.startswith(':SOUR:FUNC ') for cmd in commands))

    def test_failed_configuration_does_not_reenable_output(self):
        client = Mock()
        client.query.return_value = 'VOLT'
        def send(command):
            if command == ':SOUR:CURR:VLIM 2':
                raise OSError('connection lost')
        client.send.side_effect = send
        with self.assertRaises(OSError):
            configure_step(client, self.config, TestStep(1, 'CURR', 1, 2))
        self.assertNotIn(':OUTP ON', [call.args[0] for call in client.send.call_args_list])

    def test_software_limit_compliance_is_independent_of_source(self):
        for mode, readings in (
            ('VOLT', [Measurement(2, -9, 'VOLT'), Measurement(1, 0, 'CSWL')]),
            ('CURR', [Measurement(-9, 2, 'CURR'), Measurement(0, 1, 'VSWL')]),
        ):
            with self.subTest(mode=mode):
                configure, _, _, _ = self.run_step(readings, mode=mode, source=-9, sw_compliance=4.3)
                transition = configure.call_args_list[1]
                self.assertEqual(transition.args[2].compliance, 4.3)
                self.assertEqual(transition.kwargs, {})

    def test_compliance_is_capped_by_global_limits(self):
        for mode, previous, command in (
            ('CURR', 'VOLT', ':SOUR:CURR:VLIM 7'),
            ('VOLT', 'CURR', ':SOUR:VOLT:ILIM 5'),
        ):
            with self.subTest(mode=mode):
                client = Mock()
                client.query.return_value = previous
                applied = configure_step(client, self.config, TestStep(1, mode, 1, 9))
                self.assertEqual(applied, 7 if mode == 'CURR' else 5)
                self.assertIn(command, [call.args[0] for call in client.send.call_args_list])


if __name__ == '__main__':
    unittest.main()
