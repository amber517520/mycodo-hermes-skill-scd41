import unittest
import os
import monitor

class ParsingTests(unittest.TestCase):
    def test_live_names_parse_channels(self):
        names=['Pi5-401 - Mycodo 8.17.0','SCD-4x (Input e0fe890e)']
        for ch,value,unit in [(0,'901','ppm'),(1,'24.347','C'),(2,'74.037','%'),(3,'19.42','C'),(4,'790.836','Pa')]:
            names += [value,unit,'measurement CH%d | '%ch,'2026/10/18 20:45:25']
        r=monitor.parse_names(names)
        self.assertEqual(r['co2'],901)
        self.assertEqual(r['rh'],74.037)
        self.assertEqual(r['timestamp'],'2026-10-18T20:45:25+08:00')
        with self.assertRaises(ValueError): monitor.parse_names(['login'])

class RuleTests(unittest.TestCase):
    def test_co2_limit_is_1000(self):
        bad=monitor.RULES['CO2_HIGH'][1]
        self.assertFalse(bad(999))
        self.assertTrue(bad(1000))
        self.assertTrue(bad(1001))
    def test_consecutive_unique_samples_and_hysteresis(self):
        t=monitor.dt.datetime(2026,10,18,20,0,tzinfo=monitor.TZ)
        s={}
        def sample(sec,co2):
            return {'timestamp':(t+monitor.dt.timedelta(seconds=sec)).isoformat(),'co2':co2,'temperature':25.,'rh':88.,'dew_point':20.,'vpd':500.}
        s,a=monitor.evaluate(s,sample(0,1000),t.timestamp())
        self.assertEqual(a,[])
        s,a=monitor.evaluate(s,sample(0,1000),t.timestamp()+10)
        self.assertEqual(a,[])
        s,a=monitor.evaluate(s,sample(60,1000),t.timestamp()+60)
        self.assertEqual(a,[])
        s,a=monitor.evaluate(s,sample(120,1000),t.timestamp()+120)
        self.assertTrue(any('CO2_HIGH' in x for x in a))
        for sec in [180,240,300]:
            s,a=monitor.evaluate(s,sample(sec,690),t.timestamp()+sec)
        self.assertTrue(any('CO2_HIGH' in x and 'RECOVERED' in x for x in a))
    def test_all_thresholds_and_stale(self):
        t=monitor.dt.datetime(2026,10,18,20,0,tzinfo=monitor.TZ)
        for field,value,code,count in [('temperature',29,'TEMP_HIGH',3),('temperature',21,'TEMP_LOW',3),('rh',79,'RH_LOW',3),('rh',90,'RH_HIGH',1),('co2',1000,'CO2_HIGH',3)]:
            with self.subTest(code=code):
                s={}
                for i in range(count):
                    now=t+monitor.dt.timedelta(seconds=60*i)
                    r={'timestamp':now.isoformat(),'co2':600.,'temperature':25.,'rh':88.}
                    r[field]=value
                    s,a=monitor.evaluate(s,r,now.timestamp())
                self.assertTrue(any(code in x for x in a))
        s={}
        r={'timestamp':t.isoformat(),'co2':600.,'temperature':25.,'rh':88.}
        s,a=monitor.evaluate(s,r,t.timestamp())
        s,a=monitor.evaluate(s,None,t.timestamp()+181)
        self.assertFalse(s['assessment_allowed'])
        self.assertEqual(a,[])
        s,a=monitor.evaluate(s,None,t.timestamp()+301)
        self.assertTrue(any('DATA_GAP' in x for x in a))
    def test_gap_resets_and_future_rejected(self):
        t=monitor.dt.datetime(2026,10,18,20,0,tzinfo=monitor.TZ)
        r={'timestamp':t.isoformat(),'co2':1000.,'temperature':25.,'rh':88.}
        s,a=monitor.evaluate({},r,t.timestamp())
        r=dict(r,timestamp=(t+monitor.dt.timedelta(seconds=180)).isoformat())
        s,a=monitor.evaluate(s,r,t.timestamp()+180)
        self.assertEqual(a,[])
        s,a=monitor.evaluate({},r,t.timestamp())
        self.assertFalse(s['assessment_allowed'])
        self.assertTrue(any('TIME_INVALID' in x for x in a))

@unittest.skipUnless(os.name == "nt" and os.environ.get("MYCODO_LIVE_TEST") == "1", "Opt-in Windows live-page test: set MYCODO_LIVE_TEST=1")
class IntegrationTests(unittest.TestCase):
    def test_read_visible_mycodo_document(self):
        r=monitor.parse_names(monitor.read_visible_names())
        self.assertGreater(r['co2'],0)
        self.assertTrue(0<=r['rh']<=100)
        self.assertIn('temperature',r)

class PersistenceTests(unittest.TestCase):
    def test_default_collection_does_not_reload_browser(self):
        import tempfile,os
        from pathlib import Path
        from unittest.mock import patch
        names=['SCD-4x (Input e0fe890e)']
        for ch,value in [(0,'600'),(1,'25'),(2,'88'),(3,'20'),(4,'500')]:
            names += [value,'unit','CH%d |'%ch,'2026/10/18 20:00:00']
        t=monitor.dt.datetime(2026,10,18,20,0,tzinfo=monitor.TZ).timestamp()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            with patch.object(monitor,'read_visible_names',return_value=names) as reader:
                monitor.tick(Path(d),now=t)
                reader.assert_called_once_with()
    def test_tick_records_unique_data_and_reports_unavailable(self):
        import tempfile,os
        from pathlib import Path
        t=monitor.dt.datetime(2026,10,18,20,0,tzinfo=monitor.TZ)
        names=['SCD-4x (Input e0fe890e)']
        for ch,value in [(0,'600'),(1,'25'),(2,'88'),(3,'20'),(4,'500')]:
            names += [value,'unit','CH%d |'%ch,'2026/10/18 20:00:00']
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            p=Path(d)
            text=monitor.tick(p,lambda:names,t.timestamp())
            self.assertIn('600',text)
            self.assertEqual(monitor.tick(p,lambda:names,t.timestamp()+10),'')
            self.assertEqual(len((p/'readings.jsonl').read_text().splitlines()),1)
            def failure(): raise ValueError('unavailable')
            monitor.tick(p,failure,t.timestamp()+181)
            self.assertIn('DATA_GAP',monitor.tick(p,failure,t.timestamp()+301))

class LatestPolicyTests(unittest.TestCase):
    def test_latest_candidate_conditions(self):
        self.assertNotIn('CO2_PRE',monitor.RULES)
        self.assertEqual(monitor.RULES['CO2_HIGH'][3],3)
        self.assertFalse(monitor.RULES['RH_LOW'][1](80))
        self.assertTrue(monitor.RULES['RH_LOW'][1](79.9))
        self.assertTrue(monitor.RULES['RH_HIGH'][1](90))
        self.assertEqual(monitor.RULES['RH_HIGH'][3],1)
    def test_saved_control_spec_is_not_an_executor(self):
        c=monitor.CONTROL_RULES
        self.assertFalse(c['device_control_enabled'])
        self.assertFalse(c['notifications']['enabled'])
        self.assertEqual(c['fan']['run_minutes'],3)
        self.assertEqual(c['fan']['cooldown_minutes'],5)
        self.assertEqual(c['humidifier']['run_minutes'],3)
        self.assertEqual(c['humidifier']['cooldown_minutes'],5)
        for device in ['fan','humidifier']:
            self.assertTrue(c[device]['automatic_repeat'])
            self.assertEqual(c[device]['max_cycles_per_episode'],3)
            self.assertEqual(c[device]['failure_count_basis'],'failed_post_cycle_recheck')
            self.assertTrue(c[device]['stop_and_lockout_after_limit'])
            self.assertEqual(c[device]['initial_trigger_samples_count_as_failed_cycles'],False)

    def test_notification_window_boundaries(self):
        for hour,minute,expected in [(8,59,False),(9,0,True),(20,59,True),(21,0,False),(23,0,False)]:
            t=monitor.dt.datetime(2026,10,22,hour,minute,tzinfo=monitor.TZ)
            self.assertEqual(monitor.notification_allowed(t.timestamp()),expected)

if __name__=='__main__': unittest.main()
