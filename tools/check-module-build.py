"""Check that every audited module and discovered entry was emitted, outside source."""
import argparse
import json
from pathlib import Path
import re
from importlib.util import spec_from_file_location, module_from_spec

spec = spec_from_file_location('audit_modules',Path(__file__).with_name('audit-modules.py'))
audit = module_from_spec(spec)
spec.loader.exec_module(audit)

ap = argparse.ArgumentParser(__doc__)
ap.add_argument('--audit',type=Path,required=True)
ap.add_argument('--generated',type=Path,required=True)
ap.add_argument('--out',type=Path,required=True)
ap.add_argument('--require-complete',action='store_true',help='Also fail on unresolved static audit findings')
a = ap.parse_args()
generated, out = audit.external(a.generated), audit.external(a.out)
report = json.loads(a.audit.read_text())
profile = json.loads(a.audit.with_name('candidate-profile.json').read_text())
names = {m['file']:m['name'] for m in profile['modules']}
missing, entries = [], 0
for row in report['modules']:
    if 'entry_points' not in row:
        continue
    name = names[row['file']]
    table = generated/f'p_{name.lower()}_table.cpp'
    actual = set(re.findall(r'\{0x([0-9A-Fa-f]{8})u,\s*f_',table.read_text())) if table.exists() else set()
    expected = set(row['entry_points'])
    absent = sorted(expected-{e.upper() for e in actual})
    entries += len(expected)
    if absent:missing.append(dict(module=name,entries=absent))
blockers = dict(mapping_or_entry=len(report['blockers']),
                indirect_sites=sum(r.get('discovery',{}).get('unresolved indirect',0) for r in report['modules']),
                discovery_problems=sum(len(r.get('problems',[])) for r in report['modules']),
                cross_module_records=len(report['cross_module_gaps']))
complete = not missing and not any(blockers.values())
result = dict(modules=len(names),expected_entries=entries,missing=missing,
              static_findings=blockers,complete_static_audit=complete,
              caveat='Emission check only. Does not certify discovery completeness or gameplay.')
out.write_text(json.dumps(result,indent=2)+'\n')
print(f'{len(names)} modules, {entries} audited entries, {len(missing)} modules with missing emitted entries')
if a.require_complete and not complete:print('Full static audit gate FAILED: unresolved findings remain')
raise SystemExit(bool(missing) or (a.require_complete and not complete))
