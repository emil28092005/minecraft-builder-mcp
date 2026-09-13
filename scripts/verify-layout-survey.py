#!/usr/bin/env python3
"""Compare every live map column to the planned visible result and inspect hidden water."""
import argparse
from collections import defaultdict
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True)
    p.add_argument('--layout',type=Path,action='append',required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();before=json.loads(args.before.read_text());after=json.loads(args.after.read_text())
    for key in ('world_uuid','min_x','max_x','min_z','max_z','width','length'):
        if before[key]!=after[key]:raise ValueError('Map scopes differ: '+key)
    w=before['width'];expected_y=before['surface_y'].copy()
    expected_m=[before['palette'][i] for i in before['material_index']]
    original_m=expected_m.copy();targets=set();planned_blocks=0
    for path in args.layout:
        layout=json.loads(path.read_text())
        if layout['scope']['world_id']!=before['world_uuid']:raise ValueError('Layout world differs')
        for b in sorted(layout['blocks'],key=lambda b:b['y']):
            i=(b['z']-before['min_z'])*w+b['x']-before['min_x'];targets.add((b['x'],b['y'],b['z']));planned_blocks+=1
            if b['y']>=expected_y[i]:expected_y[i]=b['y'];expected_m[i]=b['block']
    observed=[after['palette'][i] for i in after['material_index']]
    mismatches=[i for i in range(len(expected_y)) if expected_y[i]!=after['surface_y'][i] or expected_m[i]!=observed[i]]
    if mismatches:raise ValueError(f'{len(mismatches)} unexpected surface columns; first indices {mismatches[:8]}')
    hidden_water=defaultdict(list)
    for i,material in enumerate(original_m):
        if material=='minecraft:water' and observed[i]!='minecraft:water':
            x=i%w+before['min_x'];z=i//w+before['min_z'];y=before['surface_y'][i]
            hidden_water[(x//16,z//16,y)].append((x,y,z))
    spec=importlib.util.spec_from_file_location('terrain',ROOT/'scripts/terrain.py')
    terrain=importlib.util.module_from_spec(spec);spec.loader.exec_module(terrain)
    backend=terrain.Backend(ROOT/'.runtime/server/plugins/MinecraftBuilderMCP/config.yml')
    context=backend.call('project_context')
    if context['world_id']!=before['world_uuid']:raise ValueError('Live verification world differs')
    verified_water=0
    for points in hidden_water.values():
        lo={axis:min(point[j] for point in points) for j,axis in enumerate(('x','y','z'))}
        hi={axis:max(point[j] for point in points) for j,axis in enumerate(('x','y','z'))}
        read=backend.call('region_inspect',min=lo,max=hi,detail='blocks')
        states={tuple(b['pos'][axis] for axis in ('x','y','z')):b['state'] for b in read['blocks']}
        for point in points:
            if not states[point].startswith('minecraft:water['):raise ValueError('Water changed beneath a marker: '+str(point))
            verified_water+=1
    report={'world':before['world'],'source':'live Paper surface maps + bounded RPC water reads',
            'verified_surface_columns':len(expected_y),'surface_mismatches':0,
            'unique_marker_blocks':len(targets),'planned_writes':planned_blocks,
            'original_water_columns':original_m.count('minecraft:water'),'water_columns_obscured_by_markers':verified_water,
            'water_obscured_by_markers_verified_intact':True,
            'height_unchanged_columns':sum(a==b for a,b in zip(before['surface_y'],after['surface_y'])),
            'capture_started_at':after['capture_started_at'],'capture_finished_at':after['capture_finished_at'],
            'atomic_snapshot':False,'note':'World edits were idle during each capture. Terrain follows its original heights; raised markers represent future structures, not finished traversable paths.'}
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':main()
