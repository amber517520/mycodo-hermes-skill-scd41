"""Safety-first dry-run core: no live actuation implementation."""
import copy
import math

INPUT = 'e0fe890e-dce7-4b14-9395-5b7815423e51'
CHANNELS = {'co2': [0, 'ppm'], 'temperature': [1, 'C'], 'humidity': [2, 'percent'], 'dewpoint': [3, 'C'], 'vpd': [4, 'Pa']}
OUTPUTS = {
    'humidifier': {'uuid': 'bf9acc8f-76e6-4d3e-8f24-1f9a38512d24', 'pin': 5, 'channel': 0, 'type': 'output_on_off_pinctrl', 'active_high': True, 'startup': 'off', 'shutdown': 'off'},
    'fan': {'uuid': '1a58c7c4-481a-408c-b1bc-d88f6ba75b10', 'pin': 16, 'channel': 0, 'type': 'output_on_off_pinctrl', 'active_high': True, 'startup': 'off', 'shutdown': 'off'},
}

def default_config():
    return {'schema': 1, 'mode': 'dry-run', 'box': 'A', 'input_uuid': INPUT,
            'channels': copy.deepcopy(CHANNELS), 'outputs': copy.deepcopy(OUTPUTS),
            'species': '秀珍菇（研究名稱已確認；參數來源待核准）', 'species_confirmed': False,
            'approved': False, 'provenance': None, 'water_available': None,
            'thresholds': dict.fromkeys(['temperature_min', 'temperature_max', 'humidity_min', 'humidity_max', 'co2_max']),
            'limits': dict.fromkeys(['humidifier_max_seconds', 'fan_max_seconds', 'cooldown_seconds', 'stale_seconds'])}

def validate_config(c):
    baseline = default_config()
    for k in ['schema', 'mode', 'box', 'input_uuid', 'channels', 'outputs']:
        if c.get(k) != baseline[k] or type(c.get(k)) is not type(baseline[k]):
            raise ValueError('configuration_allowlist_mismatch')
    for name, out in c['outputs'].items():
        if type(out['pin']) is not int or type(out['channel']) is not int:
            raise ValueError('invalid_output_channel')
    for channel, unit in c['channels'].values():
        if type(channel) is not int:
            raise ValueError('invalid_input_channel')

def finite_number(v):
    try:
        return type(v) in (int, float) and math.isfinite(v)
    except OverflowError:
        return False

def reading_status(r, now, stale_seconds):
    if not isinstance(r, dict) or not finite_number(r.get('value')) or not finite_number(r.get('time')) or r['time'] <= 0 or not finite_number(now):
        return 'invalid'
    if r['time'] > now:
        return 'future'
    if not finite_number(stale_seconds) or stale_seconds <= 0:
        return 'freshness_unconfigured'
    return 'stale' if now - r['time'] > stale_seconds else 'fresh'

def evaluate(c, readings, now, last_humidifier_time=None):
    validate_config(c)
    thresholds = c.get('thresholds', {})
    limits = c.get('limits', {})
    statuses = {k: reading_status(readings.get(k), now, limits.get('stale_seconds')) for k in CHANNELS}
    blockers = []
    if c.get('approved') is not True:
        blockers.append('approval_required')
    if c.get('species_confirmed') is not True or not isinstance(c.get('provenance'), str) or not c['provenance'].strip():
        blockers.append('species_or_provenance_unconfirmed')
    complete = (set(thresholds) == set(default_config()['thresholds']) and all(finite_number(v) for v in thresholds.values()) and
                set(limits) == set(default_config()['limits']) and all(finite_number(v) and v > 0 for v in limits.values()))
    if complete:
        complete = (thresholds['temperature_min'] < thresholds['temperature_max'] and
                    0 <= thresholds['humidity_min'] < thresholds['humidity_max'] <= 100 and thresholds['co2_max'] > 0)
    if not complete:
        blockers.append('thresholds_or_limits_unconfigured')
    if any(s != 'fresh' for s in statuses.values()):
        blockers.append('readings_not_fresh')
    result = {'mode': 'dry-run', 'status': 'unconfigured' if not complete or c.get('approved') is not True else 'blocked' if blockers else 'ready',
              'readings': readings, 'reading_status': statuses, 'blockers': blockers,
              'planned_commands': [], 'executed_commands': []}
    if not blockers:
        if not (thresholds['temperature_min'] <= readings['temperature']['value'] <= thresholds['temperature_max']):
            blockers.append('temperature_outside_approved_range')
        if not (0 <= readings['humidity']['value'] <= 100) or readings['co2']['value'] < 0 or readings['vpd']['value'] < 0:
            blockers.append('physical_reading_invalid')
    if blockers:
        if result['status'] == 'ready': result['status'] = 'blocked'
        return result
    if readings['co2']['value'] > thresholds['co2_max']:
        result['planned_commands'].append(dict(OUTPUTS['fan'], action='pulse', duration_seconds=limits['fan_max_seconds']))
    if readings['humidity']['value'] < thresholds['humidity_min']:
        if c.get('water_available') is not True:
            blockers.append('water_unconfirmed')
        elif not finite_number(last_humidifier_time) or last_humidifier_time <= 0 or last_humidifier_time > now or now - last_humidifier_time < limits['cooldown_seconds']:
            blockers.append('cooldown_unconfirmed_or_active')
        else:
            result['planned_commands'].append(dict(OUTPUTS['humidifier'], action='pulse', duration_seconds=limits['humidifier_max_seconds']))
    if blockers:
        result['status'] = 'blocked'
    return result

def replay(report):
    readings = {}
    for request in report.get('requests', []):
        if request.get('http_status') != 200:
            continue
        parts = request.get('path', '').split('/')
        for metric, (channel, unit) in CHANNELS.items():
            prefix = ['', 'api', 'measurements', 'last', INPUT, unit, str(channel)]
            if len(parts) == 8 and parts[:7] == prefix and parts[7].isdigit():
                readings[metric] = copy.deepcopy(request.get('data'))
    return readings

import json

def map_outputs(data):
    result = {}
    for name, allowed in OUTPUTS.items():
        result[name] = {'mapping': 'unknown', 'state': 'unknown'}
        devices = [d for d in data.get('output devices', []) if d.get('unique_id') == allowed['uuid']]
        channels = [ch for ch in data.get('output channels', []) if ch.get('output_id') == allowed['uuid'] and type(ch.get('channel')) is int and ch['channel'] == 0]
        if len(devices) != 1 or len(channels) != 1 or devices[0].get('output_type') != allowed['type']:
            continue
        try:
            opts = json.loads(channels[0].get('custom_options', '{}'))
        except (ValueError, TypeError):
            continue
        if type(opts.get('pin')) is not int or opts['pin'] != allowed['pin'] or opts.get('on_state') != 1 or opts.get('state_startup') != 0 or opts.get('state_shutdown') != 0:
            continue
        state = data.get('output states', {}).get(allowed['uuid'], {}).get('0', 'unknown')
        if type(state) is bool:
            state = 'on' if state else 'off'
        result[name] = {'mapping': 'verified', 'pin': allowed['pin'], 'channel': 0, 'state': state if state in ('on', 'off') else 'unknown'}
    return result

import base64
import ssl
import urllib.request
from urllib.parse import urlsplit

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class ReadClient:
    def __init__(self, base_url, api_key, ca_pem=None):
        parsed = urlsplit(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('https_origin_required')
        self.base_url = base_url.rstrip('/')
        self.context = ssl.create_default_context(cafile=ca_pem)
        self._encoded_key = base64.b64encode(api_key.encode('utf-8')).decode('ascii')
        self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.context), NoRedirect())

    def get(self, path):
        allowed = {'/api/settings/inputs', '/api/settings/device_measurements/by_device_id/' + INPUT, '/api/outputs/'}
        for channel, unit in CHANNELS.values():
            allowed.add(f'/api/measurements/last/{INPUT}/{unit}/{channel}/600')
        if path not in allowed:
            raise ValueError('get_path_not_allowed')
        request = urllib.request.Request(self.base_url + path, method='GET', headers={'Accept': 'application/vnd.mycodo.v1+json', 'X-API-KEY': self._encoded_key})
        try:
            with self._opener.open(request, timeout=15) as response:
                raw = response.read(1048577)
                if len(raw) > 1048576:
                    raise ValueError('payload_too_large')
                return json.loads(raw.decode('utf-8'))
        except Exception:
            raise RuntimeError('read_failed_tls_http_or_payload') from None

def read_snapshot(client):
    errors = []
    def fetch(path):
        try:
            data = client.get(path)
            if not isinstance(data, dict):
                raise ValueError('invalid_shape')
            return data
        except Exception:
            errors.append('get_failed')
            return {}
    inputs = fetch('/api/settings/inputs')
    measurements = fetch('/api/settings/device_measurements/by_device_id/' + INPUT)
    outputs = fetch('/api/outputs/')
    observed_inputs = [i for i in inputs.get('input settings', []) if i.get('unique_id') == INPUT]
    if len(observed_inputs) != 1 or observed_inputs[0].get('device') != 'SCD4x_CIRCUITPYTHON' or observed_inputs[0].get('is_activated') is not True:
        errors.append('input_inventory_unverified')
    observed_channels = {m.get('channel'): (m.get('unit'), m.get('device_id')) for m in measurements.get('device measurement settings', [])}
    if any(observed_channels.get(ch) != (unit, INPUT) for ch, unit in CHANNELS.values()):
        errors.append('channel_inventory_unverified')
    readings = {metric: fetch(f'/api/measurements/last/{INPUT}/{unit}/{channel}/600') for metric, (channel, unit) in CHANNELS.items()}
    mapped = map_outputs(outputs)
    if any(o['mapping'] != 'verified' for o in mapped.values()):
        errors.append('output_inventory_unverified')
    return {'source': 'live_GET_only', 'readings': readings, 'outputs': mapped, 'errors': errors}

import html

def safe_data(value):
    if isinstance(value, dict):
        return {str(k): safe_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_data(v) for v in value]
    if type(value) is float and not math.isfinite(value):
        return None
    return value

def render_html(report):
    escaped = html.escape(json.dumps(safe_data(report), ensure_ascii=False, indent=2, allow_nan=False))
    return '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>DRY RUN</title><h1>DRY RUN — 執行指令 0</h1><pre>' + escaped + '</pre></html>'

from datetime import datetime, timezone
from pathlib import Path

def write_audit(path, report):
    status = report.get('status')
    if status not in ('ready', 'blocked', 'unconfigured', 'error'):
        status = 'error'
    event = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'mode': 'dry-run',
             'status': status, 'planned_count': len(report.get('planned_commands', [])),
             'executed_count': 0, 'error_present': bool(report.get('errors'))}
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, allow_nan=False) + '\n')
