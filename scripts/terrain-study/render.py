"""Render comparable scientific previews from sampled height fields; never edits screenshots."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / '.runtime/terrain-study'
OUT = ROOT / 'docs/references'
WATER = 48
fields = [np.fromfile(DATA / name, dtype='>f4').reshape(768, 768).astype(float)
          for name in ['before.f32', 'natural.f32']]
names = ['V1 — rectangular platforms', 'Study — ridges, soft hills, winding water']

def colors(ground):
    dz, dx = np.gradient(ground)
    slope = np.hypot(dx, dz)
    rock = np.clip((slope - .55) / 1.5, 0, 1)[..., None]
    green = np.array([.35, .46, .25])
    stone = np.array([.54, .54, .49])
    rgb = green * (1-rock) + stone * rock
    # Identical materials and lighting for both fields: isolate the shape comparison.
    shaded = LightSource(315, 42).shade_rgb(rgb, ground, vert_exag=1, blend_mode='soft')
    depth = np.clip((WATER-ground)/25, 0, 1)[..., None]
    water = np.array([.19, .46, .50])*(1-depth) + np.array([.12, .30, .37])*depth
    return np.where((ground < WATER)[..., None], water, shaded)

fig, axes = plt.subplots(1, 2, figsize=(16, 8), facecolor='#f4f3ee')
for ax, ground, name in zip(axes, fields, names):
    ax.imshow(colors(ground), extent=(-384,384,384,-384))
    ax.set_title(name, fontsize=16, loc='left', pad=16)
    ax.set_xlabel('X / blocks'); ax.set_ylabel('Z / blocks — north up')
fig.suptitle('Shacraft / terrain composition study · 768 × 768 blocks', fontsize=20, x=.06, ha='left', y=.99)
fig.text(.06,.025,'Computed height fields. Same scale, water level and shading. Right: offline prototype, not yet in Minecraft.',fontsize=11)
fig.subplots_adjust(left=.06,right=.98,top=.90,bottom=.10,wspace=.18)
fig.savefig(OUT/'shacraft-terrain-study-plan.png',dpi=130)
plt.close(fig)

fig=plt.figure(figsize=(16,8),facecolor='#f4f3ee')
for i,(ground,name) in enumerate(zip(fields,names)):
    ax=fig.add_subplot(1,2,i+1,projection='3d',facecolor='#f4f3ee')
    s=4; x=np.arange(-384,384,s); z=np.arange(-384,384,s); xx,zz=np.meshgrid(x,z)
    ax.plot_surface(xx,zz,np.maximum(ground[::s,::s],WATER),facecolors=colors(ground)[::s,::s],
                    rstride=1,cstride=1,linewidth=0,antialiased=False,shade=False)
    ax.set(xlim=(-384,384),ylim=(-384,384),zlim=(25,220))
    ax.set_box_aspect((768,768,195));ax.view_init(elev=37,azim=-58);ax.set_axis_off()
    ax.set_title(name,loc='left',fontsize=16,pad=0)
fig.suptitle('Shacraft / compare silhouettes before rebuilding',fontsize=20,x=.05,ha='left',y=.95)
fig.text(.05,.07,'Geometric preview at true vertical scale. No rectangular plateaus in the new study. No erosion simulation.',fontsize=11)
fig.subplots_adjust(left=.01,right=.99,top=.86,bottom=.10,wspace=-.06)
fig.savefig(OUT/'shacraft-terrain-study-perspective.png',dpi=130)
plt.close(fig)

stats=[]
for ground,name in zip(fields,names):
    dz,dx=np.gradient(ground);s=np.hypot(dx,dz)
    stats.append({'name':name,'min_ground_y':float(ground.min()),'max_ground_y':float(ground.max()),
                  'water_columns':int((ground<WATER).sum()),'slope_p95':float(np.percentile(s,95))})
(OUT/'shacraft-terrain-study.json').write_text(json.dumps({'world_applied':False,'water_level':WATER,'fields':stats},indent=2)+'\n')
print(json.dumps(stats))
