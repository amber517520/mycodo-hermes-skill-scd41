"""Command line entry point. Actuation is deliberately unavailable."""
import argparse
import json
import getpass
import os
import sys
import time
from pathlib import Path
from . import core

class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_arguments')

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if '--execute' in args or any(a.startswith('--execute=') for a in args):
        print(json.dumps({'mode': 'dry-run', 'error': 'execute_disabled', 'executed_commands': []}))
        return 2
    parser = PrivateArgumentParser(description='SCD41 dry-run only', allow_abbrev=False)
    parser.add_argument('command', choices=['replay', 'simulate', 'read'])
    parser.add_argument('--report')
    parser.add_argument('--config')
    parser.add_argument('--fixture')
    parser.add_argument('--url')
    parser.add_argument('--ca-pem')
    parser.add_argument('--audit')
    parser.add_argument('--html')
    try:
        options = parser.parse_args(args)
    except ValueError:
        print(json.dumps({'mode': 'dry-run', 'error': 'invalid_arguments', 'executed_commands': []}))
        return 2
    try:
        config = json.loads(Path(options.config).read_text(encoding='utf-8')) if options.config else core.default_config()
        core.validate_config(config)
        if options.command == 'replay':
            data = json.loads(Path(options.report).read_text(encoding='utf-8'))
            result = core.evaluate(config, core.replay(data), time.time())
            result['source'] = 'offline_recorded_report_NOT_current_Pi_data'
        elif options.command == 'read':
            key = os.environ.get('MYCODO_API_KEY') or getpass.getpass('Mycodo API key (masked): ')
            if not key:
                raise ValueError('key_required')
            client = core.ReadClient(options.url, key, ca_pem=options.ca_pem)
            del key
            snapshot = core.read_snapshot(client)
            result = core.evaluate(config, snapshot['readings'], time.time())
            result.update(source=snapshot['source'], outputs=snapshot['outputs'], errors=snapshot['errors'])
            if snapshot['errors']:
                result['planned_commands'] = []
                result['blockers'].extend(snapshot['errors'])
        else:
            data = json.loads(Path(options.fixture).read_text(encoding='utf-8'))
            if data.get('label') != 'OFFLINE TEST ONLY NOT CURRENT PI DATA':
                raise ValueError('test_label_required')
            result = core.evaluate(data['config'], data['readings'], data['now'], data.get('last_humidifier_time'))
            result['source'] = 'offline_synthetic_TEST_NOT_current_Pi_data'
        if options.audit:
            core.write_audit(options.audit, result)
        if options.html:
            Path(options.html).write_text(core.render_html(result), encoding='utf-8')
    except Exception:
        print(json.dumps({'mode': 'dry-run', 'error': 'invalid_input_or_configuration', 'executed_commands': []}))
        return 2
    print(json.dumps(core.safe_data(result), ensure_ascii=True, allow_nan=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
