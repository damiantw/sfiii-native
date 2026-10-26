"""Write an external, revision-specific selection for a compatible AI trial runtime."""
import argparse
import json
from pathlib import Path

from worker import atomic_json, external


def selection(report, profile):
    rows=[p for p in report if p['profile']==profile]
    if len(rows)!=3 or {p['model'] for p in rows}!={'video','anime','general'}:
        raise ValueError('Exactly three model packs are required for this disc profile')
    if len({p['revision'] for p in rows})!=1:
        raise ValueError('Packs belong to different disc revisions')
    for row in rows:
        path=external(row['path'])
        manifest=json.loads((path/'manifest.json').read_text())
        for key in ('revision','profile','model','material_count'):
            if manifest[key]!=row[key]:raise ValueError('Pack manifest mismatch: '+key)
        if not row['material_count']:raise ValueError('Pack is empty')
    return dict(schema=1,profile=profile,revision=rows[0]['revision'],
        models={p['model']:str(Path(p['path']).resolve()) for p in rows},
        missing={p['model']:len(p['missing']) for p in rows},
        scope=('World and CHR/CHP character artwork. Menus remain original; unmatched frames use original artwork.'
               if any(p.get('character_material_count') for p in rows) else
               'World textures only. Unmatched materials use original artwork. Menus and sprites remain original.'))


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    target=external(args.output)
    if target.exists():raise ValueError('Selection already exists; preserve it before replacing')
    atomic_json(target,selection(json.loads(args.report.read_text()),args.profile))


if __name__=='__main__':main()
