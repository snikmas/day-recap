import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cli
import core

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = {'timezone':'Asia/Shanghai','timezone_mode':'computer','roots':[str(self.root)],'excludes':[],
                    'schedule':{'start_date':'2026-10-08','daily_time':None,'enabled':False}}
        core.json_write(self.root/'preferences.json',self.cfg)
    def tearDown(self):
        self.temp.cleanup()
    def run_cli(self,*args):
        out=io.StringIO()
        with patch('sys.argv',['cli.py','--data-dir',str(self.root),*args]),patch('sys.stdout',out):
            cli.main()
        return json.loads(out.getvalue())
    def test_computer_zone_changes_new_preparation_only(self):
        core.commit(self.root,'2026-10-08','existing',{'timezone':'Asia/Shanghai','coverage':[]})
        with patch.object(core,'computer_zone',return_value='Europe/Paris'),patch.object(cli,'prepare',return_value={}) as prep:
            self.run_cli('collect','2026-10-09')
        self.assertEqual(prep.call_args.args[1]['timezone'],'Europe/Paris')
        self.assertEqual(core.completion(self.root,'2026-10-08')['timezone'],'Asia/Shanghai')
    def test_fixed_zone_is_preserved(self):
        self.cfg['timezone_mode']='fixed';core.json_write(self.root/'preferences.json',self.cfg)
        with patch.object(core,'computer_zone',side_effect=AssertionError('should not detect')),patch.object(cli,'prepare',return_value={}) as prep:
            self.run_cli('collect','2026-10-09')
        self.assertEqual(prep.call_args.args[1]['timezone'],'Asia/Shanghai')
    def test_missing_or_duplicate_segment_blocks_save(self):
        draft=self.root/'draft.md';draft.write_text('draft')
        manifest=self.root/'manifest.json';core.json_write(manifest,{'key':'2026-10-08','segments':[{'id':'s1'},{'id':'s2'}]})
        for processed in [[],['s1'],['s1','s2','s2']]:
            args=['commit','2026-10-08','--draft',str(draft),'--manifest',str(manifest)]
            for name in processed:args+=['--processed',name]
            with self.assertRaises(RuntimeError):self.run_cli(*args)
        self.assertFalse(core.report_path(self.root,'2026-10-08').exists())
    def test_setup_preserves_native_schedule_identity(self):
        self.cfg['schedule'].update(automation_id='daily-recap',runtime='heartbeat')
        core.json_write(self.root/'preferences.json',self.cfg)
        self.run_cli('setup','--root',str(self.root),'--start-date','2026-10-09')
        saved=core.read_json(self.root/'preferences.json')
        self.assertEqual(saved['schedule']['automation_id'],'daily-recap')
        self.assertEqual(saved['schedule']['start_date'],'2026-10-08')

    def test_noncanonical_date_cannot_create_second_report_for_same_day(self):
        with self.assertRaises(ValueError):core.report_path(self.root,'20261008')

    def test_current_or_future_week_is_rejected(self):
        with self.assertRaises(ValueError):self.run_cli('weekly','2099-W01')
    def test_single_start_notice_does_not_complete_or_duplicate(self):
        self.assertTrue(core.start_notice(self.root,'2026-10-08'))
        self.assertFalse(core.start_notice(self.root,'2026-10-08'))
        self.assertIsNone(core.completion(self.root,'2026-10-08'))
        self.cfg['schedule']['daily_time']='06:00'
        from datetime import datetime,timezone
        due=core.pending(self.root,self.cfg,datetime(2026,10,9,1,tzinfo=timezone.utc))
        self.assertIn('2026-10-08',due['daily'])
