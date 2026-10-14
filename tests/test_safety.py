import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mycodo_scd41 import core

class SafetyTests(unittest.TestCase):
    def test_default_configuration_is_unapproved(self):
        self.assertTrue(hasattr(core, 'default_config'), 'missing default_config')
        c = core.default_config()
        self.assertFalse(c['approved'])
        self.assertIsNone(c['provenance'])
        self.assertTrue(all(v is None for v in c['limits'].values()))
        self.assertTrue(all(v is None for v in c['thresholds'].values()))
        self.assertEqual(c['box'], 'A')
        self.assertEqual(c['water_available'], None)

    def test_configuration_allowlist_cannot_be_changed(self):
        self.assertTrue(hasattr(core, 'validate_config'), 'missing validation')
        c = core.default_config()
        core.validate_config(c)
        mutations = [('box', 'B'), ('mode', 'execute'), ('input_uuid', 'invalid')]
        for k, v in mutations:
            bad = copy.deepcopy(c); bad[k] = v
            with self.subTest(k=k), self.assertRaises(ValueError): core.validate_config(bad)
        for name in c['outputs']:
            for k, v in [('pin', 17), ('uuid', 'bad'), ('channel', True), ('type', 'relay')]:
                bad = copy.deepcopy(c); bad['outputs'][name][k] = v
                with self.subTest(name=name, k=k), self.assertRaises(ValueError): core.validate_config(bad)
        for name in c['channels']:
            bad = copy.deepcopy(c); bad['channels'][name][1] = 'bad'
            with self.subTest(metric=name), self.assertRaises(ValueError): core.validate_config(bad)

    def test_reading_validation_fails_closed(self):
        self.assertTrue(hasattr(core, 'reading_status'), 'missing reading validation')
        self.assertEqual(core.reading_status({'time': 100, 'value': 20}, 110, 20), 'fresh')
        for field in ['time', 'value']:
            for v in [None, True, False, '20', float('nan'), float('inf'), -float('inf')]:
                r = {'time': 100, 'value': 20}; r[field] = v
                with self.subTest(field=field, value=v): self.assertEqual(core.reading_status(r, 110, 20), 'invalid')
        for r in [{}, None, [], {'value': 20}, {'time':100}]:
            self.assertEqual(core.reading_status(r, 110, 20), 'invalid')
        self.assertEqual(core.reading_status({'time': 0, 'value': 20}, 110, 20), 'invalid')
        self.assertEqual(core.reading_status({'time': 111, 'value':20}, 110, 20), 'future')
        self.assertEqual(core.reading_status({'time': 80, 'value':20}, 110, 20), 'stale')
        self.assertEqual(core.reading_status({'time':100, 'value':20}, 110, None), 'freshness_unconfigured')

    def test_unconfigured_evaluation_shows_readings_without_plans(self):
        self.assertTrue(hasattr(core, 'evaluate'), 'missing evaluation')
        c=core.default_config(); readings={k:{'time':100,'value':20} for k in c['channels']}
        r=core.evaluate(c,readings,110)
        self.assertEqual(r['status'],'unconfigured')
        self.assertEqual(r['readings'],readings)
        self.assertEqual(r['executed_commands'],[])
        self.assertEqual(r['planned_commands'],[])
        self.assertIn('approval_required',r['blockers'])
        self.assertIn('freshness_unconfigured',r['reading_status'].values())

    def approved_fixture(self):
        c=core.default_config(); c.update(approved=True,provenance='OFFLINE TEST ONLY',species_confirmed=True,water_available=True)
        c['thresholds'].update(temperature_min=10,temperature_max=30,humidity_min=70,humidity_max=90,co2_max=1000)
        c['limits'].update(humidifier_max_seconds=2,fan_max_seconds=3,cooldown_seconds=10,stale_seconds=20)
        r={k:{'time':100,'value':v} for k,v in {'co2':1500,'temperature':20,'humidity':60,'dewpoint':12,'vpd':800}.items()}
        return c,r

    def test_approved_complete_fresh_fixture_plans_only(self):
        c,r=self.approved_fixture(); result=core.evaluate(c,r,110,last_humidifier_time=90)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(len(result['planned_commands']),2)
        self.assertEqual(result['executed_commands'],[])
        self.assertEqual({p['channel'] for p in result['planned_commands']},{0})
        self.assertEqual({p['duration_seconds'] for p in result['planned_commands']},{2,3})

    def test_partial_or_invalid_approval_blocks_plans(self):
        c,r=self.approved_fixture()
        for section in ['limits','thresholds']:
            for key in c[section]:
                for value in [None, True, float('nan'), '2']:
                    bad=copy.deepcopy(c); bad[section][key]=value
                    with self.subTest(section=section,key=key,value=value): self.assertEqual(core.evaluate(bad,r,110)['planned_commands'],[])
        for key,value in [('approved',1),('species_confirmed',False),('provenance',None)]:
            bad=copy.deepcopy(c); bad[key]=value
            self.assertEqual(core.evaluate(bad,r,110)['planned_commands'],[])
        for key,value in [('temperature_min',31),('humidity_min',95),('humidity_max',101),('co2_max',-1)]:
            bad=copy.deepcopy(c); bad['thresholds'][key]=value
            with self.subTest(key=key): self.assertEqual(core.evaluate(bad,r,110)['planned_commands'],[])

    def test_humidifier_requires_water_and_cooldown_confirmation(self):
        c,r=self.approved_fixture()
        for water in [None,False,1,'yes']:
            c['water_available']=water
            result=core.evaluate(c,r,110,last_humidifier_time=90)
            with self.subTest(water=water):
                self.assertNotIn(5,[p['pin'] for p in result['planned_commands']])
                self.assertIn('water_unconfirmed',result['blockers'])
        c['water_available']=True
        for last in [None,105,111,True,float('nan')]:
            result=core.evaluate(c,r,110,last_humidifier_time=last)
            with self.subTest(last=last): self.assertNotIn(5,[p['pin'] for p in result['planned_commands']])

    def test_out_of_range_environment_blocks_all_plans(self):
        c,r=self.approved_fixture()
        for key,value in [('temperature',35),('humidity',110),('humidity',-1),('co2',-1),('vpd',-1)]:
            bad=copy.deepcopy(r);bad[key]['value']=value
            with self.subTest(key=key,value=value): self.assertEqual(core.evaluate(c,bad,110,90)['planned_commands'],[])
        for time in [None,0,80,111,float('nan')]:
            bad=copy.deepcopy(r);bad['dewpoint']['time']=time
            with self.subTest(time=time): self.assertEqual(core.evaluate(c,bad,110,90)['planned_commands'],[])

    def test_replay_keeps_original_measurement_timestamps(self):
        self.assertTrue(hasattr(core,'replay'), 'missing replay')
        report={'requests':[{'path':'/api/measurements/last/'+core.INPUT+'/ppm/0/600','http_status':200,'data':{'time':100,'value':991}}]}
        r=core.replay(report)
        self.assertEqual(r['co2'],{'time':100,'value':991})
        self.assertNotIn('humidity',r)
        report['requests'][0]['http_status']=401
        self.assertEqual(core.replay(report),{})

    def test_output_mapping_uses_output_uuid_not_array_index(self):
        self.assertTrue(hasattr(core,'map_outputs'),'missing output mapping')
        devices=[dict(unique_id=o['uuid'],output_type=o['type']) for o in core.OUTPUTS.values()]
        channels=[{'output_id':o['uuid'],'channel':0,'custom_options':json.dumps({'pin':o['pin'],'on_state':1,'state_startup':0,'state_shutdown':0})} for o in core.OUTPUTS.values()]
        data={'output devices':devices[::-1],'output channels':channels,'output states':{devices[0]['unique_id']:{'0':'off'}}}
        result=core.map_outputs(data)
        self.assertEqual(result['humidifier']['pin'],5)
        self.assertEqual(result['fan']['pin'],16)
        self.assertEqual(result['humidifier']['state'],'off')
        self.assertEqual(result['fan']['state'],'unknown')
        del channels[0]['output_id']
        self.assertEqual(core.map_outputs(data)['humidifier']['mapping'],'unknown')

    def test_https_client_rejects_unsafe_urls_and_redirects(self):
        self.assertTrue(hasattr(core,'ReadClient'),'missing secure GET client')
        for url in ['http://pi.local','https://user:pass@pi.local','https://pi.local/?key=x','https://pi.local/path','https://pi.local/#x','https://']:
            with self.subTest(url=url), self.assertRaises(ValueError): core.ReadClient(url,'dummy')
        c=core.ReadClient('https://pi.local','dummy')
        self.assertTrue(c.context.check_hostname)
        import ssl
        self.assertEqual(c.context.verify_mode,ssl.CERT_REQUIRED)
        self.assertIsNone(core.NoRedirect().redirect_request(None,None,302,'',{},'https://other.local'))
        for path in ['/api/outputs/on/x','https://other.local','/api/settings/inputs?x=y','/api/outputs/../on']:
            with self.subTest(path=path), self.assertRaises(ValueError): c.get(path)

    def test_get_client_sanitizes_failure_and_enforces_size_limit(self):
        c=core.ReadClient('https://pi.local','FAKE_TEST_SECRET')
        with patch.object(c._opener,'open',side_effect=RuntimeError('FAKE_TEST_SECRET https://private/key')):
            with self.assertRaisesRegex(RuntimeError,'^read_failed_tls_http_or_payload$'): c.get('/api/settings/inputs')
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,n): return b' '*1048577
        with patch.object(c._opener,'open',return_value=Response()) as opened:
            with self.assertRaises(RuntimeError): c.get('/api/settings/inputs')
            request=opened.call_args.args[0]
            self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.get_header('X-api-key'),'RkFLRV9URVNUX1NFQ1JFVA==')
        class Oversized(Response):
            def read(self,n): return b'['+b' '*1048575+b']'
        with patch.object(c._opener,'open',return_value=Oversized()):
            with self.assertRaises(RuntimeError): c.get('/api/settings/inputs')

    def test_read_snapshot_collects_only_get_inventory_and_channels(self):
        self.assertTrue(hasattr(core,'read_snapshot'),'missing read snapshot')
        paths=[]
        class Client:
            def get(self,path):
                paths.append(path)
                if '/measurements/last/' in path: return {'time':100,'value':20}
                return {}
        r=core.read_snapshot(Client())
        self.assertEqual(set(r['readings']),set(core.CHANNELS))
        self.assertEqual(len(paths),8)
        self.assertTrue(all(p.startswith('/api/') for p in paths))
        self.assertTrue(all(v['mapping']=='unknown' for v in r['outputs'].values()))
        self.assertIn('input_inventory_unverified',r['errors'])
        self.assertIn('channel_inventory_unverified',r['errors'])

    def test_reports_escape_html_and_remove_nonfinite_numbers(self):
        self.assertTrue(hasattr(core,'render_html'),'missing HTML report')
        self.assertTrue(hasattr(core,'safe_data'),'missing JSON sanitizer')
        r={'status':'<script>alert(1)</script>','readings':{'value':float('nan')},'error':'invalid'}
        cleaned=core.safe_data(r)
        self.assertIsNone(cleaned['readings']['value'])
        text=core.render_html(cleaned)
        self.assertNotIn('<script>',text)
        self.assertIn('&lt;script&gt;',text)
        self.assertIn('DRY RUN',text)

    def test_audit_omits_untrusted_errors_credentials_and_payloads(self):
        self.assertTrue(hasattr(core,'write_audit'),'missing sanitized audit')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'audit.jsonl'
            core.write_audit(p,{'status':'blocked','errors':['SECRET https://private'],'api_key':'SECRET','readings':{'x':'SECRET'},'planned_commands':[],'executed_commands':[]})
            core.write_audit(p,{'status':'unconfigured'})
            lines=p.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines),2)
            self.assertNotIn('SECRET',''.join(lines))
            row=json.loads(lines[0]);self.assertEqual(row['executed_count'],0)
            self.assertIn('timestamp_utc',row)

    def run_cli(self,*args):
        import subprocess,sys
        return subprocess.run([sys.executable,'-m','mycodo_scd41',*args],capture_output=True,text=True)

    def test_cli_execute_is_rejected_before_reading_files(self):
        r=self.run_cli('replay','--execute','--report','does-not-exist.json')
        self.assertEqual(r.returncode,2)
        self.assertEqual(json.loads(r.stdout)['error'],'execute_disabled')
        self.assertEqual(json.loads(r.stdout)['executed_commands'],[])

    def test_cli_replay_is_offline_and_keeps_old_times(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'
            p.write_text(json.dumps({'requests':[{'path':'/api/measurements/last/'+core.INPUT+'/ppm/0/600','http_status':200,'data':{'time':100,'value':991}}]}),encoding='utf-8')
            r=self.run_cli('replay','--report',str(p))
            self.assertEqual(r.returncode,0,r.stderr)
            result=json.loads(r.stdout)
            self.assertEqual(result['readings']['co2']['time'],100)
            self.assertEqual(result['source'],'offline_recorded_report_NOT_current_Pi_data')
            self.assertEqual(result['status'],'unconfigured')

    def test_cli_simulation_requires_explicit_test_fixture(self):
        c,readings=self.approved_fixture()
        with tempfile.TemporaryDirectory() as d:
            fixture=Path(d)/'fixture.json'
            fixture.write_text(json.dumps({'label':'OFFLINE TEST ONLY NOT CURRENT PI DATA','config':c,'readings':readings,'now':110,'last_humidifier_time':90}),encoding='utf-8')
            r=self.run_cli('simulate','--fixture',str(fixture))
            self.assertEqual(r.returncode,0,r.stderr)
            result=json.loads(r.stdout)
            self.assertEqual(len(result['planned_commands']),2)
            self.assertEqual(result['executed_commands'],[])
            self.assertEqual(result['source'],'offline_synthetic_TEST_NOT_current_Pi_data')
            fixture.write_text('{}',encoding='utf-8')
            r=self.run_cli('simulate','--fixture',str(fixture))
            self.assertEqual(r.returncode,2)
            self.assertNotIn('Traceback',r.stderr)

    def test_cli_emits_optional_audit_and_escaped_html(self):
        with tempfile.TemporaryDirectory() as d:
            fixture=Path(d)/'report.json';fixture.write_text('{}'.format(json.dumps({'requests':[]})),encoding='utf-8')
            audit=Path(d)/'audit.jsonl';html=Path(d)/'report.html'
            r=self.run_cli('replay','--report',str(fixture),'--audit',str(audit),'--html',str(html))
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads(audit.read_text(encoding='utf-8'))['executed_count'],0)
            self.assertIn('DRY RUN',html.read_text(encoding='utf-8'))

    def test_cli_read_uses_masked_key_and_get_only_client(self):
        self.assertIn('read',self.run_cli('--help').stdout,'missing read command')
        from mycodo_scd41 import __main__ as cli_module
        import contextlib,io,os
        class Client:
            def get(self,path): return {}
        output=io.StringIO()
        with patch.dict(os.environ,{},clear=True), patch('getpass.getpass',return_value='FAKE_TEST_SECRET') as prompt, patch.object(core,'ReadClient',return_value=Client()) as factory, contextlib.redirect_stdout(output):
            self.assertEqual(cli_module.main(['read','--url','https://pi.local','--ca-pem','operator-trusted.pem']),0)
        prompt.assert_called_once()
        factory.assert_called_once_with('https://pi.local','FAKE_TEST_SECRET',ca_pem='operator-trusted.pem')
        self.assertNotIn('FAKE_TEST_SECRET',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['source'],'live_GET_only')
        self.assertEqual(json.loads(output.getvalue())['planned_commands'],[])

    def test_cli_configuration_can_never_enable_execute(self):
        c,r=self.approved_fixture()
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/'config.json';config.write_text(json.dumps(c),encoding='utf-8')
            report=Path(d)/'report.json';report.write_text(json.dumps({'requests':[{'path':'/api/measurements/last/'+core.INPUT+'/'+unit+'/'+str(ch)+'/600','http_status':200,'data':r[metric]} for metric,(ch,unit) in core.CHANNELS.items()]}),encoding='utf-8')
            result=self.run_cli('replay','--config',str(config),'--report',str(report))
            self.assertEqual(result.returncode,0,result.stderr)
            row=json.loads(result.stdout)
            self.assertEqual(row['status'],'blocked')
            self.assertTrue(all(s=='stale' for s in row['reading_status'].values()))
            self.assertEqual(row['planned_commands'],[])
            c['mode']='execute';config.write_text(json.dumps(c),encoding='utf-8')
            result=self.run_cli('replay','--config',str(config),'--report',str(report))
            self.assertEqual(result.returncode,2)
            self.assertEqual(json.loads(result.stdout)['executed_commands'],[])
