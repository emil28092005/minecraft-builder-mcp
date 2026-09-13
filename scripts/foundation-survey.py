#!/usr/bin/env python3
"""Read-only, scoped block surveys for checked foundations and half-block path clearance.

Snapshots contain actual complete block states, never inferred terrain or implicit air.
Reads are sequential and non-atomic: keep edits idle during a survey. Cached reads may
only be reused explicitly with --resume; the original observation times are retained.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import tempfile

_spec = importlib.util.spec_from_file_location('foundation_terrain', Path(__file__).with_name('terrain.py'))
terrain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(terrain)
SCOPE_KEYS = ('project_id', 'world_id', 'world_epoch')
AXES = ('x', 'y', 'z')
STATE = re.compile(r'minecraft:[a-z0-9_]+(?:\[[a-z0-9_=,]+\])?\Z')
MAX_VOXELS = 4_000_000
AIR = {'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'}
# Conservative shape set. Unknown blocks never count as air or safe support.
FULL = set(('stone cobblestone mossy_cobblestone stone_bricks mossy_stone_bricks '
            'cracked_stone_bricks chiseled_stone_bricks smooth_stone granite polished_granite '
            'diorite polished_diorite andesite polished_andesite deepslate cobbled_deepslate '
            'polished_deepslate deepslate_bricks deepslate_tiles bricks quartz_block quartz_pillar '
            'smooth_quartz sandstone cut_sandstone smooth_sandstone red_sandstone terracotta '
            'glass tinted_glass obsidian dirt grass_block bedrock oak_planks spruce_planks '
            'birch_planks dark_oak_planks oak_log spruce_log birch_log dark_oak_log '
            'stripped_oak_log stripped_spruce_log moss_block glowstone gold_block '
            'waxed_oxidized_cut_copper barrier').split())
SLABS = {'stone_brick_slab', 'cobblestone_slab', 'oak_slab', 'spruce_slab', 'smooth_stone_slab'}
COLORS = ('white orange magenta light_blue yellow lime pink gray light_gray cyan purple blue brown green red black').split()
FULL.update(color + suffix for color in COLORS for suffix in ('_concrete', '_terracotta', '_stained_glass'))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def point(value):
    if not isinstance(value, dict) or any(type(value.get(a)) is not int for a in AXES):
        raise ValueError('Coordinates must contain integer x, y, z')
    if any(not -(2 ** 31) <= value[a] < 2 ** 31 for a in AXES):
        raise ValueError('Coordinates must fit signed 32-bit integers')
    return {a: value[a] for a in AXES}


def scope_of(context):
    scope = {k: context.get(k) for k in SCOPE_KEYS}
    if any(not isinstance(v, str) or not v for v in scope.values()):
        raise ValueError('Project context must identify project, world and epoch')
    return scope


def volume(box):
    return math.prod(box['max'][a] - box['min'][a] + 1 for a in AXES)


def box_of(lo, hi):
    box = {'min': point(lo), 'max': point(hi)}
    if any(box['min'][a] > box['max'][a] for a in AXES):
        raise ValueError('Minimum exceeds maximum')
    return box


def cell_key(box):
    return tuple(box['min'][a] // 16 for a in AXES)


def box_cells(lo, hi):
    box = box_of(lo, hi)
    if volume(box) > MAX_VOXELS:
        raise ValueError(f'Survey exceeds {MAX_VOXELS:,} voxels; split it explicitly')
    cells = []
    for cx in range(lo['x'] // 16, hi['x'] // 16 + 1):
        for cy in range(lo['y'] // 16, hi['y'] // 16 + 1):
            for cz in range(lo['z'] // 16, hi['z'] // 16 + 1):
                origin = dict(zip(AXES, (cx * 16, cy * 16, cz * 16)))
                cells.append({'min': {a: max(lo[a], origin[a]) for a in AXES},
                              'max': {a: min(hi[a], origin[a] + 15) for a in AXES}})
    return cells


def column_cells(document):
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('columns'), list):
        raise ValueError('Column plan requires version: 1 and columns: [{x,z,min_y,max_y}]')
    if not 1 <= len(document['columns']) <= MAX_VOXELS:
        raise ValueError('Column plan is empty or too large')
    merged = {}
    for column in document['columns']:
        if not isinstance(column, dict) or any(type(column.get(k)) is not int for k in ('x', 'z', 'min_y', 'max_y')):
            raise ValueError('Every column requires integer x, z, min_y and max_y')
        lo = point({'x': column['x'], 'z': column['z'], 'y': column['min_y']})
        hi = point({**lo, 'y': column['max_y']})
        for box in box_cells(lo, hi):
            key = cell_key(box)
            old = merged.get(key)
            merged[key] = box if old is None else {
                'min': {a: min(old['min'][a], box['min'][a]) for a in AXES},
                'max': {a: max(old['max'][a], box['max'][a]) for a in AXES}}
    cells = [merged[key] for key in sorted(merged)]
    if sum(volume(b) for b in cells) > MAX_VOXELS:
        raise ValueError('Expanded column survey exceeds voxel limit')
    return cells


def assert_in_scope(cells, context):
    region = context.get('region', {})
    area = box_of(region.get('min'), region.get('max'))
    for cell in cells:
        if any(cell['min'][a] < area['min'][a] or cell['max'][a] > area['max'][a] for a in AXES):
            raise ValueError('Requested survey exceeds the selected project area')


def index_at(box, x, y, z):
    lo, hi = box['min'], box['max']
    if not (lo['x'] <= x <= hi['x'] and lo['y'] <= y <= hi['y'] and lo['z'] <= z <= hi['z']):
        raise KeyError(f'No observed block at {(x, y, z)}; air is never inferred')
    return ((y - lo['y']) * (hi['z'] - lo['z'] + 1) + z - lo['z']) * (hi['x'] - lo['x'] + 1) + x - lo['x']


def capture_cell(backend, box, epoch):
    started = utc_now()
    result = backend.call('region_inspect', **box, detail='blocks')
    if result.get('world_epoch') != epoch or result.get('truncated') is not False:
        raise RuntimeError('Inspection was truncated or returned another world epoch')
    palette, lookup = [], {}
    indices = [None] * volume(box)
    for item in result.get('blocks', []):
        pos = point(item.get('pos'))
        index = index_at(box, **pos)
        if indices[index] is not None:
            raise RuntimeError('Inspection returned a duplicate position')
        state = item.get('state')
        if not isinstance(state, str) or not STATE.fullmatch(state):
            raise RuntimeError('Inspection returned an invalid block state')
        if state not in lookup:
            lookup[state] = len(palette)
            palette.append(state)
        indices[index] = lookup[state]
    if any(i is None for i in indices):
        raise RuntimeError('Inspection omitted blocks; missing blocks are not air')
    return {**box, 'palette': palette, 'indices': indices,
            'observed_from': started, 'observed_until': utc_now()}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def save_gzip(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=path.name + '.', suffix='.tmp', dir=path.parent, delete=False) as raw:
            temporary = Path(raw.name)
            with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as zipped:
                zipped.write(json.dumps(document, separators=(',', ':')).encode())
            raw.flush()
            os.fsync(raw.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class Snapshot:
    def __init__(self, document, expected_scope=None):
        if not isinstance(document, dict) or document.get('version') != 1 or document.get('complete') is not True:
            raise ValueError('Only complete version-1 snapshots may be used')
        self.scope = scope_of(document.get('scope', {}))
        if expected_scope is not None and self.scope != expected_scope:
            raise ValueError('Snapshot belongs to another project/world/epoch')
        self.document, self.cells = document, {}
        requested = document.get('requested_cells')
        captured = document.get('cells')
        if not isinstance(requested, list) or not requested or not isinstance(captured, list) or len(requested) != len(captured):
            raise ValueError('Snapshot does not cover every requested cell')
        if sum(volume(box_of(b.get('min'), b.get('max'))) for b in requested) > MAX_VOXELS:
            raise ValueError('Snapshot exceeds maximum voxel count')
        for expected, cell in zip(requested, captured):
            box = box_of(cell.get('min'), cell.get('max'))
            if box != expected or cell_key(box) != tuple(box['max'][a] // 16 for a in AXES):
                raise ValueError('Snapshot cell differs from request or crosses a 16³ cell')
            key = cell_key(box)
            if key in self.cells:
                raise ValueError('Snapshot contains duplicate cells')
            palette, indices = cell.get('palette'), cell.get('indices')
            if not isinstance(palette, list) or not palette or any(not isinstance(s, str) or not STATE.fullmatch(s) for s in palette):
                raise ValueError('Snapshot palette contains invalid states')
            if not isinstance(indices, list) or len(indices) != volume(box) or any(type(i) is not int or not 0 <= i < len(palette) for i in indices):
                raise ValueError('Snapshot has missing or invalid block indices')
            self.cells[key] = cell

    def state(self, x, y, z):
        point({'x': x, 'y': y, 'z': z})
        cell = self.cells.get((x // 16, y // 16, z // 16))
        if cell is None:
            raise KeyError(f'No observed block at {(x, y, z)}; air is never inferred')
        return cell['palette'][cell['indices'][index_at(cell, x, y, z)]]

    def states_for(self, blocks):
        return {tuple(b[a] for a in AXES): self.state(**point(b)) for b in blocks}


def load_snapshot(path, expected_scope=None):
    with gzip.open(path, 'rt') as handle:
        return Snapshot(json.load(handle), expected_scope)


def scan(backend, cells, path, resume=False, progress=lambda value: None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    context = backend.call('project_context')
    scope = scope_of(context)
    assert_in_scope(cells, context)
    cache = path.with_name(path.name + '.parts')
    with path.with_name(path.name + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            raise ValueError('Complete snapshot already exists; choose a fresh path for a fresh survey')
        if cache.exists() and not resume:
            raise ValueError('Survey cache already exists; --resume explicitly reuses older observations')
        cache.mkdir(exist_ok=True)
        identity = {'version': 1, 'scope': scope, 'requested_cells': cells}
        header = cache / 'manifest.json'
        if header.exists():
            saved = json.loads(header.read_text())
            if saved.get('identity') != identity or saved.get('digest') != digest(identity):
                raise ValueError('Survey cache scope or requested cells differ')
        else:
            saved = {'identity': identity, 'digest': digest(identity), 'started_at': utc_now()}
            terrain.save(header, saved)
        captured = []
        for number, box in enumerate(cells):
            part = cache / f'{number:06d}.json.gz'
            if part.exists():
                with gzip.open(part, 'rt') as handle:
                    cell = json.load(handle)
                # Reject incomplete, reordered, or damaged cached observations before reuse.
                Snapshot({'version': 1, 'complete': True, 'scope': scope,
                          'requested_cells': [box], 'cells': [cell]}, scope)
            else:
                cell = capture_cell(backend, box, scope['world_epoch'])
                save_gzip(part, cell)
            captured.append(cell)
            progress({'cells': number + 1, 'total_cells': len(cells)})
        final_context = backend.call('project_context')
        if scope_of(final_context) != scope or final_context.get('region') != context.get('region'):
            raise RuntimeError('Project scope changed during capture; no complete snapshot written')
        document = {**identity, 'complete': True, 'atomic_snapshot': False,
                    'started_at': saved['started_at'], 'finished_at': utc_now(),
                    'resumed_cache': resume, 'cells': captured,
                    'note': 'Sequential observations. Exact states must be checked again atomically when editing.'}
        result = Snapshot(document, scope)
        save_gzip(path, document)
        return result


def vertical_shape(state, sub_x=.5, sub_z=.5):
    """Occupied Y intervals at a surface sample, or None for unknown geometry.

    A straight stair has two levels. Samples on the riser boundary are ambiguous
    and rejected, including the default center, rather than choosing one level.
    """
    if state in AIR:
        return []
    base, _, properties = state.removeprefix('minecraft:').partition('[')
    props = dict(piece.split('=', 1) for piece in properties.rstrip(']').split(',') if '=' in piece)
    if base in FULL:
        return [(0.0, 1.0)]
    if base in SLABS and props.get('waterlogged', 'false') == 'false':
        return {'bottom': [(0.0, .5)], 'top': [(.5, 1.0)], 'double': [(0.0, 1.0)]}.get(props.get('type'))
    if (base.endswith('_stairs') and props.get('shape') == 'straight'
            and props.get('half') == 'bottom' and props.get('waterlogged', 'false') == 'false'):
        facing = props.get('facing')
        if facing not in ('north', 'south', 'east', 'west'):
            return None
        offset = sub_z if facing in ('north', 'south') else sub_x
        if abs(offset - .5) <= 1e-7:
            return None
        high = offset < .5 if facing in ('north', 'west') else offset > .5
        return [(0.0, 1.0 if high else .5)]
    return None


def verify_walkable(snapshot, points):
    """Check observed surface samples and their 1.8-block vertical clearance.

    `standing_y` is the feet height, not the supporting block Y. Full blocks and
    horizontal slabs support a centered player's full footprint. Explicit sub_x
    and sub_z fractions additionally sample straight bottom stairs on each side
    of their riser. These are point samples, not a full moving-player collision
    simulation. Optional ordered `route` points check physical cardinal steps of
    at most one block and rises/drops of at most half a block.
    """
    failures, routes = [], defaultdict(list)
    for number, p in enumerate(points):
        if not isinstance(p, dict) or type(p.get('x')) is not int or type(p.get('z')) is not int:
            raise ValueError('Walk points require integer x and z')
        feet = p.get('standing_y')
        if type(feet) not in (int, float) or not math.isfinite(feet) or feet * 2 != round(feet * 2):
            raise ValueError('standing_y must be a finite half-block height')
        x, z = p['x'], p['z']
        sub_x, sub_z = p.get('sub_x', .5), p.get('sub_z', .5)
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1
               for value in (sub_x, sub_z)):
            raise ValueError('sub_x and sub_z must be finite fractions strictly between 0 and 1')
        support_y = math.ceil(feet) - 1
        reason = None
        try:
            support = vertical_shape(snapshot.state(x, support_y, z), sub_x, sub_z)
            if support is None:
                reason = 'unknown_support_shape'
            elif not any(abs(support_y + top - feet) < 1e-8 for _, top in support):
                reason = 'missing_support_at_feet'
            if reason is None:
                for y in range(math.floor(feet), math.ceil(feet + 1.8)):
                    occupied = vertical_shape(snapshot.state(x, y, z), sub_x, sub_z)
                    if occupied is None:
                        reason = 'unknown_clearance_shape'
                        break
                    if any(y + bottom < feet + 1.8 and y + top > feet for bottom, top in occupied):
                        reason = 'blocked_headroom'
                        break
        except KeyError:
            reason = 'unobserved_block'
        if reason:
            failures.append({'index': number, 'x': x, 'z': z, 'sub_x': sub_x, 'sub_z': sub_z,
                             'standing_y': feet, 'reason': reason})
        if 'route' in p:
            route = p['route']
            if not isinstance(route, str) or not route:
                raise ValueError('route must be a nonempty string')
            routes[route].append((number, x + sub_x, z + sub_z, feet))
    edges = 0
    for route, row in routes.items():
        for previous, current in zip(row, row[1:]):
            edges += 1
            dx, dz = abs(previous[1] - current[1]), abs(previous[2] - current[2])
            if (dx > 1e-7 and dz > 1e-7) or not 1e-7 < dx + dz <= 1 + 1e-7:
                failures.append({'index': current[0], 'route': route, 'reason': 'non_cardinal_route_step'})
            elif abs(previous[3] - current[3]) > .5:
                failures.append({'index': current[0], 'route': route, 'reason': 'route_step_exceeds_half_block'})
    return {'checked_points': len(points), 'checked_route_edges': edges, 'failures': failures,
            'passed': not failures, 'scope': snapshot.scope,
            'note': 'Observed surface samples and vertical headroom; full cubes, slabs and explicit straight bottom-stair samples. Stair samples are a surface profile, not a full player-width collision simulation. Cached snapshot is not a live re-read.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    capture = commands.add_parser('scan', help='Read actual blocks; never edits or loads chunks')
    capture.add_argument('--min', type=int, nargs=3, metavar=('X', 'Y', 'Z'))
    capture.add_argument('--max', type=int, nargs=3, metavar=('X', 'Y', 'Z'))
    capture.add_argument('--columns', type=Path)
    capture.add_argument('--out', type=Path, required=True)
    capture.add_argument('--resume', action='store_true', help='Explicitly reuse older partial observations')
    capture.add_argument('--config', type=Path, default=terrain.ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml')
    verify = commands.add_parser('verify-walk', help='Check surfaces against an observed snapshot')
    verify.add_argument('--snapshot', type=Path, required=True)
    verify.add_argument('--points', type=Path, required=True, help='JSON {scope:{...},points:[{x,z,standing_y,sub_x?,sub_z?,route?}]}')
    verify.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'scan':
        if args.columns:
            if args.min or args.max:
                parser.error('Use --columns or --min/--max, not both')
            cells = column_cells(json.loads(args.columns.read_text()))
        else:
            if not args.min or not args.max:
                parser.error('--min and --max are required without --columns')
            cells = box_cells(dict(zip(AXES, args.min)), dict(zip(AXES, args.max)))
        result = scan(terrain.Backend(args.config), cells, args.out, args.resume,
                      progress=lambda p: print(json.dumps(p), flush=True) if p['cells'] % 16 == 0 or p['cells'] == p['total_cells'] else None)
        print(json.dumps({'status': 'captured', 'scope': result.scope, 'cells': len(cells),
                          'voxels': sum(volume(c) for c in cells), 'path': str(args.out.resolve())}))
    else:
        document = json.loads(args.points.read_text())
        result = verify_walkable(load_snapshot(args.snapshot, scope_of(document.get('scope', {}))), document['points'])
        args.report.parent.mkdir(parents=True, exist_ok=True)
        terrain.save(args.report, result)
        print(json.dumps({'passed': result['passed'], 'checked_points': result['checked_points'],
                          'failures': len(result['failures']), 'report': str(args.report.resolve())}))
        if not result['passed']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
