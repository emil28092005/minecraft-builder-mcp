#!/usr/bin/env python3
"""Render a survey atlas from live surface data; optional blocks are a labelled preview."""
import argparse
import json
import math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb, LightSource

ROOT=Path(__file__).resolve().parents[1]
COLOR={'01':'#98d84d','02':'#f6d34a','03':'#9460ce','04':'#23b6b6','05':'#e3544b',
       '06':'#f78d27','07':'#f0f0e6','08':'#4a69d8','09':'#f394b5'}
BLOCK={'lime':'#98d84d','yellow':'#f6d34a','purple':'#9460ce','cyan':'#23b6b6',
       'green':'#527c31','orange':'#f78d27','white':'#f0f0e6','blue':'#4a69d8',
       'pink':'#f394b5','black':'#26282d','light_gray':'#a4aaa6','red':'#e3544b'}

def main():
    p=argparse.ArgumentParser();p.add_argument('surface',type=Path);p.add_argument('--study',type=Path,required=True)
    p.add_argument('--blocks',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();s=json.loads(args.surface.read_text());study=json.loads(args.study.read_text())
    h=np.array(s['surface_y']).reshape(s['length'],s['width']).astype(float)
    indexes=np.array(s['material_index']).reshape(h.shape);palette=list(s['palette']);colors=list(s['palette_rgb'])
    if args.blocks:
        for b in json.loads(args.blocks.read_text())['blocks']:
            x,z=b['x']-s['min_x'],b['z']-s['min_z']
            if b['y']<h[z,x]:continue
            material=b['block']
            if material not in palette:
                palette.append(material)
                colors.append(BLOCK.get(material.replace('minecraft:','').replace('_concrete',''),'#f4cf58'))
            indexes[z,x]=palette.index(material);h[z,x]=b['y']
    rgb=np.array([to_rgb(c) for c in colors])[indexes]
    dz,dx=np.gradient(h);norm=np.sqrt(dx*dx+dz*dz+1)
    shade=np.clip(.76+.36*(.55*dx+.55*dz+.63)/norm,.44,1.13)
    categorical=np.array([m.endswith('_concrete') or m=='minecraft:glowstone' for m in palette])[indexes]
    water=np.array([m=='minecraft:water' for m in palette])[indexes]
    shade=np.where(categorical,1,np.where(water,.96,shade))
    rgb=np.clip(rgb*shade[...,None],0,1)
    bg='#14211e';fg='#e8eade';muted='#a9bcb0'
    fig=plt.figure(figsize=(16,12),facecolor=bg)
    ax=fig.add_axes([.045,.12,.67,.80],facecolor=bg)
    ax.imshow(rgb,extent=(s['min_x']-.5,s['max_x']+.5,s['max_z']+.5,s['min_z']-.5),interpolation='nearest')
    ax.set_xlim(-320,319);ax.set_ylim(384,-255)
    ax.set_xticks(np.arange(-256,320,64));ax.set_yticks(np.arange(-192,384,64))
    ax.tick_params(colors=muted,labelsize=9);ax.set_xlabel('X / blocks',color=muted,labelpad=8)
    ax.set_ylabel('Z / blocks · north up',color=muted,labelpad=8)
    for spine in ax.spines.values():spine.set_color('#607166')
    for d in study['districts']:
        x,z=d['label'];ident=d['id']
        ax.text(x,z-13,ident,ha='center',va='center',fontsize=12,fontweight='bold',color='#14211e',
                bbox=dict(boxstyle='circle,pad=.30',facecolor=COLOR[ident],edgecolor=fg,linewidth=1.1),zorder=9)
    ax.annotate('N',xy=(287,-224),xytext=(287,-198),ha='center',color=fg,fontsize=12,
                arrowprops=dict(arrowstyle='-|>',color=fg,lw=1.5))
    ax.plot([-288,-224],[355,355],color=fg,lw=3);ax.text(-256,370,'64 blocks',color=fg,ha='center',fontsize=9)
    fig.text(.06,.953,'SHACRAFT',color=fg,fontsize=28,fontweight='bold')
    fig.text(.242,.958,'LOBBY / SITE MARKING',color=muted,fontsize=16)
    fig.text(.746,.881,'DISTRICTS',color=muted,fontsize=12,fontweight='bold')
    descriptions={
        '01':'Hexagonal arrival plaza\nCentral Shacraft medallion',
        '02':'Clock tower + station hall\nPavilions and forecourt',
        '03':'Portal concourse\nSix individual portal bays',
        '04':'Airship terminal\nThree piers + flagship reserve',
        '05':'Palm house · winter garden\nObservatory and garden walks',
        '06':'Market square\nSix separate building plots',
        '07':'Arrival avenue and viaduct\nSouthern entrance to the valley',
        '08':'Lake pumping house\nBoardwalk and viewing terrace',
        '09':'Scenic overlooks\nSmall optional ridge trails'}
    for i,d in enumerate(study['districts']):
        y=.842-i*.067;ident=d['id']
        fig.text(.749,y,ident,color=COLOR[ident],fontsize=16,fontweight='bold')
        fig.text(.779,y,descriptions[ident],color=fg,fontsize=10,linespacing=1.55)
    fig.text(.747,.20,'READING THE MARKS',color=muted,fontsize=11,fontweight='bold')
    fig.text(.747,.169,'Color = building / courtyard boundary\nWhite = future path edges\nRaised ribs = bridge deck reservation\nLit stakes = corners and wayfinding',color=fg,fontsize=9,linespacing=1.7,va='top')
    note='DESIGN PREVIEW · proposed blocks over a live survey' if args.blocks else 'ACTUAL WORLD SURFACE · captured after placement · no player camera required'
    fig.text(.06,.055,note,color=fg,fontsize=10)
    fig.text(.06,.035,'768 × 768 world · central development shown · terrain heights and water preserved · paths and stairs are still reservations',color=muted,fontsize=9)
    args.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(args.output,dpi=150,facecolor=bg);plt.close(fig)
    print(args.output)

if __name__=='__main__':main()
