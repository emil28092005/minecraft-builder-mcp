#!/usr/bin/env python3
"""Independently audit planned foundation navigation on a half-block surface grid.

This is geometry QA, not a Minecraft collision simulator or a live block survey.
Only clear cells are traversable. Four quarter-center samples describe each full
block or straight bottom stair; adjacent samples require <= 0.5-block height change.
"""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import unittest


def normalize_cells(document):
    result = {}
    for cell in document['cells']:
        if any(type(cell.get(key)) is not int for key in ('x', 'z', 'block_y')):
            raise ValueError('Geometry coordinates and block_y must be integers')
        if type(cell.get('clear')) is not bool or cell.get('kind') not in ('full', 'stairs'):
            raise ValueError('Geometry needs explicit clear and full/stairs kind')
        if cell['kind'] == 'stairs' and cell.get('facing') not in ('north', 'east', 'south', 'west'):
            raise ValueError('Stairs need an explicit cardinal facing')
        at = (cell['x'], cell['z'])
        if at in result:
            raise ValueError(f'Duplicate geometry cell {at}')
        result[at] = cell
    return result


def cell_nodes(x, z):
    return [(2 * x + i, 2 * z + j) for i in (0, 1) for j in (0, 1)]


def height2(cell, sample):
    if cell['kind'] == 'full':
        return 2 * cell['block_y'] + 2
    ix, iz = sample[0] % 2, sample[1] % 2
    facing = cell['facing']
    high = ((facing == 'north' and iz == 0) or (facing == 'south' and iz == 1)
            or (facing == 'west' and ix == 0) or (facing == 'east' and ix == 1))
    return 2 * cell['block_y'] + (2 if high else 1)


def surface_graph(cells):
    return {node: height2(cell, node) for (x, z), cell in cells.items() if cell['clear']
            for node in cell_nodes(x, z)}


def neighbors(node):
    x, z = node
    return ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1))


def reachable(graph, source):
    starts = [p for p in cell_nodes(*source) if p in graph]
    if len(starts) != 4:
        raise ValueError(f'Navigation source {source} is missing or non-clear')
    # One source prevents accidentally joining two disconnected halves of a cell.
    queue, reached = deque(starts[:1]), {starts[0]: 0}
    while queue:
        node = queue.popleft()
        for other in neighbors(node):
            if other in graph and other not in reached and abs(graph[node] - graph[other]) <= 1:
                reached[other] = reached[node] + 1
                queue.append(other)
    return reached


def at_node(node, height=None):
    value = {'x': node[0] / 2 + .25, 'z': node[1] / 2 + .25}
    if height is not None:
        value['standing_y'] = height / 2
    return value


def endpoint_report(name, at, graph, reached):
    nodes = cell_nodes(*at)
    existing = [p for p in nodes if p in graph]
    connected = [p for p in nodes if p in reached]
    return {'name': name, 'x': at[0], 'z': at[1], 'surface_samples': len(existing),
            'reachable_samples': len(connected), 'passed': len(connected) == 4,
            'shortest_surface_route_blocks': min((reached[p] / 2 for p in connected), default=None)}


def route_report(route, cells, graph, reached):
    path = [tuple(p) for p in route.get('centerline_4', route['centerline'])]
    corridor = {tuple(p) for p in route['corridor']}
    clear = {tuple(p) for p in route['clear_cells']}
    width = route['clear_width']
    if type(width) is not int or width < 1 or width % 2 != 1:
        raise ValueError('This cross-section audit requires positive odd clear_width')
    missing_corridor = sorted(corridor - cells.keys())
    nonclear = sorted(p for p in clear if p not in cells or not cells[p]['clear'])
    unreachable = sorted(p for p in clear if any(n not in reached for n in cell_nodes(*p)))
    jumps, invalid_steps = [], []
    max_boundary_step = 0
    for p, q in zip(path, path[1:]):
        dx, dz = q[0] - p[0], q[1] - p[1]
        if abs(dx) + abs(dz) != 1:
            invalid_steps.append({'from': list(p), 'to': list(q)})
            continue
        # Check both parallel quarter-center lanes across the shared block face.
        for a in cell_nodes(*p):
            b = (a[0] + dx, a[1] + dz)
            if (b[0] // 2, b[1] // 2) != q:
                continue
            if a not in graph or b not in graph:
                jumps.append({'from': at_node(a), 'to': at_node(b), 'reason': 'missing_clear_surface'})
                continue
            step = abs(graph[a] - graph[b]) / 2
            max_boundary_step = max(max_boundary_step, step)
            if step > .5:
                jumps.append({'from': at_node(a, graph[a]), 'to': at_node(b, graph[b]),
                              'height_change': step, 'reason': 'height_step_exceeds_half_block'})
    cross_sections, narrow = [], []
    for i, p in enumerate(path):
        # Use at least one corridor-width of tangent support. Inserted cardinal
        # elbows near an axis-clipped endpoint must not rotate the cross-section
        # to measure longitudinally past that deliberate terminal boundary.
        window = max(6, width)
        before, after = path[max(0, i - window)], path[min(len(path) - 1, i + window)]
        tx, tz = after[0] - before[0], after[1] - before[1]
        normal = (0, 1) if abs(tx) > abs(tz) else (1, 0)
        radius = width // 2
        samples = [(p[0] + normal[0] * offset, p[1] + normal[1] * offset)
                   for offset in range(-radius, radius + 1)]
        present = sum(s in cells for s in samples)
        usable = sum(s in cells and cells[s]['clear'] for s in samples)
        connected = sum(all(n in reached for n in cell_nodes(*s)) for s in samples)
        cross_sections.append((present, usable, connected))
        if min(present, usable, connected) < width:
            narrow.append({'x': p[0], 'z': p[1], 'normal': list(normal), 'required_width': width,
                           'structural_columns': present, 'clear_columns': usable,
                           'reachable_columns': connected,
                           'problem_columns': [list(s) for s in samples if s not in cells or not cells[s]['clear']
                                               or any(n not in reached for n in cell_nodes(*s))]})
    ends = [endpoint_report(route['id'] + ':' + name, at, graph, reached)
            for name, at in [('start', path[0]), ('end', path[-1])]]
    passed = not (missing_corridor or nonclear or unreachable or jumps or invalid_steps or narrow)
    return {'id': route['id'], 'passed': passed, 'declared_clear_width': width,
            'corridor_columns': len(corridor), 'missing_corridor_columns': missing_corridor,
            'declared_clear_columns': len(clear), 'nonclear_declared_columns': nonclear,
            'unreachable_declared_columns': unreachable,
            'cross_sections': len(cross_sections),
            'minimum_structural_cross_section': min(row[0] for row in cross_sections),
            'minimum_clear_cross_section': min(row[1] for row in cross_sections),
            'minimum_reachable_cross_section': min(row[2] for row in cross_sections),
            'narrow_cross_sections': narrow, 'centerline_invalid_steps': invalid_steps,
            'centerline_maximum_boundary_step': max_boundary_step,
            'centerline_jumps': jumps, 'endpoints': ends}


def audit(document, source=(0, 9), station=(-6, -105)):
    cells = normalize_cells(document)
    graph = surface_graph(cells)
    reached = reachable(graph, source)
    unreachable = sorted(p for p, cell in cells.items() if cell['clear']
                         and any(n not in reached for n in cell_nodes(*p)))
    routes = [route_report(route, cells, graph, reached) for route in document['routes']]
    goal = endpoint_report('clock-station', station, graph, reached)
    return {'version': 1, 'source': {'x': source[0], 'z': source[1]}, 'world_edits': 0,
            'method': 'Four quarter-center surface samples per clear cell; cardinal half-block BFS, rise/drop <= 0.5 block.',
            'limitations': 'Planned surface topology only. No headroom, body-width collision, material state or live-world verification. Width checks are cardinal cross-sections using the dominant local tangent; full declared masks are also checked.',
            'geometry_sha256': hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'planned_columns': len(cells), 'clear_columns': sum(c['clear'] for c in cells.values()),
            'surface_samples': len(graph), 'reachable_samples': len(reached),
            'unreachable_clear_columns': [list(p) for p in unreachable],
            'unreachable_by_group': dict(Counter(cells[p].get('group', 'unknown') for p in unreachable)),
            'station': goal, 'routes': routes,
            'passed': not unreachable and goal['passed'] and all(r['passed'] for r in routes)}


class GeometryAuditTests(unittest.TestCase):
    def test_full_block_jump_separates_components(self):
        cells = {(x, 0): {'kind': 'full', 'block_y': 10 if x == 0 else 11, 'clear': True}
                 for x in range(2)}
        graph = surface_graph(cells)
        self.assertEqual(len(reachable(graph, (0, 0))), 4)

    def test_stairs_connect_two_levels_for_all_directions(self):
        for facing, direction in [('north', (0, -1)), ('south', (0, 1)), ('west', (-1, 0)), ('east', (1, 0))]:
            with self.subTest(facing=facing):
                dx, dz = direction
                cells = {(-dx, -dz): {'kind': 'full', 'block_y': 9, 'clear': True},
                         (0, 0): {'kind': 'stairs', 'block_y': 10, 'facing': facing, 'clear': True},
                         (dx, dz): {'kind': 'full', 'block_y': 10, 'clear': True}}
                graph = surface_graph(cells)
                self.assertEqual(len(reachable(graph, (-dx, -dz))), 12)

    def test_nonclear_surface_is_never_traversable(self):
        graph = surface_graph({(0, 0): {'kind': 'full', 'block_y': 10, 'clear': False}})
        self.assertFalse(graph)

    def test_missing_width_column_is_reported(self):
        cells = {(x, z): {'x': x, 'z': z, 'kind': 'full', 'block_y': 10, 'clear': True}
                 for x in range(-1, 2) for z in range(3)}
        del cells[(-1, 1)]
        graph = surface_graph(cells)
        route = {'id': 'test', 'centerline': [(0, 0), (0, 1), (0, 2)],
                 'corridor': list(cells), 'clear_cells': list(cells), 'clear_width': 3}
        report = route_report(route, cells, graph, reachable(graph, (0, 0)))
        self.assertFalse(report['passed'])
        self.assertEqual(report['minimum_structural_cross_section'], 2)
        self.assertEqual(report['narrow_cross_sections'][0]['problem_columns'], [[-1, 1]])


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry', type=Path, default=root / '.runtime/foundation-study/design/geometry.json')
    parser.add_argument('--report', type=Path, default=root / '.runtime/foundation-study/design/navigation-qa.json')
    parser.add_argument('--source', type=int, nargs=2, default=(0, 9), metavar=('X', 'Z'))
    parser.add_argument('--station', type=int, nargs=2, default=(-6, -105), metavar=('X', 'Z'))
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(GeometryAuditTests))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    report = audit(json.loads(args.geometry.read_text()), tuple(args.source), tuple(args.station))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'clear_columns': report['clear_columns'],
                      'reachable_samples': report['reachable_samples'], 'surface_samples': report['surface_samples'],
                      'unreachable_clear_columns': len(report['unreachable_clear_columns']),
                      'unreachable_by_group': report['unreachable_by_group'], 'station': report['station'],
                      'routes': [{'id': r['id'], 'passed': r['passed'],
                                  'minimum_clear_width': r['minimum_clear_cross_section'],
                                  'narrow_sections': len(r['narrow_cross_sections']),
                                  'centerline_jumps': len(r['centerline_jumps']),
                                  'unreachable_columns': len(r['unreachable_declared_columns'])} for r in report['routes']],
                      'report': str(args.report.resolve())}, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
