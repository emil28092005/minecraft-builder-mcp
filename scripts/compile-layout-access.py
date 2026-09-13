#!/usr/bin/env python3
"""Compile audited access refinements against the original survey plus placed markers."""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mark',ROOT/'scripts/mark-shacraft-layout.py')
mark=importlib.util.module_from_spec(spec);spec.loader.exec_module(mark)

def main():
    p=argparse.ArgumentParser();p.add_argument('--before',type=Path,required=True)
    p.add_argument('--base',type=Path,required=True);p.add_argument('--study',type=Path,required=True)
    p.add_argument('--access',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();before=json.loads(a.before.read_text());base=json.loads(a.base.read_text())
    study=json.loads(a.study.read_text());access=json.loads(a.access.read_text());desired={}
    old={(b['x'],b['y'],b['z']):b['block'] for b in base['blocks']}
    def ground(x,z):
        i=(z-before['min_z'])*before['width']+x-before['min_x']
        return before['surface_y'][i],before['palette'][before['material_index'][i]]
    def put(x,z,block,group,y=None):
        x,z=round(x),round(z);h,material=ground(x,z);y=max(h,51) if y is None else y
        if y<h:raise ValueError('Refusing subsurface edit')
        if material=='minecraft:grass_block':material+='[snowy=false]'
        key=(x,y,z);expected=old.get(key,material if y==h else 'minecraft:air')
        if expected=='minecraft:water':raise ValueError('Refusing water edit')
        if expected==block:return
        desired[key]={'x':x,'y':y,'z':z,'block':block,'expected':expected,'group':group}
    labels=[]
    for route in access['routes']:
        pts=route['points'];color='minecraft:white_concrete'
        for side in (-1,1):
            for x,z in mark.raster_line(mark.offset(pts,side),.6):put(x,z,color,route['id'])
        if route['role']=='stairs':
            for i in range(0,len(pts),6):
                aa=mark.offset(pts,-1)[i];bb=mark.offset(pts,1)[i]
                for x,z in mark.raster_line([aa,bb],.6):put(x,z,'minecraft:blue_concrete',route['id'])
        for label in route.get('labels',[]):
            x,z=label['point'];h,_=ground(x,z)
            labels.append({'x':x+.5,'y':h+5,'z':z+.5,'text':label['text']})
    for route in study['routes']:
        if route['role']!='bridge':continue
        pts=route['points'];deck=route['deck_y']
        for side in (-1,1):
            for end in (0,-1):
                x,z=map(round,mark.offset(pts,side*(route['width']-1)/2)[end]);h,_=ground(x,z)
                for y in range(max(50,h+1),deck+1):put(x,z,'minecraft:white_concrete',route['id']+'-height-stakes',y)
        for abutment in route.get('abutments',[]):
            if abutment['future_stairs']:
                x,z=abutment['point'];h,_=ground(x,z)
                labels.append({'x':x+.5,'y':deck+5,'z':z+.5,
                               'text':f"FUTURE STAIRS / +{deck-h}m\nDECK Y{deck}"})
    # The raised pier reservations meet a future upper terminal level.
    for z in (-158,-132,-106):labels.append({'x':161.5,'y':83,'z':z+.5,'text':'PIER DECK Y79 / FUTURE ACCESS'})
    data={'version':1,'scope':base['scope'],'blocks':sorted(desired.values(),key=lambda b:(b['z'],b['x'],b['y']))}
    a.output.write_text(json.dumps(data,separators=(',',':'))+'\n')
    a.output.with_suffix('.labels.json').write_text(json.dumps(labels,indent=2)+'\n')
    print(json.dumps({'access_blocks':len(desired),'labels':len(labels)}))

if __name__=='__main__':main()
