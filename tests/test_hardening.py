import contextlib
import copy
import io
import unittest
from mycodo_scd41 import core
from mycodo_scd41.__main__ import main

class HardeningTests(unittest.TestCase):
    def test_unknown_cli_arguments_are_not_echoed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = main(['replay', '--api-key', 'SENSITIVE_TEST_SENTINEL'])
        self.assertEqual(code, 2)
        self.assertNotIn('SENSITIVE_TEST_SENTINEL', output.getvalue())
        self.assertIn('invalid_arguments', output.getvalue())

    def test_huge_integer_reading_fails_closed(self):
        self.assertEqual(core.reading_status({'time': 100, 'value': 10**1000}, 110, 20), 'invalid')

    def test_boolean_output_states_preserved(self):
        import json
        for state, expected in [(False, 'off'), (True, 'on')]:
            devices = []
            channels = []
            states = {}
            for name, allowed in core.OUTPUTS.items():
                devices.append({'unique_id': allowed['uuid'], 'output_type': allowed['type']})
                channels.append({'output_id': allowed['uuid'], 'channel': 0, 'custom_options': json.dumps({'pin': allowed['pin'], 'on_state': 1, 'state_startup': 0, 'state_shutdown': 0})})
                states[allowed['uuid']] = {'0': state}
            result = core.map_outputs({'output devices': devices, 'output channels': channels, 'output states': states})
            self.assertEqual({x['state'] for x in result.values()}, {expected})
