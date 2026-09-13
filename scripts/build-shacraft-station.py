#!/usr/bin/env python3
"""Compile the two-floor clock station against observed, unchanged foundation voxels.

No live writes: apply the resulting recipe using scripts/layout.py after QA.
"""
import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'.runtime/station-stage07'

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

survey=module('station_survey',ROOT/'scripts/foundation-survey.py')

def canonical(state):
    if '[' not in state:return state
    name,raw=state[:-1].split('[',1)
    return name+'['+','.join(sorted(raw.split(',')))+']'

def compile_station(before):
    layout=json.loads((ROOT/'docs/references/zone02-interior-v1/layout.json').read_text())
    geometry=json.loads((ROOT/'.runtime/foundations-stage02/foundations-final.geometry.json').read_text())
    foundation=survey.load_snapshot(ROOT/'.runtime/foundations-stage02/after.json.gz')
    foot={(c['x'],c['z']) for c in geometry['cells'] if c['group']=='clock-station'}
    allowed=set(json.loads((STAGE/'context-public.json').read_text())['supported_materials'])
    exterior=module('station_exterior',ROOT/'scripts/station-exterior.py')
    interior=module('station_interior',ROOT/'scripts/station-interior.py')
    states,groups,ext=exterior.compile_exterior(foot,layout)
    decorations,labels,intmeta=interior.compile_interior(foot,layout)
    changes=Counter()
    for p,v in decorations.items():
        if p in states and states[p]!=v:changes[(groups[p],labels[p])]+=1
    states.update(decorations);groups.update(labels)
    rows=[];conflicts=[]
    for p,value in sorted(states.items()):
        state=canonical(value)
        if state.split('[')[0] not in allowed:raise ValueError(f'Material unavailable: {state}')
        observed=before.state(*p)
        if observed==state:continue
        if observed not in survey.AIR:
            try: prior=foundation.state(*p)
            except KeyError:prior=None
            if observed!=prior:conflicts.append({'at':p,'current':observed,'foundation_stage':prior})
        rows.append(dict(zip(('x','y','z'),p))|{'block':state,'expected':observed,'group':groups[p]})
    if conflicts:raise ValueError(f'Unexpected existing changes preserved: {conflicts[:12]} ({len(conflicts)} total)')
    recipe={'version':1,'scope':before.scope,'blocks':rows}
    desired={(b['x'],b['y'],b['z']):b['block'] for b in rows}
    def state(x,y,z):return desired.get((x,y,z),before.state(x,y,z))
    inner=exterior._erode(foot,2)
    floors=[]
    for feet,name in [(99,'vestibule'),(113,'smash')]:
        candidates=set(inner)
        if feet==99:candidates|={(x,z) for x in range(-9,-2) for z in range(-85,-82)}
        clear=sorted(p for p in candidates if all(state(p[0],y,p[1]) in survey.AIR for y in range(feet,feet+4)))
        floors.append({'id':name,'standing_y':feet,'source':{'x':-6,'z':-120},'clear_columns':clear,'min_headroom':4})
    def region(name,x0,x1,y0,y1,z0,z1):
        return {'id':name,'min':{'x':x0,'y':y0,'z':z0},'max':{'x':x1,'y':y1,'z':z1}}
    clear_regions=[region('entrance',-9,-3,99,102,-85,-83)]
    for feet in [99,113]:
        clear_regions += [region(f'cabin-{feet}',-8,-4,feet,feet+3,-122,-118),
                          region(f'lift-door-{feet}',-8,-4,feet,feet+3,-117,-116)]
    clear_regions += [region('ground-entry-aisle',-9,-3,99,102,-115,-86),
                      region('smash-bay-front',-46,11,113,116,-135,-129)]
    metadata={'scope':before.scope,'exterior':ext,'interior':intmeta,'public_floors':floors,
              'clear_regions':clear_regions,'footprint':sorted(foot),
              'containment':{'bounds':{'min':{'x':-79,'y':94,'z':-150},'max':{'x':45,'y':163,'z':-76}},
                  'authorized_caps':[region('ground-entrance-audit-cap',-9,-3,99,110,-84,-84)],
                  'forbidden_y_at_or_above':126,
                  'seeds':[{'id':'vestibule-and-cabin','x':-6,'y':99,'z':-120,'min_y':99,'max_y':110},
                           {'id':'smash-and-cabin','x':-6,'y':113,'z':-120,'min_y':113,'max_y':123}]},
              'compile_summary':{'written_blocks':len(rows),'intended_states':len(states),'materials':dict(Counter(b['block'].split('[')[0] for b in rows)),
                                 'layer_overrides':[{'exterior':a,'interior':b,'count':n} for (a,b),n in changes.items()]}}
    return recipe,metadata

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,default=STAGE/'before.json.gz')
    parser.add_argument('--output',type=Path,default=STAGE/'compiled')
    args=parser.parse_args();recipe,metadata=compile_station(survey.load_snapshot(args.before))
    args.output.mkdir(parents=True,exist_ok=True)
    for name,data in [('station.json',recipe),('station.metadata.json',metadata)]:
        (args.output/name).write_text(json.dumps(data,separators=(',',':'))+'\n')
    print(json.dumps(metadata['compile_summary']))

if __name__=='__main__':main()
