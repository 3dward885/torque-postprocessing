"""Reproduce the diagnosed fixed-field scan; exclusions are simulated test actions."""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cli import load_entry, run_entry
import field_quality as fq
from pipeline import UPSTREAM_IMPLEMENTATION, process
from storage import load_session, save_session, treated_text
from output_settings import save_output_dat
from treated_plots import molar_text, normalization, grouped_samples, export_treated_plots
from io_profiles import sha256


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    before=json.loads((ROOT/'validation/v16_before/before.json').read_text())
    assert UPSTREAM_IMPLEMENTATION==before['upstream_implementation']
    results={}
    for name,expected in before['results'].items():
        raw,cfg=load_session(ROOT/'examples'/f'{name}.json')[0]
        obj,cfg=load_entry(raw,cfg)
        cfg['field_quality'].update(condition='changing', source='Diagnostic numerical regression policy; not experimental permission')
        r=process(obj,cfg)
        assert treated_text(r).encode()==(ROOT/'validation/v16_before'/f'{name}.dat').read_bytes()
        assert molar_text(r,normalization(before['synthetic_normalization'])).encode()==(ROOT/'validation/v16_before'/f'{name}_molar.dat').read_bytes()
        assert {p['pass_id']:p['baseline_binding'] for p in r['passes']}==expected['bindings']
        save_session(output/f'{name}.json',[(raw,cfg)])
        results[name]={'rows':r['rows'],'exact_DAT_and_molar':True,'bindings_unchanged':True}
    raw,cfg,choice=load_session(ROOT/'validation/mixed_field_20261006/saved_session.json',include_output=True)[0]
    obj,cfg=load_entry(raw,cfg)
    assert sha256(raw)=='9ea4fec5a273b727546139b899ec1e2c1c94177e39191548076d321dc4237355'
    cfg['field_quality'].update(limit_T='0.5',source='User entered 0.5 T and approved rounded-span >= limit rule, 6 October 2026')
    detected=process(obj,cfg,partial=True)
    assert detected['field_review']['P003']['evidence']['span_T']=='0.499968148'
    assert detected['field_review']['P003']['status']=='Review required'
    assert list(detected['processing_errors'])==['P003']
    assert detected['rows']==777 and not detected['exportable']
    assert not detected['inventory'][2]['excluded']
    save_session(output/'Rot1_REVIEW_REQUIRED.json',[(raw,cfg,choice)])
    testcfg=fq.decide(obj,cfg,'P003','exclude','SIMULATED SOFTWARE TEST ACTION — not user exclusion approval')
    after=process(obj,testcfg)
    prior=json.loads((ROOT/'validation/v16_before/Rot1_before_result.json').read_text())
    for p in after['passes']:
        old=next(x for x in prior['passes'] if x['pass_id']==p['pass_id'])
        assert p['D']==old['D'] and p['baseline_binding']==old['baseline_binding']
    assert after['rows']==777 and after['raw_rows']==1146
    assert sum(r['retention']=='explicitly excluded' for r in after['ledger'])==41
    assert sum(r['role']=='background' for r in after['ledger'])==328
    assert len(after['field_review']['P002']['evidence']['source_lines'])==41
    save_session(output/'Rot1_SIMULATED_EXCLUSION.json',[(raw,testcfg,choice)])
    save_output_dat(after,output/'Rot1_SIMULATED_EXCLUSION_treated.dat',choice)
    plots=export_treated_plots([(after,choice)],output/'SIMULATED_EXCLUSION_plots')
    rotation,norm,groups=grouped_samples(after,choice)
    from decimal import Decimal
    assert [s['pass_id'] for s in groups[Decimal('2')]]==['P001','P002','P004']
    assert sum(len(s['tokens']) for s in groups[Decimal('2')])==123
    prior_molar=molar_text(prior,normalization(choice)).splitlines()[1:]
    after_molar=molar_text(after,norm).splitlines()[1:]
    assert after_molar==prior_molar[:82]+prior_molar[123:]
    # Use the actual export entry shape, preserving recorded user normalization.
    from plots import font_status
    results['Rot1']={'raw_rows':1146,'background_rows':328,'explicitly_excluded_test_rows':41,
        'treated_rows':777,'exact_unaffected_D_and_bindings':True,'P003':after['field_review']['P003'],
        'simulated_decision':True,'font':font_status(),'plots':str(plots),'2K_points':123,'exact_unaffected_molar':True}
    (output/'result.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
    for path,h in before['protected_files'].items():
        assert sha256(path)==h,path
    for path,h in before['archive_sha256'].items():
        assert sha256(ROOT/path)==h,path
    results['preservation']='all snapshot protected inputs and archives unchanged'
    (output/'report.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('PASS: original fingerprint, three exact ordinary/molar replays, baseline bindings, actual P003 detection, simulated whole-scan exclusion, protected hashes')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output.resolve())
