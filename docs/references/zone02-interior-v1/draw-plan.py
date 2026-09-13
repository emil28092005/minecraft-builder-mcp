"""Render the proposed station layout against the saved, block-exact foundation.

Read-only design utility; it never connects to or writes the Minecraft world.
All X/Z boxes are inclusive block coordinates. Pillow is required.
"""
import json
from pathlib import Path
from collections import Counter
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/foundations-stage02/foundations-final.geometry.json'
geometry = json.loads(SOURCE.read_text())
foot = {(c['x'], c['z']) for c in geometry['cells'] if c['group'] == 'clock-station'}
inner = {p for p in foot if all((p[0]+dx,p[1]+dz) in foot for dx in range(-2,3) for dz in range(-2,3))}
walls = foot-inner

def cells(box):
    a,b,c,d = box
    return {(x,z) for x in range(a,b+1) for z in range(c,d+1)}

core = [-10,-2,-124,-116]
cabin = [-8,-4,-122,-118]
bays = [[x-3,x+3,-140,-136] for x in [-42,-32,-22,-12,-2,8]]
display = [-42,-24,-124,-110]
pillars = [[x,x+1,z,z+1] for x in [-69,-49,-19,17,31] for z in [-127,-104]]
benches = [[x,x+7,z,z+1] for x in [-67,24] for z in [-132,-108]]
features = {'lift housing':core,'lift cabin':cabin,'display':display}
features.update({f'arena bay {i+1}':b for i,b in enumerate(bays)})
features.update({f'column {i+1}':b for i,b in enumerate(pillars)})
features.update({f'bench {i+1}':b for i,b in enumerate(benches)})
for name,box in features.items():
    assert cells(box) <= inner, (name,'outside two-block perimeter setback')
solid_features = [core,display,*bays,*pillars,*benches]
for i,a in enumerate(solid_features):
    for b in solid_features[i+1:]:
        assert not cells(a)&cells(b), ('furniture overlap',a,b)
route = cells([-9,-3,-115,-85])
assert route <= foot
assert not route & set().union(*(cells(b) for b in solid_features))
bay_aisle = cells([-46,11,-135,-129])
assert bay_aisle <= inner
assert not bay_aisle & set().union(*(cells(b) for b in solid_features))
map_path = ROOT / '.runtime/server/plugins/ShacraftTerrain/maps/zone01-complete.json'
surface=json.loads(map_path.read_text())
hist=Counter(surface['surface_y'][(z-surface['min_z'])*surface['width']+x-surface['min_x']] for x,z in foot)
design = {
 'status':'PROPOSAL ONLY. Foundation is surveyed; walls, interiors and upper levels are not built.',
 'world':'shacraft_lobby_v2','coordinate_convention':'X/Z boxes include both endpoints. Floor Y is block Y; walk Y is top of that floor.',
 'foundation_source':str(SOURCE.relative_to(ROOT)), 'surface_capture_finished_at':surface['capture_finished_at'],
 'foundation_columns':len(foot),'foundation_bounds':[-74,40,-145,-83], 'foundation_surface_height_counts':dict(hist),
 'floors':[{'name':'1 Vestibule','floor_block_y':98,'walk_y':99,'ceiling_underside_y':111,'clear_height':12},
           {'name':'2 Smash','floor_block_y':112,'walk_y':113,'ceiling_underside_y':124,'clear_height':11}],
 'intermediate_deck_block_y':[111,112], 'perimeter_wall_thickness':2,
 'main_roof_eaves_y':126,'main_roof_ridge_y':140,'clocktower_peak_y':158,
 'entrance_axis_x':-6,'entrance_opening_x':[-9,-3],'entrance_threshold_z':[-84,-83],
 'lift':{'housing':core,'clear_cabin':cabin,'door_clear_x':[-8,-4],'door_z':[-117,-116],'opens':'south','same_location_on_both_floors':True},
 'smash_display':display,'smash_selection_bays':bays,'aligned_columns':pillars,'wing_benches':benches,
 'reserved_clear_aisles':{'entry':[-9,-3,-115,-85],'bay_front':[-46,11,-135,-129]},
 'checks':{'features_inside_two_block_setback':True,'solid_features_do_not_overlap':True,'entry_route_clear_width':7,'bay_front_clear_depth':7},
 'limitations':['Saved surface export is not a fresh live scan.', 'Containment and overlap checks cover the proposed plan, not constructed voxels.',
 'Generated perspectives are artistic references; this coordinate specification governs placement.', 'Arena sign slots are unassigned, not working destinations.',
 'Future floors need an explicit roof/height design before construction. Only the lift alignment is reserved.']}
(OUT/'layout.json').write_text(json.dumps(design,indent=2)+'\n')

W,H=2000,1530
im=Image.new('RGB',(W,H),'#f5f1e7'); d=ImageDraw.Draw(im)
REG='/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-Regular.ttf'
BOLD='/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-SemiBold.ttf'
SERIF='/usr/share/fonts/truetype/ibm-plex/IBMPlexSerif-Regular.ttf'
def text(x,y,s,size=22,color='#203e36',bold=False,anchor=None):
    d.text((x,y),s,font=ImageFont.truetype(BOLD if bold else REG,size),fill=color,anchor=anchor)
text(65,35,'SHACRAFT / CLOCK STATION',44,bold=True)
text(65,93,'01 VESTIBULE + 02 SMASH     /     COORDINATE PLAN     /     DESIGN v1',22)
text(65,133,'Fixed foundation: 115 x 63 blocks overall. North is up. Both plans use the same 1-block grid.',21)
green='#376956';orange='#bd633b';wall='#58635c';floor='#e8dfcc';gold='#d0aa54'

def plan(ox,title,upper=False):
    oy=255; sc=7
    def xy(x,z): return ox+(x+74)*sc,oy+(z+145)*sc
    def box(b,fill,outline=None):
        a,c=xy(b[0],b[2]);bb,dd=xy(b[1]+1,b[3]+1)
        d.rectangle((a,c,bb-1,dd-1),fill=fill,outline=outline)
    def label(x,z,s,size=17,col='#203e36'):
        a,b=xy(x,z);text(a,b,s,size,col,anchor='mm')
    text(ox,196,title,28,bold=True)
    for x,z in foot: box([x,x,z,z], wall if (x,z) in walls else floor)
    # Discrete occupied columns avoid polygon boundary ambiguity.
    for x,z in inner:
        a,b=xy(x,z)
        d.line((a,b,a+sc,b),fill='#ddd5c4')
        d.line((a,b,a,b+sc),fill='#ddd5c4')
    for b in pillars: box(b,'#7b8177')
    for b in benches: box(b,'#957753')
    box(core,green);box(cabin,'#cbdcd0')
    box([-8,-4,-117,-116],'#cbdcd0')
    label(-5.5,-120,'L',21)
    if upper:
        box(display,orange)
        label(-32.5,-118,'DISPLAY',16,'#ffffff')
        label(-32.5,-114,'19 x 15',16,'#ffffff')
        for i,b in enumerate(bays):
            box(b,gold);label((b[0]+b[1]+1)/2,-137.5,f'{i+1:02}',16)
        label(-17,-132,'7-BLOCK CLEAR AISLE',17)
        label(-60,-118,'RULES',17)
        label(28,-118,'WAIT',17)
        label(-5,-94,'SOUTH GALLERY',17)
    else:
        label(-58,-118,'WAITING',17)
        label(28,-118,'WAITING',17)
        label(-34,-117,'VESTIBULE',19)
        box([1,7,-113,-111],gold)
        label(4,-107,'DIRECTORY',15)
        # South doorway through both perimeter wall blocks.
        box([-9,-3,-84,-83],floor)
        a,b=xy(-5.5,-88);c,e=xy(-5.5,-111)
        d.line((a,b,c,e),fill=green,width=4)
        d.polygon([(c,e),(c-8,e+14),(c+8,e+14)],fill=green)
        label(-5.5,-97,'7 wide',15)
    # Outside dimensions and orientation.
    text(ox+402,oy-21,'115 blocks',19,anchor='mm')
    d.line((ox,oy-8,ox+805,oy-8),fill=wall,width=2)
    for x in [ox,ox+805]: d.line((x,oy-14,x,oy-2),fill=wall,width=2)
    text(ox+842,oy+213,'63',21,anchor='mm');text(ox+842,oy+240,'blocks',16,anchor='mm')
    d.line((ox+817,oy,ox+817,oy+441),fill=wall,width=2)
    for z in [-145,-125,-105,-83]:
        a,b=xy(-74,z);text(a-12,b,str(z),15,anchor='rm')
    for x in [-74,-50,-25,0,40]:
        a,b=xy(x,-82);text(a,b+18,str(x),16,anchor='mm')
    text(ox+23,oy+398,'N',23,bold=True)
    d.line((ox+31,oy+397,ox+31,oy+358),fill=green,width=3)
    d.polygon([(ox+31,oy+352),(ox+23,oy+366),(ox+39,oy+366)],fill=green)
    text(ox,oy+491,'X: east-west  /  Z: north-south  /  unit: one block',18)

plan(105,'01 / VESTIBULE  •  WALK Y99')
plan(1100,'02 / SMASH  •  WALK Y113',True)
d.line((65,792,1935,792),fill='#bdb8aa',width=2)
text(65,825,'SECTION / ENTRANCE AXIS X = -6',27,bold=True)
text(1060,825,'DESIGN RULES',27,bold=True)
# North at left, south at right; Y shown as world surface elevations.
sx,sy,scale=105,1200,11
def section_box(z0,z1,y0,y1,fill):
    d.rectangle((sx+(z0+145)*scale,sy-(y1-98)*scale,sx+(z1+145)*scale-1,sy-(y0-98)*scale-1),fill=fill)
section_box(-145,-82,98,99,wall)
section_box(-145,-82,111,113,wall)
section_box(-145,-82,124,126,wall)
section_box(-145,-143,99,124,wall)
section_box(-84,-82,99,124,wall)
section_box(-84,-82,99,105,'#f5f1e7')
for y in [99,113]:
    top=111 if y==99 else 124
    section_box(-124,-122,y,top,green)
    section_box(-118,-116,y+6,top,green)
    section_box(-122,-118,y,y+0.25,gold)
for y,lab in [(99,'Y99 / level 1'),(111,'Y111 / ceiling'),(113,'Y113 / level 2'),(124,'Y124 / ceiling')]:
    yy=sy-(y-98)*scale
    d.line((sx-12,yy,sx+720,yy),fill='#b4afa2',width=1)
    text(sx+735,yy,lab,18,anchor='lm')
text(455,1072,'12 clear',23,anchor='mm')
text(455,924,'11 clear',23,anchor='mm')
text(105,1234,'NORTH',18);text(735,1234,'SOUTH / ENTRY',18)
notes=[
 'Fixed footprint; 2-block perimeter walls.',
 'Lift: 9 x 9 housing; 5 x 5 clear cabin.',
 'Same shaft and south-facing door on both floors.',
 'Six 7 x 5 sign bays; destinations remain unassigned.',
 'SMASH display is scenery on a solid, enclosed floor.',
 'Gameplay takes place in separate arena worlds.',
 'Future stories are not furnished or dimensioned here.',
 'Concept images illustrate style; layout.json governs placement.'
]
for i,s in enumerate(notes): text(1060,878+i*43,s,21)
text(65,1320,'VERIFIED AGAINST THE SAVED FOUNDATION',22,bold=True)
text(65,1358,f'{len(foot):,} foundation columns • all specified furnishings inside the wall setback • no furnishing overlaps',21)
text(65,1394,'This is a design drawing, not a live scan or a completed building. Above-ground shell and floors are proposed.',21)
text(65,1452,'SOURCE: foundations-final.geometry.json + zone01-complete surface export  /  13 SEP 2026',18)
im.save(OUT/'00-coordinate-plan.png')
im.save(OUT/'00-coordinate-plan.pdf',resolution=150)
print(json.dumps({'saved':str(OUT),'foundation_columns':len(foot),'height_counts':dict(hist),'checks':'passed'}))
