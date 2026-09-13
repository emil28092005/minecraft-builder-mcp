#!/usr/bin/env python3
"""Compile the reviewed foundations and streets into a checked, reversible block plan.

No server writes here. A full live voxel survey is required, and differences from
the known natural world + previous marker receipts are protected, not adopted.
Apply the resulting JSON with scripts/layout.py.
"""
import argparse
from collections import Counter, deque
import importlib.util
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

geometry=module('foundation_geometry',ROOT/'scripts/foundation-study/geometry.py')
survey=module('foundation_survey',ROOT/'scripts/foundation-survey.py')
N=((1,0),(-1,0),(0,1),(0,-1))


def distances(mask):
    dist={p:0 for p in mask if any((p[0]+dx,p[1]+dz) not in mask for dx,dz in N)}
    q=deque(dist)
    while q:
        x,z=q.popleft()
        for dx,dz in N:
            p=(x+dx,z+dz)
            if p in mask and p not in dist:dist[p]=dist[(x,z)]+1;q.append(p)
    return dist


def compile_plan(design,layout,before,original,marker_documents):
    scope=before.document['scope'];geo=geometry.build_geometry(design,layout);cells=geo['cells']
    mask=set(cells);edge=distances(mask);desired={};groups={}
    known={}
    for doc in marker_documents:
        for b in doc['blocks']:known[(b['x'],b['y'],b['z'])]=b['block']
    def natural(x,z):
        i=(z-original['min_z'])*original['width']+x-original['min_x']
        return original['surface_y'][i],original['palette'][original['material_index'][i]]
    def predicted(x,y,z):
        if (x,y,z) in known:return known[(x,y,z)]
        h,material=natural(x,z)
        if y>h:return 'minecraft:air'
        if material=='minecraft:water':raise ValueError('Water column outside foundation scope')
        if y==h:return material+'[snowy=false]' if material=='minecraft:grass_block' else material
        return 'minecraft:dirt' if material=='minecraft:grass_block' and y>=h-3 else 'minecraft:stone'
    def put(x,y,z,block,group):
        if not block.startswith('minecraft:'):block='minecraft:'+block
        desired[(x,y,z)]=block;groups[(x,y,z)]=group
    # Remove only old survey blocks within this stage's exact footprint + 1-column
    # cleanup margin. Outside district markers remain unchanged.
    cleanup=mask|{(x+dx,z+dz) for x,z in mask for dx,dz in N}
    for (x,y,z),state in known.items():
        if (x,z) not in cleanup:continue
        try:before.state(x,y,z)
        except (KeyError,ValueError):continue  # Only the optional cleanup margin may extend beyond the survey.
        h,m=natural(x,z)
        if y>h:new='minecraft:air'
        elif y==h:new=m+'[snowy=false]' if m=='minecraft:grass_block' else m
        else:continue
        put(x,y,z,new,'remove-obsolete-survey')

    road_clear={tuple(p) for r in geo['routes'] for p in r['clear_cells']}
    road_buffer=road_clear|{(x+dx,z+dz) for x,z in road_clear for dx,dz in N}
    # Exact solid footings and two structural courses beneath every walking deck.
    for (x,z),c in cells.items():
        y=c['block_y'];h,_=natural(x,z);d=edge[(x,z)];group=c['group']
        bottom=min(h-1,y-2) if d<=1 else min(h,y-2)
        for yy in range(bottom,y):
            block='stone'
            if d==0:
                block='deepslate_bricks' if yy<=h+1 else 'stone_bricks'
                if yy==y-1:block='polished_andesite'
                if (x+z)%12 in (0,1) and yy>h+1:block='smooth_sandstone'
            elif d==1 and yy==y-1:block='stone_bricks'
            put(x,yy,z,block,group+'-foundation')
        # Clear all natural overburden and former stakes above the finished floor.
        for yy in range(y+1,max(h+2,y+4)+1):put(x,yy,z,'air',group+'-clearance')
        if c['kind']=='stairs':
            paving=f"stone_brick_stairs[facing={c['facing']},half=bottom,shape=straight,waterlogged=false]"
        elif not c['clear'] or d==0:paving='polished_andesite'
        elif d==1:paving='stone_bricks'
        elif d==2:paving='smooth_sandstone'
        elif group=='clock-station':
            # Quiet structural floor; regular narrow foundation setting-out bands.
            paving='stone_bricks' if x%16==0 or z%16==0 else 'smooth_stone'
        elif group in ('arrival-hex','station-forecourt'):
            paving='smooth_sandstone'
            if x%12==0 or z%12==0:paving='smooth_stone'
        else:
            paving='smooth_stone'
            if c['kind']=='full' and ((x if 'radial' in group or 'ring-' in group else z)%8==0):paving='stone_bricks'
        put(x,y,z,paving,group+'-paving')

    # Green inset medallion. All tesserae are flush with the arrival paving.
    hexagon=[(round(16*math.sin(math.pi/3*i)),round(9-16*math.cos(math.pi/3*i))) for i in range(6)]
    medallion=geometry.polygon_cells(hexagon);md=distances(medallion)
    for x,z in medallion:
        put(x,95,z,'smooth_quartz' if md[(x,z)]<=1 else 'green_concrete','arrival-medallion')
    glyph=['01110','11000','11000','01110','00011','00011','01110']
    for row,bits in enumerate(glyph):
        for col,on in enumerate(bits):
            if on=='1':
                for dx in (0,1):
                    for dz in (0,1):put(-5+col*2+dx,95,2+row*2+dz,'smooth_quartz','arrival-medallion')

    # Keep the future tower and pavilion footing outlines readable in the deck.
    for f in layout['features']:
        if f['id'] not in ('station-clock-base','station-pavilion--63','station-pavilion-29'):continue
        vertices=f['points'];outline=geometry.polygon_cells(vertices)
        for x,z in outline:
            if any((x+dx,z+dz) not in outline for dx,dz in N):put(x,98,z,'polished_andesite','station-structural-bands')

    # A shallow blind arcade breaks up the tall western station retaining wall.
    # Each opening is one block deep, with an intact solid backing and lintel.
    for center in (-132,-124,-116,-108):
        for offset in range(-2,3):
            z=center+offset;h,_=natural(-74,z);top=94-abs(offset)
            for y in range(max(h+2,85),top+1):
                put(-74,y,z,'air','station-west-blind-arcade')
                put(-73,y,z,'deepslate_bricks','station-west-blind-arcade')
            if top>=h+2:put(-74,top+1,z,'smooth_sandstone','station-west-arch-stones')
    for z0 in (-138,-128,-120,-112,-104,-99):
        for z in (z0,z0+1):
            h,_=natural(-75,z)
            for y in range(h-1,98):put(-75,y,z,'deepslate_bricks' if y<h+2 else 'stone_bricks','station-west-pilasters')
            put(-75,98,z,'smooth_sandstone','station-west-pilasters')

    # Guard exposed edges while reserving every planned road opening at full width.
    rail={}
    for (x,z),c in cells.items():
        if edge[(x,z)]!=0:continue
        if c['clear'] and (x,z) in road_buffer:continue
        outside=[(x+dx,z+dz) for dx,dz in N if (x+dx,z+dz) not in cells]
        drop=max([c['block_y']-natural(*p)[0] for p in outside] or [0])
        if drop>=3 or c['group']=='station-entrance-stair':rail[(x,z)]=c['block_y']+1
    for (x,z),y in rail.items():
        props={name:('low' if (x+dx,z+dz) in rail and abs(rail[(x+dx,z+dz)]-y)<=1 else 'none')
               for name,(dx,dz) in {'east':(1,0),'north':(0,-1),'south':(0,1),'west':(-1,0)}.items()}
        straight=(props['east']==props['west']=='low' and props['north']==props['south']=='none') or (props['north']==props['south']=='low' and props['east']==props['west']=='none')
        up='false' if straight and (x+z)%8 else 'true'
        state=f"stone_brick_wall[east={props['east']},north={props['north']},south={props['south']},up={up},waterlogged=false,west={props['west']}]"
        put(x,y,z,state,'edge-balustrades')

    # Roads meet the reserved bridge decks exactly. A temporary end balustrade
    # prevents a finished street from leading straight into an unbuilt span.
    bridge_gates=[]
    for ident in ('east-radial-local','ring-northeast-local'):
        r=next(r for r in geo['routes'] if r['id']==ident)
        end_x,end_z=r['centerline'][-1];deck=cells[(end_x,end_z)]['block_y']
        zs=sorted(z for x,z in r['corridor'] if x==end_x)
        for z in zs:
            x=end_x+1;h,_=natural(x,z)
            for y in range(min(h,deck-1),deck+1):put(x,y,z,'stone_bricks','temporary-bridge-threshold')
            north='low' if z-1 in zs else 'none';south='low' if z+1 in zs else 'none'
            put(x,deck+1,z,f'stone_brick_wall[east=none,north={north},south={south},up=true,waterlogged=false,west=none]','temporary-bridge-gates')
        bridge_gates.append({'x':end_x+1.5,'y':deck+4,'z':end_z+.5,'deck_y':deck})

    # Lit piers are part of the stone edge, never obstacles in the clear road lane.
    candidates=[p for p in rail if cells[p]['kind']=='full']
    chosen=[]
    landmarks=[(0,-37),(38,-14),(42,30),(0,56),(-42,30),(-38,-14),
               (-36,-61),(27,-61),(-25,-83),(13,-83),(-74,-139),(40,-139),(-74,-98),(40,-98)]
    for target in landmarks:
        options=sorted(candidates,key=lambda p:(p[0]-target[0])**2+(p[1]-target[1])**2)
        if options and math.dist(options[0],target)<12 and all(math.dist(options[0],p)>8 for p in chosen):chosen.append(options[0])
    for point in sorted(candidates,key=lambda p:(p[1],p[0])):
        if all(math.dist(point,p)>19 for p in chosen):chosen.append(point)
    for x,z in chosen:
        y=cells[(x,z)]['block_y']
        put(x,y+1,z,'chiseled_stone_bricks','lamp-piers');put(x,y+2,z,'stone_bricks','lamp-piers')
        put(x,y+3,z,'smooth_stone_slab[type=double,waterlogged=false]','lamp-piers')
        put(x,y+4,z,'lantern[hanging=false,waterlogged=false]','lamps')

    # Preserve any unexpected human edits, including underground blocks. We do
    # not silently rebase onto arbitrary newly observed content.
    blocks=[];mismatches=[]
    for (x,y,z),block in sorted(desired.items()):
        actual=before.state(x,y,z);expected=predicted(x,y,z)
        if actual!=expected:
            mismatches.append({'x':x,'y':y,'z':z,'expected':expected,'actual':actual})
            continue
        if block!=actual:blocks.append({'x':x,'y':y,'z':z,'block':block,'expected':actual,'group':groups[(x,y,z)]})
    if mismatches:raise ValueError(f'Unexpected live edits preserved: {len(mismatches)}, first {mismatches[:5]}')
    # Sample both treads of every stair and every usable full floor column. Rails
    # and lamp piers are excluded; actual after-survey tests their surrounding lanes.
    walk=[]
    for (x,z),c in cells.items():
        if (x,z) in rail or not c['clear']:continue
        if c['kind']=='stairs':
            for sub in (.25,.75):
                sx,sz=(sub,.5) if c['facing'] in ('east','west') else (.5,sub)
                walk.append({'x':x,'z':z,'standing_y':geometry.tread_height(c,sx,sz),'sub_x':sx,'sub_z':sz})
        else:walk.append({'x':x,'z':z,'standing_y':c['block_y']+1})
    metadata={'scope':scope,'geometry_checks':geo['checks'],'changed_blocks':len(blocks),'walk_samples':len(walk),
              'lamps':len(chosen),'rail_columns':len(rail),'by_material':dict(Counter(b['block'] for b in blocks)),
              'temporary_bridge_gates':bridge_gates,
              'source_snapshot_finished_at':before.document['finished_at'],'source_snapshot_atomic':False,
              'note':'Only zones01/02 foundations and local access roads; other districts remain marked reservations.'}
    return {'version':1,'scope':scope,'blocks':blocks},metadata,{'scope':scope,'points':walk},geo


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--design',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    before=survey.load_snapshot(a.snapshot)
    design=json.loads(a.design.read_text());layout=json.loads((ROOT/'examples/layout/shacraft-lobby-layout.json').read_text())
    original=json.loads((ROOT/'.runtime/server/plugins/ShacraftTerrain/maps/layout-before.json').read_text())
    markers=[json.loads((ROOT/name).read_text()) for name in ('.runtime/layout-study/markers-final.json','.runtime/layout-study/access-blocks.json')]
    plan,meta,walk,geo=compile_plan(design,layout,before,original,markers)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(plan,separators=(',',':'))+'\n')
    a.output.with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    a.output.with_suffix('.walk.json').write_text(json.dumps(walk,separators=(',',':'))+'\n')
    a.output.with_suffix('.geometry.json').write_text(json.dumps(geometry.serializable(geo),separators=(',',':'))+'\n')
    print(json.dumps(meta))


if __name__=='__main__':main()
