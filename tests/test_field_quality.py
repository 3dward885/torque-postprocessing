"""Synthetic field trajectories; numerical limits here are test configuration only."""
import copy
from decimal import Decimal
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import field_quality as fq
import test_workflow
from test_core import synthetic
from pipeline import process, refinalize, verify_export, migrate_config
from io_profiles import InputError, read_raw
from cli import main
from storage import save_session, load_session, treated_text


class FieldQualityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_workflow.WorkflowTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def data(self, field_start="1.5", span=".499968148", reverse=False):
        rows = synthetic()
        start, step = Decimal(field_start), Decimal(span)/40
        for i in range(41):
            rows[i][1] = str((start + (step*i if reverse else -step*i))*10000)
        obj, cfg = self.fixture.write(rows)
        cfg['field_quality'] = fq.defaults()
        cfg['field_quality'].update(limit_T='0.50', source='Synthetic test limit')
        return obj, cfg

    def test_rounded_boundary_both_directions_and_signed_fields(self):
        for base in ('1.5', '-1.5', '0'):
            for reverse in (True, False):
                for span, pending in (('.49499999',False),('.495',True),('.49500001',True),('.5',True),('.00009',False)):
                    obj,cfg = self.data(base,span,reverse)
                    r = fq.configure(obj,cfg).field_review['P001']
                    self.assertEqual(r['status']=='Review required',pending,(base,span,reverse))
                    self.assertEqual(Decimal(r['evidence']['span_T']),Decimal(span))
        obj,cfg=self.data()
        self.assertEqual(fq.configure(obj,cfg).field_review['P001']['evidence']['review_span_T'],'0.50')

    def test_invalid_limits_and_old_settings_require_configuration(self):
        obj,cfg=self.data()
        for value in ('bad','NaN','Infinity','-1',True):
            cfg['field_quality']['limit_T']=value
            with self.assertRaises(InputError): fq.configure(obj,cfg)
        del cfg['field_quality']
        migrated=migrate_config(cfg)
        self.assertEqual(migrated['field_quality']['condition'],'fixed')
        self.assertEqual(migrated['field_quality']['limit_T'],'')
        with self.assertRaisesRegex(InputError,'Field review required'): process(obj,migrated)
        migrated['field_quality']['schema_version']=2
        with self.assertRaises(InputError): process(obj,migrated)

    def test_detection_preserves_complete_rows_and_blocks_exports(self):
        obj,cfg=self.data()
        cfg['acquisition']['angle_range_deg']=['0','150']
        r=process(obj,cfg,partial=True)
        self.assertEqual(len(r['ledger']),82)
        self.assertEqual(len(r['field_review']['P001']['evidence']['source_lines']),41)
        self.assertFalse(r['inventory'][0]['excluded'])
        self.assertFalse(r['exportable'])
        with self.assertRaises(InputError): verify_export(r)
        with self.assertRaises(InputError): process(obj,cfg)

    def test_explicit_decision_bindings_and_no_silent_reuse(self):
        obj,cfg=self.data()
        permitted=fq.decide(obj,cfg,'P001','permit_changing','Simulated test permission')
        r=process(obj,permitted)
        verify_export(r)
        self.assertEqual(r['rows'],41)
        changed=copy.deepcopy(permitted)
        changed['field_quality']['limit_T']='0.6'
        with self.assertRaisesRegex(InputError,'does not match'): process(obj,changed)
        altered=copy.deepcopy(obj)
        altered.sha256='different'
        changed=copy.deepcopy(permitted); changed['input_sha256']='different'
        self.assertEqual(fq.configure(altered,changed).field_review['P001']['status'],'Review required')
        result=copy.deepcopy(r); result['config']['field_quality']['limit_T']='0.6'
        with self.assertRaises(InputError): verify_export(result)
        with self.assertRaises(InputError): refinalize(r,changed)

    def test_entire_exclusion_independent_scan_and_background(self):
        rows=synthetic()
        rows=rows[:41]+rows[:41]+rows[41:]
        obj,cfg=self.fixture.write(rows)
        cfg['field_quality']=fq.defaults()
        cfg['field_quality'].update(limit_T='.5',source='Synthetic limit')
        before=process(obj,cfg)
        cfg=fq.decide(obj,cfg,'P001','exclude','Simulated whole-scan decision')
        after=process(obj,cfg)
        self.assertEqual(after['rows'],41)
        self.assertEqual(after['output_rows'],before['output_rows'][41:])
        self.assertEqual(sum(r['retention']=='explicitly excluded' for r in after['ledger']),41)
        self.assertEqual(after['passes'][0]['pass_id'],'P002')
        cfg=fq.decide(obj,cfg,'P003','exclude','Simulated background rejection')
        after=process(obj,cfg,partial=True)
        self.assertFalse(after['exportable'])
        self.assertIn('missing',after['processing_errors']['P002'])

    def test_session_cli_and_unresolved_error(self):
        obj,cfg=self.data()
        session=self.fixture.root/'session.json'
        save_session(session,[(obj.path,cfg)])
        saved=load_session(session)[0][1]
        self.assertEqual(saved['field_quality'],cfg['field_quality'])
        with patch('sys.stdout',new_callable=io.StringIO) as out:
            status=main(['process','--session',str(session),'--dat',str(self.fixture.root/'blocked.dat')])
        self.assertEqual(status,1)
        self.assertIn('P001',out.getvalue())
        self.assertFalse((self.fixture.root/'blocked.dat').exists())
        cfg=fq.decide(obj,cfg,'P001','permit_changing','Simulated test permission')
        save_session(self.fixture.root/'allowed.json',[(obj.path,cfg)])
        dat=self.fixture.root/'allowed.dat'
        with patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['process','--session',str(self.fixture.root/'allowed.json'),'--dat',str(dat)]),0)
        self.assertEqual(dat.read_text(),treated_text(process(obj,cfg)))

    def test_unresolved_unused_background_also_blocks_export(self):
        obj,cfg=self.fixture.write(synthetic(second_background=True))
        cfg['field_quality']=fq.defaults()
        cfg['field_quality'].update(limit_T='.5',source='Synthetic test limit')
        cfg['overrides']['P001']={'identity':obj.passes[0].identity,'background':'P002','source':'Test selection'}
        cfg['field_quality']['decisions']['P003']={'invalid':'stale'}
        result=process(obj,cfg,partial=True)
        self.assertEqual(result['rows'],41)
        self.assertFalse(result['exportable'])
        with self.assertRaises(InputError): verify_export(result)

if __name__=='__main__': unittest.main()
