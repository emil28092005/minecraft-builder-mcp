#!/usr/bin/env python3
"""Verify a foundation edit against actual before/after Paper surface maps.

Air cuts expose saved lower voxel states; an omitted voxel never becomes assumed
air. The whole map is compared, including columns outside the edit. Optional PNG
output is a fresh material/height render of the observed after map, not a mockup.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('foundation_snapshot', ROOT / 'scripts/foundation-survey.py')
survey = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(survey)
AIR = {'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'}
WATER = {'minecraft:water', 'minecraft:bubble_column'}
MAP_SCOPE = ('world_uuid', 'world_key', 'min_x', 'max_x', 'min_z', 'max_z', 'width', 'length')


def material(state):
    return state.split('[', 1)[0]


def ignored_materials(document):
    """Air stays implicit; absent metadata preserves legacy map semantics."""
    raw = document.get('ignored_materials', [])
    if (not isinstance(raw, list) or any(not isinstance(value, str) for value in raw)
            or len(raw) != len(set(raw))
            or not set(raw) <= AIR | {'minecraft:barrier'}):
        raise ValueError('Unsupported explicit ignored_materials map policy')
    return AIR | set(raw)


def validate_map(document):
    if document.get('format') != 'minecraft-builder-surface-map-v1' or document.get('source') != 'paper_world_surface':
        raise ValueError('Expected a captured Paper world surface map')
    for key in ('min_x', 'max_x', 'min_z', 'max_z', 'width', 'length'):
        if type(document.get(key)) is not int:
            raise ValueError('Map bounds must be integers')
    count = document['width'] * document['length']
    if (not 0 < count <= 4_194_304 or document['width'] != document['max_x'] - document['min_x'] + 1
            or document['length'] != document['max_z'] - document['min_z'] + 1):
        raise ValueError('Map bounds and dimensions disagree')
    palette = document.get('palette')
    if not isinstance(palette, list) or not palette or any(not isinstance(m, str) or not survey.STATE.fullmatch(m) or '[' in m for m in palette):
        raise ValueError('Map palette must contain material names')
    heights, indices = document.get('surface_y'), document.get('material_index')
    if not isinstance(heights, list) or len(heights) != count or any(type(y) is not int for y in heights):
        raise ValueError('Map has missing or invalid surface heights')
    if not isinstance(indices, list) or len(indices) != count or any(type(i) is not int or not 0 <= i < len(palette) for i in indices):
        raise ValueError('Map has missing or invalid material indices')
    ignored = ignored_materials(document)
    if any(palette[index] in ignored - AIR for index in indices):
        raise ValueError('Map surface contains a material its explicit policy ignores')
    return [palette[index] for index in indices]


def column_index(document, x, z):
    if not (document['min_x'] <= x <= document['max_x'] and document['min_z'] <= z <= document['max_z']):
        raise ValueError(f'Edited column {(x, z)} is outside the surface map')
    return (z - document['min_z']) * document['width'] + x - document['min_x']


def expected_surface(before, snapshot, layout):
    original_materials = validate_map(before)
    ignored = ignored_materials(before)
    scope = survey.scope_of(layout.get('scope', {}))
    if snapshot.scope != scope or scope['world_id'] != before['world_uuid']:
        raise ValueError('Voxel snapshot, layout and map scopes differ')
    overlays = defaultdict(dict)
    actual_changes = Counter()
    water_replacements = []
    expected_states_checked = 0
    blocks = layout.get('blocks')
    if layout.get('version') != 1 or not isinstance(blocks, list) or not blocks:
        raise ValueError('Layout requires version 1 and explicit blocks')
    for block in blocks:
        pos = survey.point(block)
        x, y, z = pos['x'], pos['y'], pos['z']
        column_index(before, x, z)
        if y in overlays[(x, z)]:
            raise ValueError(f'Duplicate desired block {(x, y, z)}')
        desired, expected = block.get('block'), block.get('expected')
        if any(not isinstance(s, str) or not survey.STATE.fullmatch(s) for s in (desired, expected)):
            raise ValueError('Layout requires valid desired and expected block states')
        observed = snapshot.state(x, y, z)
        if observed != expected:
            raise ValueError(f'Layout expected state disagrees with baseline voxel snapshot at {(x, y, z)}')
        expected_states_checked += 1
        overlays[(x, z)][y] = desired
        if desired != observed:
            actual_changes['removed' if material(desired) in AIR else 'placed_or_replaced'] += 1
            if material(observed) in WATER and desired != observed:
                water_replacements.append({'x': x, 'y': y, 'z': z, 'before': observed, 'desired': desired})
    heights = before['surface_y'].copy()
    materials = original_materials.copy()
    exposed_snapshot_blocks = 0
    map_only_covered_tops = 0
    for (x, z), overlay in overlays.items():
        i = column_index(before, x, z)
        original_top = before['surface_y'][i]
        # A map and a block capture taken at different times must still agree
        # where reconstruction relies on their shared original surface.
        visible_overlay_top = max((y for y, state in overlay.items() if material(state) not in ignored),
                                  default=original_top)
        try:
            observed_original_top = material(snapshot.state(x, original_top, z))
        except KeyError:
            # An overhead addition can be surveyed independently of the ground
            # it covers. Its checked desired voxel proves the new surface lies
            # above the earlier captured top; no lower voxel is reconstructed.
            # Cuts and invisible-only additions still require that observation.
            if visible_overlay_top <= original_top:
                raise
            observed_original_top = original_materials[i]
            map_only_covered_tops += 1
        empty_fallback = original_materials[i] in AIR
        if (observed_original_top != original_materials[i]
                and not (empty_fallback and observed_original_top in ignored)):
            raise ValueError(f'Before map and voxel snapshot disagree at original surface {(x, original_top, z)}')
        top = max(original_top, visible_overlay_top)
        while True:
            if top in overlay:
                state = overlay[top]
            elif top == original_top:
                state = original_materials[i]
            elif top > original_top:
                # The captured surface proves higher untouched cells are
                # ignored by this explicit visibility policy. They may be
                # invisible barriers; this is no claim of collision-free air.
                state = 'minecraft:air'
            else:
                state = snapshot.state(x, top, z)
                exposed_snapshot_blocks += 1
            if material(state) not in ignored:
                heights[i], materials[i] = top, material(state)
                break
            if empty_fallback and top == original_top:
                # A captured all-transparent column reports air at world min Y.
                # Do not read below that explicit fallback or invent terrain.
                heights[i], materials[i] = top, original_materials[i]
                break
            top -= 1
    return heights, materials, overlays, {
        'expected_states_checked_against_baseline': expected_states_checked,
        'placed_or_replaced_voxels': actual_changes['placed_or_replaced'], 'removed_voxels': actual_changes['removed'],
        'lower_snapshot_voxels_consulted_after_cuts': exposed_snapshot_blocks,
        'covered_original_tops_known_only_from_before_map': map_only_covered_tops,
        'observed_water_voxels_replaced': water_replacements}


def verify(before, after, snapshot, layout):
    after_materials = validate_map(after)
    if ignored_materials(before) != ignored_materials(after):
        raise ValueError('Before and after map ignored_materials policies differ; capture a matching baseline')
    for key in MAP_SCOPE:
        if before.get(key) != after.get(key):
            raise ValueError(f'Before and after map scopes differ: {key}')
    expected_y, expected_m, overlays, stats = expected_surface(before, snapshot, layout)
    original_materials = [before['palette'][i] for i in before['material_index']]
    affected = {column_index(before, x, z) for x, z in overlays}
    mismatches, outside_mismatches = [], 0
    changed_surface = 0
    water_columns = 0
    water_surface_changes = []
    for i, observed in enumerate(after_materials):
        x, z = i % before['width'] + before['min_x'], i // before['width'] + before['min_z']
        if before['surface_y'][i] != after['surface_y'][i] or original_materials[i] != observed:
            changed_surface += 1
        if expected_y[i] != after['surface_y'][i] or expected_m[i] != observed:
            mismatch = {'x': x, 'z': z, 'expected_y': expected_y[i], 'actual_y': after['surface_y'][i],
                        'expected_material': expected_m[i], 'actual_material': observed, 'inside_edit_columns': i in affected}
            mismatches.append(mismatch)
            if i not in affected:
                outside_mismatches += 1
        if original_materials[i] in WATER:
            water_columns += 1
            if observed != original_materials[i] or before['surface_y'][i] != after['surface_y'][i]:
                water_surface_changes.append({'x': x, 'z': z, 'before_y': before['surface_y'][i],
                                              'after_y': after['surface_y'][i], 'after_material': observed})
    water_ok = not water_surface_changes and not stats['observed_water_voxels_replaced']
    return {'version': 1, 'world': before['world'], 'scope': snapshot.scope,
            'source': 'Full live Paper surface maps plus observed baseline voxels and desired edit overlay',
            'surface_ignored_materials': sorted(ignored_materials(after)),
            'verified_surface_columns': len(expected_y), 'affected_columns': len(affected),
            'outside_edit_columns_verified': len(expected_y) - len(affected),
            'changed_surface_columns': changed_surface, 'surface_mismatches': len(mismatches),
            'outside_edit_surface_mismatches': outside_mismatches,
            'mismatch_examples': mismatches[:40],
            'original_visible_water_columns': water_columns,
            'visible_water_surface_changes': len(water_surface_changes),
            'water_surface_change_examples': water_surface_changes[:20],
            **stats, 'water_preservation_passed': water_ok,
            'passed': not mismatches and water_ok,
            'capture_started_at': after.get('capture_started_at'), 'capture_finished_at': after.get('capture_finished_at'),
            'atomic_snapshot': False,
            'note': 'Sequential map captures; edits must be idle during each capture. This checks every visible surface and the observed water blocks in the edit. Hidden untouched blocks outside the voxel survey are not inferred. Live voxel and headroom checks are separate.'}


def render(after, layout, report, path):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgb

    heights = np.asarray(after['surface_y'], dtype=float).reshape(after['length'], after['width'])
    ids = np.asarray(after['material_index']).reshape(heights.shape)
    colors = after.get('palette_rgb')
    if not isinstance(colors, list) or len(colors) != len(after['palette']):
        raise ValueError('PNG rendering requires the actual map palette_rgb array')
    rgb = np.asarray([to_rgb(c) for c in colors])[ids]
    dz, dx = np.gradient(heights)
    light = (.55 * dx + .55 * dz + .63) / np.sqrt(dx * dx + dz * dz + 1)
    shade = np.clip(.76 + .36 * light, .44, 1.13)
    for index, name in enumerate(after['palette']):
        if name.endswith(('_concrete', '_wool', '_terracotta')):
            shade[ids == index] = 1
        if name in WATER:
            shade[ids == index] = .96
    rgb = np.clip(rgb * shade[:, :, None], 0, 1)
    blocks = layout['blocks']
    x0, x1 = min(b['x'] for b in blocks) - 20, max(b['x'] for b in blocks) + 20
    z0, z1 = min(b['z'] for b in blocks) - 20, max(b['z'] for b in blocks) + 20
    fig, ax = plt.subplots(figsize=(11, 14), facecolor='#f1eee4')
    ax.set_facecolor('#f1eee4')
    ax.imshow(rgb, origin='upper', interpolation='nearest',
              extent=(after['min_x'], after['max_x'] + 1, after['max_z'] + 1, after['min_z']))
    ax.set(xlim=(x0, x1), ylim=(z1, z0), xlabel='X · east →', ylabel='Z (positive south)')
    ax.set_aspect('equal')
    ax.tick_params(colors='#4f594d', labelsize=9)
    for spine in ax.spines.values():
        spine.set_color('#9a9e8c')
    labels = [
        ((0, 9), (64, -10), '01  ARRIVAL SQUARE'),
        ((-14, -117), (33, -156), '02  CLOCK STATION'),
        ((-6, -79), (54, -75), 'Station steps'),
        ((-7, -61), (37, -44), 'Forecourt'),
        ((1, 91), (-57, 115), 'South approach'),
        ((-75, 30), (-74, 62), 'Lake approach'),
        ((-60, -36), (-98, -23), 'Portal approach'),
        ((-63, -72), (-93, -103), 'Northwest promenade'),
        ((67, -84), (77, -117), 'Northeast promenade'),
        ((68, 10), (72, 42), 'East approach')]
    for (x, z), (tx, tz), label in labels:
        ax.annotate(label, xy=(x + .5, z + .5), xytext=(tx, tz),
                    ha='center', va='center', fontsize=8.7 if label[:2] in ('01', '02') else 8,
                    color='#263b31', weight='bold' if label[:2] in ('01', '02') else 'normal',
                    bbox=dict(boxstyle='round,pad=.3', fc='#f8f5ea', ec='#849080', lw=.6, alpha=.96),
                    arrowprops=dict(arrowstyle='-', color='#354b3c', lw=.8, shrinkA=3, shrinkB=2))
    ax.annotate('N', xy=(x1 - 8, z0 + 4), xytext=(x1 - 8, z0 + 18), ha='center', va='center',
                color='#20392d', fontsize=11, weight='bold', arrowprops=dict(arrowstyle='-|>', color='#20392d'))
    bar_x, bar_z = x0 + 8, z1 - 8
    ax.plot([bar_x, bar_x + 25], [bar_z, bar_z], color='#20392d', lw=2)
    ax.text(bar_x + 12.5, bar_z - 2, '25 blocks', ha='center', va='bottom', fontsize=8, color='#20392d',
            bbox=dict(fc='#f8f5ea', ec='none', alpha=.8, pad=1))
    fig.suptitle('SHACRAFT  /  FOUNDATIONS 01 + 02', x=.5, y=.975, fontsize=17, weight='bold', color='#20392d')
    fig.text(.5, .945, 'Actual server surface · north up · local roads and supported foundations',
             ha='center', fontsize=10, color='#52614e')
    status = 'surface check passed' if report['passed'] else f"{report['surface_mismatches']} surface mismatches"
    fig.text(.5, .025, f"{report['verified_surface_columns']:,} map columns checked · {status}\n"
             'Material colors and relief come from the captured world. Labels are annotations.',
             ha='center', fontsize=9, color='#52614e', linespacing=1.6)
    fig.subplots_adjust(left=.09, right=.96, top=.923, bottom=.077)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)


class FakeSnapshot:
    scope = {'project_id': 'project', 'world_id': 'world', 'world_epoch': 'epoch'}

    def __init__(self, states):
        self.states = states

    def state(self, x, y, z):
        return self.states[(x, y, z)]


def fixture_map(heights, materials):
    palette = list(dict.fromkeys(materials))
    return {'format': 'minecraft-builder-surface-map-v1', 'source': 'paper_world_surface',
            'world': 'test', 'world_uuid': 'world', 'world_key': 'minecraft:test',
            'min_x': 0, 'max_x': len(heights) - 1, 'min_z': 0, 'max_z': 0,
            'width': len(heights), 'length': 1, 'surface_y': heights,
            'palette': palette, 'material_index': [palette.index(m) for m in materials]}


class FoundationMapTests(unittest.TestCase):
    def baseline(self):
        before = fixture_map([10, 12, 8], ['minecraft:grass_block', 'minecraft:gold_block', 'minecraft:water'])
        snapshot = FakeSnapshot({(0, 10, 0): 'minecraft:grass_block', (0, 9, 0): 'minecraft:air',
                                 (0, 8, 0): 'minecraft:stone'})
        layout = {'version': 1, 'scope': snapshot.scope,
                  'blocks': [{'x': 0, 'y': 10, 'z': 0, 'block': 'minecraft:air', 'expected': 'minecraft:grass_block'}]}
        return before, snapshot, layout

    def test_cut_exposes_lower_observed_block_and_preserves_other_columns(self):
        before, snapshot, layout = self.baseline()
        after = fixture_map([8, 12, 8], ['minecraft:stone', 'minecraft:gold_block', 'minecraft:water'])
        report = verify(before, after, snapshot, layout)
        self.assertTrue(report['passed'])
        self.assertEqual(report['lower_snapshot_voxels_consulted_after_cuts'], 2)
        self.assertEqual(report['outside_edit_columns_verified'], 2)
        self.assertEqual(report['original_visible_water_columns'], 1)

    def test_unrelated_column_change_is_detected(self):
        before, snapshot, layout = self.baseline()
        after = fixture_map([8, 11, 8], ['minecraft:stone', 'minecraft:gold_block', 'minecraft:water'])
        report = verify(before, after, snapshot, layout)
        self.assertFalse(report['passed'])
        self.assertEqual(report['outside_edit_surface_mismatches'], 1)
        self.assertEqual(report['mismatch_examples'][0]['x'], 1)

    def test_missing_lower_voxel_is_not_treated_as_air(self):
        before, snapshot, layout = self.baseline()
        del snapshot.states[(0, 9, 0)]
        with self.assertRaises(KeyError):
            expected_surface(before, snapshot, layout)

    def test_new_surface_block_properties_reduce_to_material(self):
        before, snapshot, layout = self.baseline()
        snapshot.states[(0, 11, 0)] = 'minecraft:air'
        layout['blocks'].append({'x': 0, 'y': 11, 'z': 0, 'expected': 'minecraft:air',
                                 'block': 'minecraft:smooth_stone_slab[type=bottom,waterlogged=false]'})
        after = fixture_map([11, 12, 8], ['minecraft:smooth_stone_slab', 'minecraft:gold_block', 'minecraft:water'])
        self.assertTrue(verify(before, after, snapshot, layout)['passed'])

    def test_stale_expected_state_and_surface_source_mismatch_rejected(self):
        before, snapshot, layout = self.baseline()
        layout['blocks'][0]['expected'] = 'minecraft:dirt'
        with self.assertRaisesRegex(ValueError, 'baseline'):
            expected_surface(before, snapshot, layout)
        layout['blocks'][0]['expected'] = 'minecraft:grass_block'
        before['palette'][0] = 'minecraft:dirt'
        with self.assertRaisesRegex(ValueError, 'original surface'):
            expected_surface(before, snapshot, layout)

    def test_explicit_barrier_roof_is_invisible_but_legacy_roof_is_visible(self):
        before, snapshot, _ = self.baseline()
        snapshot.states[(0, 20, 0)] = 'minecraft:air'
        layout = {'version': 1, 'scope': snapshot.scope, 'blocks': [
            {'x': 0, 'y': 20, 'z': 0, 'block': 'minecraft:barrier', 'expected': 'minecraft:air'}]}
        legacy_after = fixture_map([20, 12, 8], ['minecraft:barrier', 'minecraft:gold_block', 'minecraft:water'])
        self.assertTrue(verify(before, legacy_after, snapshot, layout)['passed'])
        visible_after = json.loads(json.dumps(before))
        before['ignored_materials'] = visible_after['ignored_materials'] = ['minecraft:barrier']
        self.assertTrue(verify(before, visible_after, snapshot, layout)['passed'])

    def test_replacing_visible_top_with_ignored_barrier_exposes_lower_observed_stone(self):
        before, snapshot, layout = self.baseline()
        layout['blocks'][0]['block'] = 'minecraft:barrier'
        after = fixture_map([8, 12, 8], ['minecraft:stone', 'minecraft:gold_block', 'minecraft:water'])
        before['ignored_materials'] = after['ignored_materials'] = sorted(AIR | {'minecraft:barrier'})
        self.assertTrue(verify(before, after, snapshot, layout)['passed'])

    def test_policy_change_is_not_silently_compared_to_legacy_map(self):
        before, snapshot, layout = self.baseline()
        after = fixture_map([8, 12, 8], ['minecraft:stone', 'minecraft:gold_block', 'minecraft:water'])
        after['ignored_materials'] = sorted(AIR | {'minecraft:barrier'})
        with self.assertRaisesRegex(ValueError, 'policies differ'):
            verify(before, after, snapshot, layout)

    def test_all_transparent_column_keeps_world_min_air_fallback(self):
        before = fixture_map([-64], ['minecraft:air'])
        before['ignored_materials'] = ['minecraft:barrier']
        after = json.loads(json.dumps(before))
        snapshot = FakeSnapshot({(0, -64, 0): 'minecraft:barrier', (0, 20, 0): 'minecraft:air'})
        layout = {'version': 1, 'scope': snapshot.scope, 'blocks': [
            {'x': 0, 'y': 20, 'z': 0, 'block': 'minecraft:barrier', 'expected': 'minecraft:air'}]}
        self.assertTrue(verify(before, after, snapshot, layout)['passed'])

    def test_overhead_addition_uses_captured_map_below_tight_voxel_survey(self):
        before = fixture_map([10], ['minecraft:grass_block'])
        snapshot = FakeSnapshot({(0, 20, 0): 'minecraft:air'})
        layout = {'version': 1, 'scope': snapshot.scope, 'blocks': [
            {'x': 0, 'y': 20, 'z': 0, 'block': 'minecraft:stone', 'expected': 'minecraft:air'}]}
        after = fixture_map([20], ['minecraft:stone'])
        report = verify(before, after, snapshot, layout)
        self.assertTrue(report['passed'])
        self.assertEqual(report['covered_original_tops_known_only_from_before_map'], 1)
        before['ignored_materials'] = ['minecraft:barrier']
        layout['blocks'][0]['block'] = 'minecraft:barrier'
        with self.assertRaises(KeyError):
            expected_surface(before, snapshot, layout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    maps = ROOT / '.runtime/server/plugins/ShacraftTerrain/maps'
    stage = ROOT / '.runtime/foundations-stage02'
    parser.add_argument('--before-map', type=Path, default=maps / 'foundations-before.json')
    parser.add_argument('--after-map', type=Path, default=maps / 'foundations-after.json')
    parser.add_argument('--snapshot', type=Path, default=stage / 'before.json.gz')
    parser.add_argument('--layout', type=Path, default=stage / 'foundations.json')
    parser.add_argument('--report', type=Path, default=stage / 'surface-verification.json')
    parser.add_argument('--png', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(FoundationMapTests))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    before, after, layout = [json.loads(p.read_text()) for p in (args.before_map, args.after_map, args.layout)]
    snapshot = survey.load_snapshot(args.snapshot, survey.scope_of(layout['scope']))
    report = verify(before, after, snapshot, layout)
    report['inputs_sha256'] = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for name, path in [('before_map', args.before_map), ('after_map', args.after_map),
                                                  ('baseline_voxels', args.snapshot), ('desired_layout', args.layout)]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    survey.terrain.save(args.report, report)
    if args.png:
        render(after, layout, report, args.png)
    print(json.dumps({k: v for k, v in report.items() if k not in ('inputs_sha256', 'mismatch_examples', 'note', 'observed_water_voxels_replaced')}, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
