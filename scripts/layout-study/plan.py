"""Design-stage contours and circulation derived from Shacraft's approved height field.
No world access or mutation. Coordinates use north=-Z; fields are planning data only.
"""
from pathlib import Path
import json, math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
from matplotlib.path import Path as MplPath
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.runtime/layout-study'; OUT.mkdir(parents=True,exist_ok=True)
h=np.fromfile(ROOT/'.runtime/terrain-study/natural.f32',dtype='>f4').reshape(768,768).astype(float)
features=[];routes=[]
colors={'01':'#84d440','02':'#f4d35e','03':'#bc80ef','04':'#40c8e3','05':'#64d9a0','06':'#ef9863','07':'#f5f4e9','08':'#4ca3ff','09':'#f07eaf'}
districts=[
 ('01','Arrival square',[0,8],'An open hexagonal plaza; preserve the raised grassy crown. Main north axis reveals the clock tower.'),
 ('02','Clock station',[-18,-119],'A long station hall with projecting clock tower and two end pavilions. Its forecourt faces spawn.'),
 ('03','Portal concourse',[-201,-156],'A chamfered hall with six separate portal-bay footprints and a sunken-feeling garden approach.'),
 ('04','Airship harbor',[179,-137],'East-bank terminal with three west-facing piers above the water gorge. One future flagship uses the middle pier.'),
 ('05','Sky gardens',[207,88],'Three distinct rounded landmarks connected by winding garden paths: greenhouse, winter garden, observatory.'),
 ('06','Market quarter',[-195,225],'Six small footprints follow the slope around a compact square. Use stepped streets and individual foundations.'),
 ('07','Arrival viaduct',[8,284],'A long south approach follows the valley ridge; the final viaduct crosses the merging river branches.'),
 ('08','Lake waterworks',[-135,43],'A compact pumping house above the east lake shore and a low over-water promenade.'),
 ('09','Scenic overlooks',[48,-180],'Small optional lookouts frame the valley, lake and arrival route; no mountain flattening.')]
districts=[dict(id=i,name=n,label=p,color=colors[i],intent=t) for i,n,p,t in districts]

def closed(points): return points+[points[0]] if points[0]!=points[-1] else points

def add(i,d,n,p,role='building',**kw):
 f=dict(id=i,district=d,name=n,type='polyline' if role in ('detail','promenade','pier','bridge','axis') else 'polygon',points=p,color=colors[d],role=role,**kw)
 features.append(f);return f

def ellipse(cx,cz,rx,rz=None,n=72,angle=0):
 rz=rx if rz is None else rz;a=math.radians(angle)
 return closed([[round(cx+math.cos(t)*rx*math.cos(a)-math.sin(t)*rz*math.sin(a)),round(cz+math.cos(t)*rx*math.sin(a)+math.sin(t)*rz*math.cos(a))]for t in np.linspace(0,2*math.pi,n,endpoint=False)])

def rect(cx,cz,w,d,angle=0):
 a=math.radians(angle)
 return closed([[round(cx+x*math.cos(a)-z*math.sin(a)),round(cz+x*math.sin(a)+z*math.cos(a))]for x,z in[(-w/2,-d/2),(w/2,-d/2),(w/2,d/2),(-w/2,d/2)]])

def smooth(points):
 p=np.array([points[0]]+points+[points[-1]],float);out=[]
 for k in range(1,len(p)-2):
  a,b,c,d=p[k-1:k+3];n=max(2,int(np.linalg.norm(c-b)))
  for t in np.linspace(0,1,n,endpoint=False):
   q=.5*((2*b)+(-a+c)*t+(2*a-5*b+4*c-d)*t*t+(-a+3*b-3*c+d)*t*t*t)
   q=[round(float(q[0])),round(float(q[1]))]
   if not out or q!=out[-1]:out.append(q)
 out.append(points[-1]);return out

def route(i,name,points,width=7,role='main',**kw):
 r=dict(id=i,name=name,points=smooth(points),waypoints=points,width=width,role=role,**kw);routes.append(r);return r

add('arrival-hex','01','Arrival square',closed([[0,-37],[39,-15],[43,31],[0,57],[-43,31],[-39,-15]]),'plaza')
add('spawn-medallion','01','Shacraft medallion reserve',ellipse(0,9,16,n=36),'plaza')
add('clock-station','02','Clock station and tower',closed([[-74,-139],[-51,-139],[-51,-145],[16,-145],[16,-139],[40,-139],[40,-98],[13,-98],[13,-83],[-25,-83],[-25,-98],[-74,-98]]))
add('station-clock-base','02','Clock tower base',rect(-6,-105,18,18),'detail')
for cx in[-63,29]:add('station-pavilion-'+str(cx),'02','End pavilion',rect(cx,-119,16,30),'detail')
add('station-forecourt','02','Station forecourt',ellipse(-5,-65,36,15,n=48),'plaza')
add('portal-hall','03','Portal concourse',closed([[-227,-163],[-161,-163],[-152,-154],[-152,-122],[-161,-113],[-227,-113],[-236,-122],[-236,-154]]))
for k,(cx,cz) in enumerate([(x,z)for z in[-151,-125]for x in[-218,-194,-170]],1):add('portal-bay-'+str(k),'03','Portal bay '+str(k),rect(cx,cz,13,8),'detail',number=k)
add('portal-forecourt','03','Portal garden court',ellipse(-159,-93,17,12,n=48),'plaza')
add('harbor-terminal','04','Airship terminal',closed([[169,-170],[191,-170],[199,-162],[199,-103],[191,-95],[169,-95],[161,-103],[161,-162]]))
for k,z in enumerate([-158,-132,-106],1):
 add('airship-pier-'+str(k),'04','Airship pier '+str(k),closed([[161,z-4],[107,z-4],[103,z],[107,z+4],[161,z+4]]),'pier',deck_y=79,number=k)
add('flagship-reserve','04','Flagship mooring reserve',ellipse(78,-132,29,10,n=48),'detail',deck_y=92)
for i,(x,z,rx,rz,n) in enumerate([(185,23,25,25,'Palm glasshouse'),(211,94,22,18,'Winter garden'),(233,152,15,15,'Observatory')],1):
 add('garden-'+str(i),'05',n,ellipse(x,z,rx,rz), 'building')
 add('garden-court-'+str(i),'05',n+' surrounding walk',ellipse(x,z,rx+7,rz+7),'plaza')
add('market-square','06','Market square',ellipse(-195,225,22,25,n=48),'plaza')
for i,(x,z,w,d,a,n) in enumerate([(-219,188,24,18,-8,'Bakery'),(-177,195,24,18,7,'Crafts hall'),(-162,231,17,26,8,'Tea house'),(-178,272,22,18,-8,'Guild shop'),(-214,272,23,17,8,'Workshop'),(-233,239,22,26,-5,'Guild hall')],1):
 add('market-'+str(i),'06',n,rect(x,z,w,d,a))
add('waterworks-pump','08','Pumping house',rect(-135,43,14,18,-15))
add('waterworks-lookout','08','Waterworks lookout',ellipse(-135,69,10,n=32),'plaza')
shore=[]
for z in range(-69,76,3):
 wet=np.where(h[z+384,:384]<48)[0]-384
 if len(wet):shore.append([int(wet[-1]-3),z])
add('lake-boardwalk','08','Lake boardwalk alignment',smooth(shore),'promenade',deck_y=51)
for i,(x,z,r,n) in enumerate([(43,-173,8,'North clock-view belvedere'),(-130,-188,7,'Portal ridge overlook'),(229,-76,8,'Harbor overlook'),(266,110,7,'Garden lookout'),(-258,258,7,'Valley approach lookout')],1):
 add('overlook-'+str(i),'09',n,ellipse(x,z,r,n=32),'plaza')
# Pull the portal footprint north onto its drier shoulder; retain all six bays.
for f in features:
 if f['id']=='portal-hall' or f['id'].startswith('portal-bay-'):
  f['points']=[[x-7,round(-156+(z+138)*.8)] for x,z in f['points']]
# Direct spawn routes make the principal destinations easy to find.
route('station-axis','Clock avenue',[[0,-37],[-4,-48],[-5,-65],[-6,-83]],9)
route('portal-radial','Portal approach',[[-35,-14],[-67,-43],[-107,-65],[-135,-75],[-159,-81]],7)
route('portal-forecourt-link','Portal court entrance',[[-159,-105],[-154,-120],[-164,-139]],5,'secondary')
route('lake-radial','Lake walk',[[-42,18],[-77,27],[-104,38],[-126,40]],5,'secondary')
route('east-radial','Garden approach',[[42,16],[65,10],[82,8]],7)
route('south-axis','Arrival avenue',[[0,57],[3,97],[-5,143],[4,189],[8,237],[7,281],[5,321]],9)
# A district promenade closes two large loops and bypasses spawn.
route('ring-northwest','Station to portals',[[-40,-65],[-77,-76],[-116,-89],[-145,-105],[-152,-122],[-164,-139]],7)
route('ring-west','West inner promenade',[[-147,-111],[-125,-80],[-118,-41],[-110,4],[-115,47],[-113,88],[-127,126]],7)
route('ring-market-north','Market north street',[[-213,128],[-218,148],[-205,171],[-193,182],[-195,200]],7)
route('ring-market-south','Market south street',[[-195,250],[-187,253],[-170,252],[-145,242]],7)
route('ring-south','South inner promenade',[[-72,242],[-36,238],[8,237],[31,218],[46,194],[59,166]],7)
route('ring-garden-south','Garden south promenade',[[143,166],[172,179],[203,172],[218,157]],7)
route('ring-gardens','Garden promenade',[[218,137],[204,117],[186,109],[176,88],[184,65],[201,46]],7)
route('ring-harbor','Harbor garden promenade',[[185,-9],[197,-43],[192,-72],[181,-95]],7)
route('ring-northeast','Station to east bridge',[[40,-95],[60,-91],[82,-78]],7)
route('harbor-bridge-landing','Harbor bridge landing',[[155,-81],[171,-83],[180,-95]],7)
route('garden-bridge-landing','Garden bridge landing',[[151,8],[157,16],[160,23]],7)
route('market-shop-street','Market north street',[[-207,192],[-205,198],[-203,202]],5,'secondary')
route('market-south-shop-street','Market south shops',[[-187,253],[-178,259],[-178,262]],5,'secondary')
route('market-workshop-street','Workshop approach',[[-198,250],[-207,254],[-214,262]],5,'secondary')
route('market-guild-street','Guild approach',[[-216,231],[-220,234],[-222,236]],5,'secondary')
route('market-teahouse-street','Tea house approach',[[-173,229],[-171,229]],5,'secondary')
route('market-crafts-street','Crafts approach',[[-184,203],[-179,206]],5,'secondary')
route('waterworks-connector','Waterworks approach',[[-114,44],[-122,44],[-128,43]],5,'secondary')
route('waterworks-lookout-path','Waterworks viewing path',[[-135,52],[-135,59]],3,'secondary')
# Bridges are measured separately. Grade is a later construction task, not terrain flattening.
for i,n,a,b,w in [
 ('bridge-northeast','Clock / harbor bridge',[82,-78],[155,-81],7),
 ('bridge-east','Spawn / garden bridge',[82,8],[151,8],7),
 ('bridge-southeast','Garden / south bridge',[59,166],[143,166],7),
 ('bridge-market-north','Market / lake bridge',[-127,126],[-213,128],7),
 ('bridge-market-south','Market / arrival bridge',[-145,242],[-72,242],7),
 ('arrival-viaduct','Arrival viaduct',[5,321],[5,383],11)]:
 pts=np.linspace(a,b,int(np.linalg.norm(np.array(b)-a))+1).round().astype(int)
 heights=h[pts[:,1]+384,pts[:,0]+384]
 deck=int(math.ceil(max(heights[0],heights[-1])))+2
 if i=='arrival-viaduct':deck=max(deck,65)
 r=route(i,n,[a,b],w,'bridge',deck_y=deck,minimum_ground=float(heights.min()),endpoint_ground=[float(heights[0]),float(heights[-1])]);
 # Edge lines are appropriate for construction marking; they are not a complete bridge.
 r['intent']='Mark both parapet alignments and abutments; preserve the river and banks.'
 r['abutments']=[dict(point=q,ground_y=round(float(y),1),deck_y=deck,future_stairs=(deck-math.floor(y)>4),rise=deck-math.floor(y)) for q,y in zip([a,b],[heights[0],heights[-1]])]
# Scenic branches never substitute for main circulation.
for i,n,p in[
 ('north-overlook-path','North overlook',[[40,-128],[58,-140],[62,-161],[50,-171]]),
 ('portal-overlook-path','Portal ridge path',[[-159,-151],[-136,-158],[-123,-172],[-129,-181]]),
 ('harbor-overlook-path','Harbor lookout trail',[[196,-80],[213,-75],[221,-76]]),
 ('garden-overlook-path','Garden lookout trail',[[232,96],[249,99],[259,107]]),
 ('south-overlook-path','Valley lookout trail',[[-218,236],[-224,219],[-248,223],[-263,240],[-264,251]])]:route(i,n,p,3,'secondary')
# Geometric checks on the immutable approved field; live blocks must still be checked before writes.
zz,xx=np.mgrid[-384:384,-384:384]
for f in features:
 pts=np.array(f['points']);sample=h[np.clip(pts[:,1]+384,0,767),np.clip(pts[:,0]+384,0,767)]
 if f['type']=='polygon':
  x0,z0=pts.min(axis=0);x1,z1=pts.max(axis=0);px,pz=np.meshgrid(np.arange(x0,x1+1),np.arange(z0,z1+1))
  mask=MplPath(pts).contains_points(np.column_stack((px.flat,pz.flat)),radius=.01).reshape(px.shape)
  sample=h[z0+384:z1+385,x0+384:x1+385][mask]
 f['ground']={'min':round(float(sample.min()),2),'max':round(float(sample.max()),2),'water_samples':int((sample<48).sum()),'samples':len(sample)}
for r in routes:
 pts=np.array(r['points']);v=h[pts[:,1]+384,pts[:,0]+384]
 ds=np.linalg.norm(np.diff(pts,axis=0),axis=1);grade=np.abs(np.diff(v))/np.maximum(ds,.001)
 r['analysis']={'length':round(float(ds.sum()),1),'ground_min':round(float(v.min()),1),'ground_max':round(float(v.max()),1),'p95_raw_grade':round(float(np.percentile(grade,95)),2),'water_samples':int((v<48).sum())}
plan={'schema':'shacraft-layout-study-v1','world':'shacraft_lobby_v2','bounds':{'min_x':-384,'max_x':383,'min_z':-384,'max_z':383},'water_y':48,'status':'offline design; not a world mutation or live snapshot','districts':districts,'features':features,'routes':routes,'construction_notes':[
 'Colored outlines are building reservations, not instructions to level their entire bounding boxes.',
 'Walks remain aligned to terrain; steep local runs need short stairs during the later building phase.',
 'Main avenues 9 blocks, district ring 7, side paths 5, scenic trails 3; marker widths can be thinner than final clear widths.',
 'Keep protected water intact. Bridges have a separate planned deck Y above their endpoint terrain.',
 'The natural western lake bank is too steep for a main ring street. The main route uses the calm inner/east lake shoulder; the low over-water boardwalk is secondary.',
 'No minigame arenas. Six portal bays, three harbor piers, one future flagship reservation.'
]}
(OUT/'layout.json').write_text(json.dumps(plan,indent=2)+'\n')
# Render a design review from data, not a Minecraft screenshot.
dz,dx=np.gradient(h);rock=np.clip((np.hypot(dx,dz)-.55)/1.5,0,1)[...,None]
rgb=np.array([.32,.40,.27])*(1-rock)+np.array([.49,.49,.46])*rock
rgb=LightSource(315,42).shade_rgb(rgb,h,vert_exag=1,blend_mode='soft');rgb=np.where((h<48)[...,None],np.array([.13,.28,.35]),rgb)
fig,ax=plt.subplots(figsize=(14,14),facecolor='#151b18');ax.set_facecolor('#151b18')
ax.imshow(rgb,extent=(-384,384,384,-384))
for r in routes:
 p=np.array(r['points']);lw=2.2 if r['role']!='secondary' else 1
 ax.plot(p[:,0],p[:,1],color='#f7f2de' if r['role']!='bridge' else '#ffffff',lw=lw,alpha=.92,linestyle='-' if r['role']!='bridge' else '--')
for f in features:
 p=np.array(f['points']);ax.plot(p[:,0],p[:,1],color=f['color'],lw=2 if f['role'] not in ('detail','promenade') else 1.25)
for d in districts:
 if d['id']=='09':continue
 x,z=d['label'];ax.text(x,z,d['id'],color='#111914',ha='center',va='center',fontsize=12,fontweight='bold',bbox=dict(boxstyle='circle,pad=.35',fc=d['color'],ec='#111914',lw=1))
ax.set(xlim=(-325,310),ylim=(384,-255),xlabel='X / blocks',ylabel='Z / blocks; north up')
ax.set_title('SHACRAFT / terrain-adapted lobby layout',loc='left',color='#f5f3ea',fontsize=19,pad=22)
ax.tick_params(colors='#b5c0b8');ax.xaxis.label.set_color('#b5c0b8');ax.yaxis.label.set_color('#b5c0b8')
for i,d in enumerate(districts):
 fig.text(.085+(i%3)*.302,.065-(i//3)*.021,d['id']+'  '+d['name'],color=d['color'],fontsize=11)
fig.text(.085,.009,'DESIGN STUDY • Exact approved height field; outlines not yet placed. White: routes / dashed: future bridge spans.',color='#b5c0b8',fontsize=9)
fig.subplots_adjust(left=.06,right=.985,top=.945,bottom=.11)
fig.savefig(OUT/'layout-preview.png',dpi=140);plt.close(fig)
print(json.dumps({'features':len(features),'routes':len(routes),'path_length':round(sum(r['analysis']['length']for r in routes)), 'output':str(OUT)}))
print('BUILDING HEIGHT SPANS')
for f in features:
 if f['role']=='building':print(f['id'],f['ground'])
print('BRIDGES')
for r in routes:
 if r['role']=='bridge':print(r['id'],r['deck_y'],r['endpoint_ground'],r['analysis'])
