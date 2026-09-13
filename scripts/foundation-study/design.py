#!/usr/bin/env python3
"""Read-only elevation study for the first two Shacraft construction districts.

Writes a reviewable design specification and sections. Does not issue world edits.
Run with .runtime/terrain-study/venv/bin/python scripts/foundation-study/design.py.
Y convention: floor_y is the block coordinate; full-block walking height is Y + 1.
"""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.path import Path as Polygon
from matplotlib.colors import LightSource

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.runtime/foundation-study/design'
OUT.mkdir(parents=True,exist_ok=True)
layout=json.loads((ROOT/'examples/layout/shacraft-lobby-layout.json').read_text())
actual=json.loads((ROOT/'.runtime/server/plugins/ShacraftTerrain/maps/layout-final.json').read_text())
natural=np.floor(np.fromfile(ROOT/'.runtime/terrain-study/natural.f32',dtype='>f4').reshape(768,768)).astype(int)
live_heights=np.asarray(actual['surface_y']).reshape(768,768)
live_materials=np.asarray(actual['material_index']).reshape(768,768)
zz,xx=np.mgrid[-384:384,-384:384]
points=np.column_stack([xx.ravel(),zz.ravel()])

def feature(fid): return next(f for f in layout['features'] if f['id']==fid)
def route(fid): return next(f for f in layout['routes'] if f['id']==fid)
def polygon_mask(vertices):return Polygon(vertices).contains_points(points,radius=.1).reshape(natural.shape)
def metrics(mask,y):
    h=natural[mask]
    deltas,counts=np.unique(live_heights[mask]-h,return_counts=True)
    actual_delta_counts={str(int(k)):int(v) for k,v in zip(deltas,counts)}
    return {'columns':int(mask.sum()),'live_surface_delta_from_natural_counts':actual_delta_counts,'natural_min_y':int(h.min()),'natural_max_y':int(h.max()),'cut_above_floor_blocks':int(np.maximum(h-y,0).sum()),'fill_above_natural_blocks':int(np.maximum(y-h,0).sum()),'maximum_cut':int(max(0,(h-y).max())),'maximum_fill':int(max(0,(y-h).max()))}

surfaces=[]
for fid,y in [('arrival-hex',95),('station-forecourt',95),('clock-station',98)]:
    f=feature(fid); mask=polygon_mask(f['points'])
    surfaces.append({'id':fid,'district':f['district'],'geometry':'polygon','points':f['points'],'floor_y':y,'walk_y':y+1,'support':'Solid to existing ground inside the exact footprint; two-deep structural deck in cut areas. Exterior dark stone masonry, light stone coping, no broad earth platform.','metrics':metrics(mask,y)})

# Each schedule is expressed in the increasing travel coordinate d, irrespective of
# whether the selected world axis increases or decreases along travel. A stair
# replaces the current high-level full block; its back points toward the higher
# previous row. The next row is one full block lower. This guarantees 0.5 steps.
def descent(fid,axis,sign,start,end,y,stairs,final_y,width,waypoints):
    rows=[]; level=y
    for a in range(start*sign,end*sign+1):
        c=a*sign
        is_stair=c in stairs
        facing=('north' if axis=='z' else ('west' if sign==1 else 'east'))
        row={'coordinate':c,'block_y':level,'kind':'stairs' if is_stair else 'full','walk_high_y':level+1,'walk_low_y':level+.5 if is_stair else level+1}
        if is_stair:row['facing']=facing
        rows.append(row)
        if is_stair:level-=1
    assert level==final_y,(fid,level,final_y)
    # Walking from higher to lower: flat->stair upper edge is same elevation;
    # stair upper->lower edge is 0.5, lower->next flat is another 0.5.
    for a,b in zip(rows,rows[1:]):assert abs(a['walk_low_y']-b['walk_high_y'])<=.5
    return {'id':fid,'geometry':'road_profile','axis':axis,'travel_sign':sign,'width':width,'width_note':'Clear paving width, with one additional coping block outside either edge; use the existing marked centerline tangent.','waypoints':waypoints,'start_floor_y':y,'end_floor_y':final_y,'rows':rows,'max_walk_step':.5,'scope':'Only this local part is built in stage 01; preserve all later district markers.'}

roads=[
 {'id':'station-axis','geometry':'road_flat','width':9,'floor_y':95,'walk_y':96,'waypoints':route('station-axis')['waypoints'],'profile_until_z':-77,'intent':'Continuous flat link into the forecourt; ornamental edge strips outside nine clear blocks.'},
 descent('south-axis-local','z',1,57,110,95,[58,61,64,67,70,73,76,79,82,86,90,94,98,101,104,107],79,9,[[0,57],[3,97],[1,110]]),
 descent('portal-radial-local','x',-1,-35,-72,95,[-42,-47,-52,-58,-64,-71],89,7,[[-35,-14],[-67,-43],[-72,-46]]),
 descent('lake-radial-local','x',-1,-42,-90,95,[-44,-47,-50,-55,-64,-72,-78,-83,-85,-87,-89,-90],83,5,[[-42,18],[-77,27],[-90,32]]),
 descent('east-radial-local','x',1,42,82,95,[43,47,51,55,60,66,72,78],87,7,[[42,16],[65,10],[82,8]]),
 descent('ring-northwest-local','x',-1,-40,-80,95,[-42,-45,-49,-53,-57,-61,-65,-69,-73,-77],85,7,[[-40,-65],[-77,-76],[-80,-77]]),
 descent('ring-northeast-local','x',1,40,82,98,[41,44,47,50,54,58,62,66,70,74,78,81],86,7,[[40,-95],[60,-91],[82,-78]])
]
# Endpoint toes use actual captured surface elevations. At the lake the last
# in-bounds column is a stair: a full block here would leave a full-block drop to
# the next native row, and editing that row would exceed the stage's X=-90 bound.
endpoint_toes=[]
for rid,end in [('portal-radial-local',(-72,-46)),('lake-radial-local',(-90,32))]:
    r=next(item for item in roads if item['id']==rid)
    last=r['rows'][-1]
    native=[]
    for z in range(end[1]-1,end[1]+2):
        x=end[0]-1
        native.append({'x':x,'z':z,'natural_block_y':int(natural[z+384,x+384]),'live_surface_y':int(live_heights[z+384,x+384]),'step_from_road':abs(last['walk_low_y']-(int(live_heights[z+384,x+384])+1))})
    assert all(n['step_from_road']<=.5 for n in native),(rid,native)
    r['endpoint_kind']=last['kind']
    r['endpoint_block_y']=last['block_y']
    r['endpoint_walk_low_y']=last['walk_low_y']
    r['native_toe']=native
    endpoint_toes.append({'id':rid,'last_road_column':list(end),'last_road_kind':last['kind'],'last_road_block_y':last['block_y'],'native_front_three':native})
stairs=[
 {'z':-77,'block_y':95,'kind':'full'},
 {'z':-78,'block_y':96,'kind':'stairs','facing':'north'},
 {'z':-79,'block_y':96,'kind':'full'},
 {'z':-80,'block_y':97,'kind':'stairs','facing':'north'},
 {'z':-81,'block_y':97,'kind':'full'},
 {'z':-82,'block_y':98,'kind':'stairs','facing':'north'},
 {'z':-83,'block_y':98,'kind':'full'}]
plan={
 'schema':'shacraft-foundation-elevation-design-v1',
 'status':'DESIGN ONLY; root builder must compare actual voxels before applying and verify final live world.',
 'world':actual['world'],'source_capture_finished_at':actual['capture_finished_at'],
 'y_convention':'floor_y/block_y is the Minecraft block coordinate. A full block at Y95 is walked on at Y96. A bottom stair at Y96 spans feet heights96.5..97.',
 'selected_districts':['01','02'],
 'surfaces':surfaces,'roads':roads,'verified_native_endpoint_toes':endpoint_toes,
 'station_entrance_stair':{'x_min':-16,'x_max':4,'width':21,'travel_direction':'north','rows':stairs,'max_walk_step':.5},
 'station_ne_connection':{'geometry':'polygon','points':[[35,-103],[42,-103],[44,-95],[42,-91],[35,-94],[35,-103]],'floor_y':98,'intent':'Small local upper landing joins east wing to the northeast descending road. Keep inside this polygon; no platform around the whole station.'},
 'plaza_inlay':{'center':[0,9],'outer_radius':16,'floor_y':95,'intent':'Flat green hexagonal ring with cream Shacraft S inlay. Reserve the core for later fountain/arrival feature if desired; never raise the inlay above paving.'},
 'masonry':{'foundation_core':'minecraft:stone','dark_footing':'minecraft:deepslate_bricks','wall':'minecraft:stone_bricks','secondary_wall':'minecraft:andesite','light_coping':'minecraft:smooth_sandstone','paving':'minecraft:smooth_sandstone','paving_bands':'minecraft:smooth_stone','accent':'minecraft:green_concrete','notes':['Do not fill the surrounding rectangle. Shape all exposed plinth walls to the exact existing footprint.','The west station wing has up to16 blocks of foundation. Use vertical pilasters every8 blocks and recessed blind arch panels; one plain flat wall would look excessive.','Leave district02 building floor usable and flat. Footing lines can indicate tower and pavilions; no tall unfinished walls across doors.','Put parapets only on exposed drops, outside the clear walking width; leave all route openings unblocked.','Finish side road ends with a full-width landing; east87/northeast86 match the existing future bridge levels, so keep the boundary to those markers precise.']},
 'quality_checks':['Actual block-for-block scan of finished footprint and road surfaces.','Cardinal-direction walking graph from spawn to station floor and every road endpoint, including stair orientation and at least2 air blocks headroom.','Every descent has half-block treads; never create a full block jump as a path transition.','Foundation columns extend down to solid existing ground; no hidden unsupported floating perimeter.','No new block in a water column; no edit outside foundation/road footprints except explicitly approved local rail, light and footing cells.','Check road width across diagonal curves; evaluate the union of row footprints rather than nearest centerline points alone.','Remove obsolete colored markers and text only inside the stage01 mutation envelope; preserve all other district reservations.','Compare orthographic live surface map with plan and inspect actual west station foundation + north axis from player height.'],
 'endpoint_join_notes':['South road ends at z110/block79 near actual ground78..80; a few local grading cells or one final stair row may be required after live voxel inspection.','Portal endpoint(-72,-46) fullY89 joins native89. Lake endpoint(-90,32) uses terminal east-facing stairY84, joining native83 beyond x-90 across the center3 cells with half-block steps; never replace this terminal stair with a full-block landing.','Northeast road must originate at the station upper landing98, not the forecourt95.','The existing camera is spectator; physical walking correctness still requires geometric collision checks.']
}
(OUT/'foundation-design.json').write_text(json.dumps(plan,indent=2)+'\n')

# Inspectable plan/sections are computed from immutable natural heights.
# Live surface deltas are measured separately in the JSON metrics above.
fig=plt.figure(figsize=(15,11),layout='constrained')
gs=fig.add_gridspec(2,2,width_ratios=[1.22,1],height_ratios=[1,1])
ax=fig.add_subplot(gs[:,0]); extent=(-110,105,125,-165)
h=natural[219:510,274:490]
shade=LightSource(315,40).hillshade(h,vert_exag=2,dx=1,dy=1)
ax.imshow(h,cmap='gist_earth',extent=extent,alpha=.8,vmin=48,vmax=150)
ax.imshow(shade,cmap='gray',extent=extent,alpha=.2)
colors=['#f2dfbd','#ddd2b6','#f0c75b']
for s,c in zip(surfaces,colors):
    pp=np.array(s['points']); ax.fill(pp[:,0],pp[:,1],c,alpha=.8);ax.plot(pp[:,0],pp[:,1],color='#263e39',lw=1.2)
    cc=pp.mean(axis=0);ax.text(cc[0],cc[1],s['id'].replace('-',' ')+'\nblock Y'+str(s['floor_y']),ha='center',va='center',fontsize=9,bbox=dict(facecolor='white',alpha=.8,edgecolor='none'))
for r in roads:
    p=np.array(r['waypoints']);ax.plot(p[:,0],p[:,1],color='#ede3cf',lw=r['width']*.55,solid_capstyle='round');ax.plot(p[:,0],p[:,1],color='#485b53',lw=.6)
    if 'end_floor_y' in r:ax.text(p[-1,0],p[-1,1],'Y'+str(r.get('endpoint_block_y',r['end_floor_y']))+(' stair' if r.get('endpoint_kind')=='stairs' else ''),fontsize=8,ha='center',va='bottom',bbox=dict(facecolor='white',alpha=.85,edgecolor='none'))
ax.set(xlim=(-105,100),ylim=(125,-165),xlabel='X — east →',ylabel='Z — south →',title='Shacraft · stage 01 foundations and local streets')
ax.set_aspect('equal');ax.grid(alpha=.15)
ax2=fig.add_subplot(gs[0,1]);xs=np.arange(-80,47); zs=-120*np.ones_like(xs); ground=natural[zs+384,xs+384]
ax2.fill_between(xs,ground,70,color='#718356',alpha=.65,label='Existing natural ground'); ax2.plot(xs,ground,color='#354d2c',lw=1)
inside=(xs>=-74)&(xs<=40);ax2.plot(xs[inside],np.full(sum(inside),99),color='#ae7731',lw=2,label='Station walking plane Y99');ax2.fill_between(xs[inside],ground[inside],99,color='#c4bda9',alpha=.6,label='Supported station plinth')
ax2.set(xlabel='X across station at Z−120',ylabel='Y elevation',ylim=(78,103),title='Station: one continuous floor; articulated west retaining base');ax2.legend(fontsize=8,loc='lower right');ax2.grid(alpha=.2)
ax3=fig.add_subplot(gs[1,1]);zvals=np.arange(-100,111);xvals=np.where(zvals<0,-6,0);ground=natural[zvals+384,xvals+384];ax3.fill_between(zvals,ground,65,color='#718356',alpha=.65)
walk=np.full(len(zvals),96.);walk[zvals<=-83]=99
for row in stairs:
    k=np.where(zvals==row['z'])[0][0];walk[k]=row['block_y']+(0.75 if row['kind']=='stairs' else 1)
for row in roads[1]['rows']:
    k=np.where(zvals==row['coordinate'])[0][0];walk[k]=(row['walk_low_y']+row['walk_high_y'])/2
ax3.plot(zvals,walk,color='#a47230',lw=2,label='Planned walking surface');ax3.plot(zvals,ground,color='#354d2c',lw=1,label='Natural centerline')
ax3.set(xlabel='Z along north/south arrival route',ylabel='Y elevation',ylim=(74,103),title='Continuous arrival sequence: station → forecourt → square → approach');ax3.grid(alpha=.2);ax3.legend(fontsize=8)
fig.savefig(OUT/'foundation-plan-and-sections.png',dpi=170)
print(json.dumps({'plan':str(OUT/'foundation-design.json'),'figure':str(OUT/'foundation-plan-and-sections.png'),'surfaces':[{k:v for k,v in s.items() if k in ['id','floor_y','metrics']} for s in surfaces]},indent=2))
