#!/usr/bin/env python3
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle, FancyArrowPatch, Polygon, Arc

OUT = Path('deliverables/current/2026-09-03_handoff_v1/figures/model_review')
OUT.mkdir(parents=True, exist_ok=True)

NAVY='#0B1F33'; NAVY2='#143B59'; INK='#142635'; MUTED='#5E7080'; CYAN='#00AFCB'
TEAL='#00B9A8'; BLUE='#347BC8'; ORANGE='#F39A55'; RED='#E45756'; WHITE='#FFFFFF'
BG='#F4F7F9'; LINE='#D5E1E7'; PALE_BLUE='#E6F0FA'; PALE_TEAL='#E2F5F2'; PALE_ORANGE='#FFF0E2'

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':12})
fig, ax = plt.subplots(figsize=(16,9), facecolor=BG)
ax.set_xlim(0,16); ax.set_ylim(0,9); ax.axis('off')
ax.add_patch(Rectangle((0,8.88),16,.12,fc=CYAN,ec='none'))
ax.text(.68,8.42,'The physical system represented by the model',fontsize=25,fontweight='bold',color=NAVY,va='top')
ax.text(.70,7.93,'The active membrane transfers water inside a counter-current ERV core, followed by final coil conditioning.',fontsize=12.5,color=MUTED,va='top')

def duct(x1,y1,x2,y2,color,width=9):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle='-|>',mutation_scale=20,lw=width,color=color,capstyle='round'))

def box(x,y,w,h,title,subtitle='',fill=WHITE,edge=LINE,accent=CYAN,title_size=13):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.015,rounding_size=.10',fc=fill,ec=edge,lw=1.4))
    ax.add_patch(Rectangle((x,y),.09,h,fc=accent,ec='none'))
    ax.text(x+.25,y+h-.25,title,fontsize=title_size,fontweight='bold',color=NAVY,va='top')
    if subtitle: ax.text(x+.25,y+.25,subtitle,fontsize=10.2,color=MUTED,va='bottom',linespacing=1.25)

def droplet(x,y,scale=.16,color=CYAN):
    verts=[(x,y+scale*1.5),(x-scale*.75,y),(x,y-scale*.75),(x+scale*.75,y)]
    ax.add_patch(Polygon(verts,closed=True,fc=color,ec=WHITE,lw=.5))

# Outdoor condition pictogram
ax.add_patch(Circle((1.02,5.91),.34,fc=PALE_BLUE,ec=BLUE,lw=1.3))
ax.add_patch(Circle((1.38,6.03),.43,fc=PALE_BLUE,ec=BLUE,lw=1.3))
ax.add_patch(Circle((1.75,5.88),.31,fc=PALE_BLUE,ec=BLUE,lw=1.3))
ax.add_patch(FancyBboxPatch((.78,5.60),1.25,.38,boxstyle='round,pad=.01,rounding_size=.15',fc=PALE_BLUE,ec=BLUE,lw=1.3))
for xx in [1.00,1.38,1.76]: droplet(xx,5.23,.10,BLUE)
ax.text(1.38,6.55,'HOT, HUMID\nOUTDOOR AIR',ha='center',va='bottom',fontsize=10.5,fontweight='bold',color=BLUE)

# Occupied zone / building
ax.add_patch(FancyBboxPatch((13.40,2.12),1.95,3.82,boxstyle='round,pad=.02,rounding_size=.08',fc=WHITE,ec=NAVY,lw=1.5))
ax.add_patch(Polygon([(13.25,5.95),(14.37,6.68),(15.50,5.95)],closed=True,fc=NAVY2,ec=NAVY,lw=1.2))
for yy in [2.66,3.42,4.18,4.94]:
    for xx in [13.82,14.52]: ax.add_patch(Rectangle((xx,yy),.34,.38,fc=PALE_BLUE,ec=BLUE,lw=.7))
ax.text(14.38,2.24,'OCCUPIED SPACE',ha='center',fontsize=9.7,fontweight='bold',color=NAVY)

# Main process path
duct(2.12,5.74,4.05,5.74,BLUE,8)
duct(9.62,5.74,10.68,5.74,BLUE,8)
duct(12.42,5.74,13.34,5.74,BLUE,8)
ax.text(3.17,6.08,'PROCESS / SUPPLY AIR',ha='center',fontsize=9.3,fontweight='bold',color=BLUE)

# Return/exhaust path
duct(13.36,2.73,12.34,2.73,TEAL,8)
duct(10.72,2.73,9.62,2.73,TEAL,8)
duct(4.05,2.73,2.05,2.73,TEAL,8)
ax.text(11.62,2.25,'RETURN / RECEIVER AIR',ha='center',fontsize=9.8,fontweight='bold',color=TEAL)
ax.text(1.38,2.80,'EXHAUST\nTO OUTDOORS',ha='center',va='center',fontsize=10.5,fontweight='bold',color=TEAL)

# Active ERV core housing
ax.add_patch(FancyBboxPatch((4.05,1.78),5.58,5.02,boxstyle='round,pad=.02,rounding_size=.14',fc=WHITE,ec=NAVY2,lw=2.0))
ax.add_patch(FancyBboxPatch((4.32,5.15),5.04,1.18,boxstyle='round,pad=.01,rounding_size=.08',fc=PALE_BLUE,ec=BLUE,lw=1.2))
ax.add_patch(FancyBboxPatch((4.32,2.14),5.04,1.18,boxstyle='round,pad=.01,rounding_size=.08',fc=PALE_TEAL,ec=TEAL,lw=1.2))
ax.text(6.84,6.49,'ACTIVE ERV CORE',ha='center',fontsize=15,fontweight='bold',color=NAVY)
ax.text(6.84,5.85,'Outdoor/process channel',ha='center',fontsize=10.5,fontweight='bold',color=BLUE)
ax.text(6.84,2.84,'Counter-current exhaust/receiver channel',ha='center',fontsize=10.5,fontweight='bold',color=TEAL)

# Segments / vertical dividers
for i in range(1,8):
    xx=4.32+i*(5.04/8)
    ax.plot([xx,xx],[2.15,6.32],color=LINE,lw=.8,zorder=1)
for i in range(8):
    xx=4.32+(i+.5)*(5.04/8)
    ax.text(xx,4.84,str(i+1),ha='center',va='center',fontsize=8.5,color=MUTED)

# Membrane sandwich
ax.add_patch(Rectangle((4.32,3.87),5.04,.64,fc='#D7F2EE',ec=TEAL,lw=1.2,zorder=3))
ax.add_patch(Rectangle((4.32,4.50),5.04,.10,fc=ORANGE,ec='none',zorder=4))
ax.add_patch(Rectangle((4.32,3.78),5.04,.10,fc=ORANGE,ec='none',zorder=4))
ax.text(6.84,4.19,'electrically active membrane',ha='center',va='center',fontsize=11,fontweight='bold',color=NAVY,zorder=5)
ax.text(4.46,4.68,'process gas film',fontsize=8.2,color=ORANGE,ha='left')
ax.text(4.46,3.56,'receiver gas film',fontsize=8.2,color=ORANGE,ha='left')

# Water transfer arrows and droplets through membrane
for i in range(8):
    xx=4.32+(i+.5)*(5.04/8)
    ax.add_patch(FancyArrowPatch((xx,5.28),(xx,3.20),arrowstyle='-|>',mutation_scale=11,lw=1.7,color=CYAN,zorder=6))
    droplet(xx,4.96,.085,CYAN)
ax.text(8.94,4.90,'WATER',ha='right',fontsize=8.7,fontweight='bold',color=CYAN)
ax.text(8.94,4.69,'process → exhaust',ha='right',fontsize=8.2,color=CYAN)

# Sensible heat arrows (subtle)
for xx in [5.00,6.25,7.50,8.75]:
    ax.add_patch(FancyArrowPatch((xx,5.42),(xx,3.36),arrowstyle='-|>',mutation_scale=9,lw=.9,color=ORANGE,alpha=.65,zorder=5))

# DC supply / electrodes
ax.add_patch(FancyBboxPatch((5.62,.84),2.46,.64,boxstyle='round,pad=.02,rounding_size=.08',fc=NAVY2,ec=NAVY2))
ax.text(6.85,1.16,'LOW-VOLTAGE DC',ha='center',va='center',fontsize=10.2,fontweight='bold',color=WHITE)
ax.plot([6.00,6.00,4.68,4.68],[1.48,1.63,1.63,3.83],color=RED,lw=1.6)
ax.plot([7.70,7.70,9.02,9.02],[1.48,1.63,1.63,4.54],color=BLUE,lw=1.6)
ax.text(4.58,3.57,'−',fontsize=16,fontweight='bold',color=RED)
ax.text(8.98,4.65,'+',fontsize=14,fontweight='bold',color=BLUE)

# Cooling coil box and condensate
box(10.68,4.91,1.74,1.68,'COOLING COIL','remaining cooling\nand dehumidification',PALE_BLUE,BLUE,BLUE,12)
for i in range(5):
    xx=10.96+i*.24
    ax.plot([xx,xx+.20],[5.15,6.30],color=BLUE,lw=1.2)
ax.add_patch(FancyArrowPatch((11.55,4.92),(11.55,4.33),arrowstyle='-|>',mutation_scale=13,lw=1.5,color=CYAN))
droplet(11.55,4.15,.13,CYAN)
ax.text(11.90,4.10,'condensate',fontsize=8.5,color=CYAN,va='center')

# Return fan / symbol
ax.add_patch(Circle((11.53,2.73),.42,fc=WHITE,ec=TEAL,lw=1.4))
for a in [20,140,260]:
    ax.add_patch(Arc((11.53,2.73),.55,.55,theta1=a,theta2=a+70,color=TEAL,lw=2))
ax.text(11.53,1.98,'exhaust airflow',ha='center',fontsize=8.5,color=TEAL)

# State labels
states=[(3.27,6.42,'OA inlet\n$T,w$'),(9.87,6.42,'active ERV outlet\n$T,w$'),(12.76,6.42,'supply\n$T,w$'),
        (12.72,3.36,'return inlet\n$T,w$'),(3.28,3.36,'exhaust outlet\n$T,w$')]
for x,y,t in states:
    ax.add_patch(FancyBboxPatch((x-.53,y-.26),1.06,.48,boxstyle='round,pad=.01,rounding_size=.06',fc=WHITE,ec=LINE,lw=.8))
    ax.text(x,y-.01,t,ha='center',va='center',fontsize=7.9,color=MUTED,linespacing=1.05)

# Bottom explanatory strip
ax.add_patch(FancyBboxPatch((9.78,.77),5.55,1.01,boxstyle='round,pad=.02,rounding_size=.08',fc=PALE_ORANGE,ec=ORANGE,lw=1.0))
ax.text(10.03,1.47,'WHAT THE MODEL SIMULATES',fontsize=9.5,fontweight='bold',color=ORANGE,va='top')
ax.text(10.03,1.20,'Solve each ERV segment → integrate membrane area and EO power →\nrecalculate the remaining cooling-coil load and known system power.',fontsize=9.0,color=INK,va='top',linespacing=1.25)

ax.add_patch(FancyBboxPatch((.74,.76),3.62,.78,boxstyle='round,pad=.02,rounding_size=.08',fc=NAVY2,ec=NAVY2))
ax.text(2.55,1.16,'INTEGRATED EO MEMBRANE',ha='center',va='center',fontsize=11.5,fontweight='bold',color=WHITE)

fig.savefig(OUT/'00_simulated_system_setup.png',dpi=200,bbox_inches='tight',facecolor=fig.get_facecolor())
fig.savefig(OUT/'00_simulated_system_setup.svg',bbox_inches='tight',facecolor=fig.get_facecolor())
plt.close(fig)
print('Wrote system setup figure')
