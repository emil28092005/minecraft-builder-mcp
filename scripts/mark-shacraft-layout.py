#!/usr/bin/env python3
"""Compile the Shacraft spatial study into checked, reversible survey blocks.

This only writes a desired-block document. scripts/layout.py performs live edits.
Ground lines replace one observed surface block; they never level terrain.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLORS = {'01': 'lime', '02': 'yellow', '03': 'purple', '04': 'cyan',
          '05': 'red', '06': 'orange', '07': 'white', '08': 'blue', '09': 'pink'}
RGB = {'lime':'#98d84d','yellow':'#f6d34a','purple':'#9460ce','cyan':'#23b6b6',
       'green':'#527c31','orange':'#f78d27','white':'#f0f0e6','blue':'#4a69d8',
       'pink':'#f394b5','black':'#26282d','light_gray':'#a4aaa6','gray':'#545c61',
       'red':'#e3544b','light_blue':'#68c8ec'}
FONT = {
 '0':['111','101','101','101','111'], '1':['010','110','010','010','111'],
 '2':['111','001','111','100','111'], '3':['111','001','111','001','111'],
 '4':['101','101','111','001','001'], '5':['111','100','111','001','111'],
 '6':['111','100','111','101','111'], '7':['111','001','010','010','010'],
 '8':['111','101','111','101','111'], '9':['111','101','111','001','111'],
 'S':['111','100','111','001','111'],
}


def raster_line(points, radius=.6):
    """Integer columns whose centres meet a piecewise line, with no diagonal holes."""
    result=set()
    for (ax,az),(bx,bz) in zip(points,points[1:]):
        dx,dz=bx-ax,bz-az; length=dx*dx+dz*dz
        for z in range(math.floor(min(az,bz)-radius),math.ceil(max(az,bz)+radius)+1):
            for x in range(math.floor(min(ax,bx)-radius),math.ceil(max(ax,bx)+radius)+1):
                t=max(0,min(1,((x-ax)*dx+(z-az)*dz)/length)) if length else 0
                if (x-ax-t*dx)**2+(z-az-t*dz)**2 <= radius**2:
                    result.add((x,z))
    return result


def offset(points, distance):
    result=[]
    for i,(x,z) in enumerate(points):
        a=points[max(0,i-3)];b=points[min(len(points)-1,i+3)]
        dx,dz=b[0]-a[0],b[1]-a[1];norm=math.hypot(dx,dz) or 1
        result.append((x-dz/norm*distance,z+dx/norm*distance))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,required=True);p.add_argument('--surface',type=Path,required=True)
    p.add_argument('--scope',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();study=json.loads(args.study.read_text());surface=json.loads(args.surface.read_text())
    scope=json.loads(args.scope.read_text())
    if surface['world_uuid']!=scope['world_id'] or surface['world']!=study['world']:
        raise ValueError('Study, world surface and authorization scope disagree')
    W=surface['width'];MINX=surface['min_x'];MINZ=surface['min_z']
    heights=surface['surface_y'];palette=surface['palette'];materials=surface['material_index']
    desired={}; priorities={};skipped=Counter();raised=[]

    def at(x,z):
        if not MINX<=x<=surface['max_x'] or not MINZ<=z<=surface['max_z']:
            return None,None
        i=(z-MINZ)*W+x-MINX
        return heights[i],palette[materials[i]]

    def put(x,z,color,group,priority=10,y=None):
        x,z=round(x),round(z);top,material=at(x,z)
        if top is None:skipped['outside']+=1;return
        if y is None:
            if material=='minecraft:water':skipped['water']+=1;return
            y=max(50,top)
        if y<top:
            # Fixed-height architectural reservations can cross rising land. Raise
            # only the visible survey stroke; never excavate unknown subsurface.
            raised.append({'x':x,'z':z,'requested_y':y,'surface_y':top,'group':group});y=top
        if y<50:raise ValueError('Survey stroke would contact water')
        expected=material if y==top else 'minecraft:air'
        if expected=='minecraft:water':raise ValueError('Refusing to replace water')
        if expected=='minecraft:grass_block':expected+='[snowy=false]'
        block=('minecraft:'+color+'_concrete') if color in RGB else ('minecraft:'+color)
        key=(x,y,z)
        if priority>=priorities.get(key,-1):
            desired[key]={'x':x,'y':y,'z':z,'block':block,'expected':expected,'group':group}
            priorities[key]=priority

    def stroke(points,color,group,radius=.6,priority=10,y=None):
        for x,z in sorted(raster_line(points,radius)):
            put(x,z,color,group,priority,y)

    def text(value,cx,cz,color,group,scale=2):
        width=(len(value)*4-1)*scale
        for j,char in enumerate(value):
            for row,bits in enumerate(FONT[char]):
                for col,bit in enumerate(bits):
                    if bit=='1':
                        for dz in range(scale):
                            for dx in range(scale):
                                put(cx-width//2+j*4*scale+col*scale+dx,cz-5*scale//2+row*scale+dz,
                                    color,group,35)

    # The main route is a corridor reservation, with a clear green interior.
    # Thin edge lines and spaced centre ticks keep the terrain visually dominant.
    for route in study['routes']:
        pts=route['points'];group=route['id'];width=route['width'];deck=route.get('deck_y')
        is_bridge=route['role']=='bridge'
        edgecolor='white' if width>=5 else 'light_gray'
        if is_bridge:edgecolor='white'
        for side in (-1,1):
            stroke(offset(pts,side*(width-1)/2),edgecolor,group,.65,10,deck)
        if width>=7:
            for i in range(0,len(pts),18):
                stroke(pts[i:i+3],'light_gray',group,.55,11,deck)
        if is_bridge:
            # Cross ties define the future deck without filling it or the river.
            for i in range(0,len(pts),12):
                a=offset(pts,-(width-1)/2)[i];b=offset(pts,(width-1)/2)[i]
                stroke([a,b],'red' if group=='arrival-viaduct' else 'light_gray',group,.55,12,deck)
            for end in (0,-1):
                for side in (-1,1):
                    x,z=offset(pts,side*(width-1)/2)[end]
                    for y in range(deck+1,deck+5):put(x,z,'white',group,28,y)
                    put(x,z,'glowstone',group,29,deck+5)

    for feature in study['features']:
        color=COLORS[feature['district']];role=feature['role'];group=feature['id']
        pts=feature['points'];deck=feature.get('deck_y')
        if feature['type']=='polygon' and pts[0]!=pts[-1]:pts=pts+[pts[0]]
        radius=1.05 if role in ('building','pier') or group=='arrival-hex' else .65
        stroke(pts,color,group,radius,20,deck)
        if role=='building':
            # Four sparse survey stakes make footprints recognizable at eye level.
            for point in [pts[i] for i in sorted(set([0,(len(pts)-1)//4,(len(pts)-1)//2,3*(len(pts)-1)//4]))]:
                x,z=point;top,_=at(x,z)
                if top is None:continue
                for y in range(top+1,top+4):put(x,z,color,group,27,y)
                put(x,z,'glowstone',group,28,top+4)

    # Wayfinding IDs appear as blocks as well as external map labels.
    # Small districts use one-block pixels to keep their reservations readable.
    for district in study['districts']:
        ident=district['id'];x,z=district['label'];color=COLORS[ident]
        if ident=='09':continue
        x,z={'01':(-22,27),'07':(26,271),'08':(-136,63)}.get(ident,(x,z))
        text(ident,x,z,'white','label-'+ident,1 if ident=='08' else 2)
    # The brand medallion remains a reserved ring; its S is a simple block glyph.
    text('S',0,8,'lime','spawn-monogram',3)

    # Monumental colored posts stand outside the main entry points, never in a path.
    posts=[('01',33,48),('02',11,-73),('03',-151,-125),('04',197,-97),
           ('05',174,75),('06',-171,226),('07',18,287),('08',-132,43)]
    labels=[]
    for ident,x,z in posts:
        top,material=at(x,z)
        if material=='minecraft:water':raise ValueError('Wayfinding post in water')
        color=COLORS[ident];group='wayfinding-'+ident
        for xx in range(x-1,x+2):
            for zz in range(z-1,z+2):put(xx,zz,color,group,40)
        for y in range(top+1,top+9):put(x,z,color,group,40,y)
        put(x,z,'glowstone',group,41,top+9)
        for xx in (x-1,x+1):put(xx,z,color,group,40,top+7)
        district=next(d for d in study['districts'] if d['id']==ident)
        labels.append({'id':ident,'name':district['name'],'x':x+.5,'y':top+11,'z':z+.5,'color':RGB[color]})

    blocks=sorted(desired.values(),key=lambda b:(b['z']//16,b['x']//16,b['y']//16,b['y'],b['z'],b['x']))
    out={'version':1,'scope':scope,'blocks':blocks}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,separators=(',',':'))+'\n')
    metadata={'source_surface':str(args.surface),'world':surface['world'],'blocks':len(blocks),
              'by_material':dict(Counter(b['block'] for b in blocks)),
              'by_group':dict(Counter(b['group'] for b in blocks)),
              'skipped_strokes':dict(skipped),'raised_fixed_height_strokes':raised,
              'wayfinding_labels':labels,'districts':study['districts'],
              'note':'Surface contours preserve height; bridge outlines reserve a future deck. Walkability requires later paths and stairs.'}
    args.output.with_suffix('.metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({'blocks':len(blocks),'groups':len(metadata['by_group']),
                      'skipped':dict(skipped),'raised_fixed_height_strokes':len(raised)}))


if __name__=='__main__':main()
