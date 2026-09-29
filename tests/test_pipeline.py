import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pipeline', Path(__file__).parents[1]/'scripts/pipeline.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class PipelineTests(unittest.TestCase):
    def row(self, id=1, tokens='100', requests=10):
        return {'app_id':id,'app_name':'Test fixture','rank':1,'total_tokens':tokens,'total_requests':requests}

    def test_union_deduplicates_and_rejects_conflicts(self):
        c={'personal-agent':[self.row()], 'cli-agent':[self.row()]}
        self.assertEqual(len(p.merge_apps(c,c)),1)
        c['cli-agent']=[self.row(tokens='101')]
        with self.assertRaises(ValueError):p.merge_apps(c,c)

    def test_counts_preserve_big_integers_and_reject_invalid(self):
        self.assertEqual(p.number('9007199254740993'),9007199254740993)
        for v in [-1,True,1.5,'NaN',None]:
            with self.assertRaises(ValueError):p.number(v)

    def test_calendar_excludes_current_week(self):
        self.assertEqual(p.last_sunday(dt.date(2026,9,29)),dt.date(2026,9,27))
        self.assertEqual(p.last_sunday(dt.date(2026,9,27)),dt.date(2026,9,20))
        self.assertEqual(next(p.windows(dt.date(2025,1,12))),('2025-01-01','2025-01-05'))

    def test_payload_date_and_duplicate_guards(self):
        params=p.app_params('2025-01-06','2025-01-12','personal-agent')
        payload={'meta':{'start_date':'2025-01-06','end_date':'2025-01-12','as_of':'2026-09-29T00:00:00Z'},'data':[self.row()]}
        p.validate_payload('datasets/app-rankings',params,payload)
        payload['data'].append(self.row())
        with self.assertRaises(ValueError):p.validate_payload('datasets/app-rankings',params,payload)
        payload['data']=[];payload['meta']['start_date']='2025-01-07'
        with self.assertRaises(ValueError):p.validate_payload('datasets/app-rankings',params,payload)

    def test_baseline_growth_and_missing_window(self):
        weeks=[]
        for i,(start,end) in enumerate(p.windows(dt.date(2025,2,16))):
            weeks.append({'start':start,'end':end,'completeWeek':i>0,'series':{k:{'tokens':str(100*(i+1))} for k in p.GROUPS}})
        baseline=p.derive(weeks)
        self.assertEqual(baseline['PATI']['value'],300)
        self.assertIsNone(weeks[0]['series']['PATI']['index'])
        self.assertAlmostEqual(weeks[3]['series']['PATI']['index'],400/3)
        self.assertIsNone(weeks[3]['series']['PATI']['ma4'])
        self.assertEqual(weeks[4]['series']['PATI']['ma4'],350)
        weeks[2]['series']['PATI']['tokens']=None
        baseline=p.derive(weeks)
        self.assertEqual(baseline['PATI']['value'],200)
        self.assertIsNone(weeks[4]['series']['PATI']['ma4'])
        self.assertIsNone(p.growth(10,0))

    def test_snapshot_integrity_and_append_only(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(p,'RAW',Path(directory)):
            p.snapshot('models',{}, {'data':[{'id':'test','pricing':{'prompt':'0.001'}}]})
            first=list(Path(directory).rglob('*.json'))[0]
            old=first.read_bytes()
            p.snapshot('models',{}, {'data':[{'id':'test','pricing':{'prompt':'0.002'}}]})
            self.assertEqual(first.read_bytes(),old)
            self.assertEqual(len(list(Path(directory).rglob('*.json'))),2)
            first.write_text('{}')
            with self.assertRaises(ValueError):p.cached('models',{})

    def test_uninitialized_never_passes_freshness(self):
        doc={'schemaVersion':1,'weeks':[],'status':'awaiting_credentials','dataThrough':None}
        p.validate_index(doc)
        with self.assertRaises(ValueError):p.validate_index(doc,require_fresh=True)

if __name__=='__main__':unittest.main()
