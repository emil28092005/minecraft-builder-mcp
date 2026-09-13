#!/usr/bin/env python3
"""Rasterize the reviewed Shacraft stage-one design without editing the world.

The public build_geometry(design, layout) function uses only the Python standard
library. Coordinate keys are (x, z). Each cell has block_y, kind, group and clear;
straight bottom stairs additionally have facing. block_y is not player feet Y.

Precedence: exact foundation polygons, northeast landing, local roads, central
station staircase. Existing dense approved centerlines are used for road curves.
Roads extend a few flat rows back into their origin plaza so an avenue cannot
pinch down to the one-block vertex of the hexagonal square.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

Point = tuple[int, int]
Cell = dict[str, Any]


def _on_segment(x: int, z: int, a, b) -> bool:
    cross = (x-a[0])*(b[1]-a[1]) - (z-a[1])*(b[0]-a[0])
    return abs(cross) < 1e-8 and min(a[0],b[0]) <= x <= max(a[0],b[0]) and min(a[1],b[1]) <= z <= max(a[1],b[1])


def polygon_cells(vertices) -> set[Point]:
    """Integer block columns inside OR on the exact polygon, with no box fill."""
    vertices = [tuple(p) for p in vertices]
    if len(vertices) < 3:
        raise ValueError('A foundation polygon needs three vertices')
    segments = list(zip(vertices, vertices[1:]+vertices[:1]))
    result: set[Point] = set()
    for z in range(math.floor(min(p[1] for p in vertices)), math.ceil(max(p[1] for p in vertices))+1):
        for x in range(math.floor(min(p[0] for p in vertices)), math.ceil(max(p[0] for p in vertices))+1):
            inside = False
            boundary = False
            for a,b in segments:
                if _on_segment(x,z,a,b):
                    boundary = True
                    break
                if (a[1] > z) != (b[1] > z):
                    cross_x = a[0] + (z-a[1])*(b[0]-a[0])/(b[1]-a[1])
                    if x < cross_x:
                        inside = not inside
            if boundary or inside:
                result.add((x,z))
    return result


def _distance_squared(x: int, z: int, a, b) -> float:
    dx,dz=b[0]-a[0],b[1]-a[1]
    if not dx and not dz:
        return (x-a[0])**2+(z-a[1])**2
    t=max(0.,min(1.,((x-a[0])*dx+(z-a[1])*dz)/(dx*dx+dz*dz)))
    return (x-a[0]-t*dx)**2+(z-a[1]-t*dz)**2


def _densify(points) -> list[Point]:
    result=[]
    for a,b in zip(points,points[1:]):
        n=max(1,math.ceil(max(abs(a[0]-b[0]),abs(a[1]-b[1]))))
        for i in range(n+1):
            p=(round(a[0]+(b[0]-a[0])*i/n),round(a[1]+(b[1]-a[1])*i/n))
            if not result or result[-1] != p:
                result.append(p)
    if not result and points:
        result=[tuple(map(round,points[0]))]
    return result


def _cardinal_path(points: list[Point]) -> list[Point]:
    """Insert cardinal intermediate samples for collision checks on diagonals."""
    if not points:
        return []
    result=[points[0]]
    for x,z in points[1:]:
        ax,az=result[-1]
        while (ax,az)!=(x,z):
            if ax!=x:
                ax += 1 if x>ax else -1
            else:
                az += 1 if z>az else -1
            result.append((ax,az))
    return result


def _approved_centerline(spec, layout) -> list[Point]:
    base_id=spec['id'].removesuffix('-local')
    approved=next((r for r in layout.get('routes',[]) if r['id']==base_id),None)
    points=_densify(approved['points'] if approved else spec['waypoints'])
    if spec['geometry']=='road_profile':
        axis=0 if spec['axis']=='x' else 1
        lo=min(row['coordinate'] for row in spec['rows'])
        hi=max(row['coordinate'] for row in spec['rows'])
        points=[p for p in points if lo <= p[axis] <= hi]
        # If the approved path terminates just before a reviewed local endpoint,
        # add the small explicit tail without replacing its established curve.
        expected=tuple(spec['waypoints'][-1])
        if points and points[-1][axis] != expected[axis]:
            points += _densify([points[-1],expected])[1:]
    elif 'profile_until_z' in spec:
        stop=spec['profile_until_z']
        points=[p for p in points if p[1]>=stop]
    if len(points)<2:
        raise ValueError(f"No usable centerline for {spec['id']}")
    return points


def _origin_extension(points: list[Point], spec) -> list[Point]:
    """Overlap the origin plateau without changing its level or approved curve."""
    first=points[0]
    distance=max(4,spec['width']//2+2)
    target=points[min(len(points)-1,distance)]
    dx,dz=target[0]-first[0],target[1]-first[1]
    length=math.hypot(dx,dz)
    if not length:
        return points
    back=(round(first[0]-dx*distance/length),round(first[1]-dz*distance/length))
    return _densify([back,first])[:-1]+points


def _corridor(points: list[Point], width: int, axis=None, lo=None, hi=None):
    """Clear corridor plus one block of side coping, evaluated by cell centers."""
    outer=width/2+1
    clear_radius2=(width/2)**2
    outer_radius2=outer**2
    distances: dict[Point,float] = {}
    for a,b in zip(points,points[1:]):
        for z in range(math.floor(min(a[1],b[1])-outer),math.ceil(max(a[1],b[1])+outer)+1):
            for x in range(math.floor(min(a[0],b[0])-outer),math.ceil(max(a[0],b[0])+outer)+1):
                if axis is not None and not lo <= (x,z)[axis] <= hi:
                    continue
                d=_distance_squared(x,z,a,b)
                if d <= outer_radius2+1e-8 and d < distances.get((x,z),math.inf):
                    distances[(x,z)]=d
    return {p:d<=clear_radius2+1e-8 for p,d in distances.items()}


def tread_height(cell: Cell, local_x: float, local_z: float) -> float:
    """Collision surface of a full block or a straight bottom stair at an offset.

    Use .25/.75 offsets to inspect both tread halves, avoiding the central edge.
    """
    if cell['kind']=='full':
        return cell['block_y']+1
    high={'north':local_z<.5,'south':local_z>.5,
          'west':local_x<.5,'east':local_x>.5}[cell['facing']]
    return cell['block_y']+(1. if high else .5)


def build_geometry(design, layout):
    """Return cells, route metadata and compact invariant checks.

    cells[(x,z)] -> {block_y:int,kind:'full'|'stairs',facing?:str,
                    group:str,clear:bool}
    routes[] -> {id,centerline,centerline_4,corridor,clear_cells,clear_width}

    `clear` distinguishes usable road paving from exterior coping; for a main
    polygon every floor cell is clear. It does not mean the world has been cleared.
    """
    cells: dict[Point,Cell] = {}
    routes=[]
    polygon_areas={}
    for surface in design['surfaces']:
        footprint=polygon_cells(surface['points'])
        polygon_areas[surface['id']]=len(footprint)
        for p in footprint:
            cells[p]={'block_y':surface['floor_y'],'kind':'full','group':surface['id'],'clear':True}
    landing=design.get('station_ne_connection')
    if landing:
        for p in polygon_cells(landing['points']):
            cells[p]={'block_y':landing['floor_y'],'kind':'full','group':'station-ne-connection','clear':True}
    for spec in design['roads']:
        centerline=_approved_centerline(spec,layout)
        extended=_origin_extension(centerline,spec)
        profiled=spec['geometry']=='road_profile'
        if profiled:
            axis=0 if spec['axis']=='x' else 1
            profiles={row['coordinate']:row for row in spec['rows']}
            # Extend only the origin; stop exactly at the designed last road row.
            endpoint=centerline[-1][axis]
            origin=extended[0][axis]
            lo,hi=sorted([endpoint,origin])
            corridor=_corridor(extended,spec['width'],axis,lo,hi)
            first=spec['rows'][0]
        else:
            corridor=_corridor(extended,spec['width'])
            # The last flat avenue rows must not cover the station staircase.
            if 'profile_until_z' in spec:
                corridor={p:clear for p,clear in corridor.items() if p[1]>=spec['profile_until_z']}
        for p,clear in corridor.items():
            if profiled:
                row=profiles.get(p[axis])
                if row is None:
                    row={'block_y':first['block_y'],'kind':'full'}
                cell={'block_y':row['block_y'],'kind':row['kind'],'group':spec['id'],'clear':clear}
                if row['kind']=='stairs':
                    cell['facing']=row['facing']
            else:
                cell={'block_y':spec['floor_y'],'kind':'full','group':spec['id'],'clear':clear}
            # A coping line within an already level clear plaza is a floor band,
            # not an obstacle or a place for a parapet. Preserve that distinction.
            previous=cells.get(p)
            if previous and previous['clear'] and previous['block_y']==cell['block_y'] and previous['kind']==cell['kind']=='full':
                cell['clear']=True
            cells[p]=cell
        routes.append({'id':spec['id'],'centerline':centerline,'centerline_4':_cardinal_path(centerline),'corridor':sorted(corridor),'clear_cells':sorted(p for p,c in corridor.items() if c),'clear_width':spec['width']})
    stair=design['station_entrance_stair']
    stair_cells=[]
    stair_clear=[]
    for row in stair['rows']:
        for x in range(stair['x_min']-1,stair['x_max']+2):
            p=(x,row['z'])
            clear=stair['x_min']<=x<=stair['x_max']
            cells[p]={'block_y':row['block_y'],'kind':row['kind'],'group':'station-entrance-stair','clear':clear}
            if row['kind']=='stairs':
                cells[p]['facing']=row['facing']
            stair_cells.append(p)
            if clear:
                stair_clear.append(p)
    mid=(stair['x_min']+stair['x_max'])//2
    line=[(mid,row['z']) for row in stair['rows']]
    routes.append({'id':'station-entrance-stair','centerline':line,'centerline_4':_cardinal_path(line),'corridor':stair_cells,'clear_cells':stair_clear,'clear_width':stair['width']})
    missing=[]
    blocked=[]
    for route in routes:
        for p in route['centerline_4']:
            if p not in cells:
                missing.append((route['id'],p))
            elif not cells[p]['clear']:
                blocked.append((route['id'],p))
    if missing or blocked:
        raise ValueError(f'Road centerline incomplete: missing={missing[:8]}, non-clear={blocked[:8]}')
    max_step=0.
    for route in routes:
        path=route['centerline_4']
        route_step=0.
        for p,q in zip(path,path[1:]):
            dx,dz=q[0]-p[0],q[1]-p[1]
            departure=tread_height(cells[p],.5+dx*.25,.5+dz*.25)
            arrival=tread_height(cells[q],.5-dx*.25,.5-dz*.25)
            step=abs(departure-arrival)
            if step>.5:
                raise ValueError(f"Unwalkable centerline in {route['id']}: {p}->{q}, {step} blocks")
            route_step=max(route_step,step)
        route['maximum_centerline_step']=route_step
        max_step=max(max_step,route_step)
    counts={}
    for cell in cells.values():
        counts[cell['group']]=counts.get(cell['group'],0)+1
    return {'cells':cells,'routes':routes,'checks':{'columns':len(cells),'polygon_areas':polygon_areas,'columns_by_final_group':counts,'centerline_missing':len(missing),'centerline_nonclear':len(blocked),'maximum_centerline_step':max_step,'stairs':sum(c['kind']=='stairs' for c in cells.values()),'minimum_block_y':min(c['block_y'] for c in cells.values()),'maximum_block_y':max(c['block_y'] for c in cells.values()),'world_edits':0}}


def serializable(geometry):
    return {**geometry,'cells':[{'x':x,'z':z,**cell} for (x,z),cell in sorted(geometry['cells'].items(),key=lambda p:(p[0][1],p[0][0]))]}


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design',type=Path,default=root/'.runtime/foundation-study/design/foundation-design.json')
    parser.add_argument('--layout',type=Path,default=root/'examples/layout/shacraft-lobby-layout.json')
    parser.add_argument('--output',type=Path,default=root/'.runtime/foundation-study/design/geometry.json')
    args=parser.parse_args()
    geometry=build_geometry(json.loads(args.design.read_text()),json.loads(args.layout.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(serializable(geometry),separators=(',',':'))+'\n')
    print(json.dumps({'output':str(args.output),'checks':geometry['checks']},indent=2))


if __name__=='__main__':
    main()
