"""Reset-only CLI behavior without a hardware connection."""
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch, call

import main
from battery_cycler.core.models import AppConfig, InstrumentError
from battery_cycler.instruments import keithley2461


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig('unused', 5025, Path('.'), Path('.'), 1, 7, 5)

    def test_reset_sequence_and_no_profile(self):
        client = Mock()
        client.query.side_effect = ['KEITHLEY INSTRUMENTS,MODEL 2461', '1']
        with patch.object(main, 'load_config', return_value=self.config), \
             patch.object(main, 'input_parsing') as parse, \
             patch.object(main, 'run_test') as run, \
             patch.object(keithley2461, 'ScpiClient', return_value=client), \
             redirect_stderr(io.StringIO()):
            self.assertEqual(main.main(['--reset']), 0)
        parse.assert_not_called()
        run.assert_not_called()
        client.assert_has_calls([call.connect(), call.query('*IDN?'),
                                 call.send(':ABORt'), call.send('*RST'), call.query('*OPC?')])
        commands = [c.args[0] for c in client.send.call_args_list]
        self.assertNotIn(':OUTP ON', commands)
        self.assertIn(':OUTP OFF', commands)
        self.assertIn(':OUTP:SMOD HIMP', commands)
        client.close.assert_called_once()

    def test_reset_failure_still_shuts_down(self):
        client = Mock()
        client.query.side_effect = ['KEITHLEY,MODEL 2461', '0']
        with patch.object(keithley2461, 'ScpiClient', return_value=client), \
             redirect_stderr(io.StringIO()), self.assertRaises(InstrumentError):
            keithley2461.setup(self.config, reset_only=True)
        client.send.assert_any_call(':OUTP OFF')
        client.close.assert_called_once()

    def test_abort_failure_still_shuts_down(self):
        client = Mock()
        client.query.return_value = 'KEITHLEY,MODEL 2461'
        def send(command):
            if command == ':ABORt':
                raise InstrumentError('abort failed')
        client.send.side_effect = send
        with patch.object(keithley2461, 'ScpiClient', return_value=client), \
             redirect_stderr(io.StringIO()), self.assertRaises(InstrumentError):
            keithley2461.setup(self.config, reset_only=True)
        client.send.assert_any_call(':OUTP OFF')
        client.close.assert_called_once()

    def test_reset_excludes_checks(self):
        for option in ('--check-input', '--check-dev'):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main._build_argument_parser().parse_args(['--reset', option])
            self.assertEqual(error.exception.code, 2)
