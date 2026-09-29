"""Print a compact verification summary from the real committed dataset."""
import hashlib
import json
from pathlib import Path
from pipeline import GROUPS, OUT, RAW, validate_index

doc = json.loads(OUT.read_text(encoding='utf-8'))
validate_index(doc, require_fresh=True)
files = list(RAW.glob('*/*.json'))
for path in files:
    if hashlib.sha256(path.read_bytes()).hexdigest() != path.stem:
        raise ValueError('Snapshot checksum mismatch: ' + str(path))
derived = OUT.parents[2]/'data'/'derived'/'index.json'
if derived.read_bytes() != OUT.read_bytes():
    raise ValueError('Published data differs from derived source')
summary = {
    'dataThrough': doc['dataThrough'],
    'generatedAt': doc['generatedAt'],
    'rawSnapshots': len(files),
    'rawBytes': sum(p.stat().st_size for p in files),
    'allSnapshotHashesVerified': True,
    'publishedEqualsDerived': True,
    'pricesAsOf': doc['pricesAsOf'],
    'completeWeeks': sum(w['completeWeek'] for w in doc['weeks']),
    'missingModelDates': doc['coverage'].get('missingModelDates', []),
    'series': {},
}
for key in GROUPS:
    available = [w for w in doc['weeks'] if w['completeWeek'] and w['series'][key]['tokens'] is not None]
    latest = doc['weeks'][-1]['series'][key]
    summary['series'][key] = {
        'firstAvailableWeek': available[0]['start'] if available else None,
        'availableWeeks': len(available),
        'cappedWeeks': sum(w['series'][key]['capped'] for w in available),
        'baseline': doc['baselines'][key],
        'latest': {k: v for k,v in latest.items() if k!='apps'},
    }
print(json.dumps(summary, indent=2))
