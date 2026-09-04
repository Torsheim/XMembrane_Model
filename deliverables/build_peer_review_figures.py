#!/usr/bin/env python3
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle, FancyArrowPatch
import numpy as np

OUT = Path('deliverables/current/2026-09-03_handoff_v1/figures/model_review')
OUT.mkdir(parents=True, exist_ok=True)

NAVY = '#0B1F33'; NAVY2 = '#143B59'; INK = '#142635'; MUTED = '#5E7080'
CYAN = '#00AFCB'; TEAL = '#00B9A8'; BLUE = '#347BC8'; ORANGE = '#F39A55'; RED = '#E45756'
WHITE = '#FFFFFF'; BG = '#F4F7F9'; LINE = '#D5E1E7'; LIGHT = '#EAF1F4'
PALE_BLUE = '#E6F0FA'; PALE_TEAL = '#E2F5F2'; PALE_ORANGE = '#FFF0E2'; PALE_RED = '#FCE9E8'

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':12,'axes.titlesize':22,'figure.dpi':150})

def canvas(title, subtitle=''):
    fig, ax = plt.subplots(figsize=(16,9), facecolor=BG)
    ax.set_xlim(0,16); ax.set_ylim(0,9); ax.axis('off')
    ax.add_patch(Rectangle((0,8.88),16,.12,color=CYAN,lw=0))
    ax.text(.7,8.35,title,fontsize=25,fontweight='bold',color=NAVY,va='top')
    if subtitle: ax.text(.72,7.85,subtitle,fontsize=12.5,color=MUTED,va='top')
    return fig, ax

def box(ax,x,y,w,h,title,body='',accent=CYAN,fill=WHITE,title_size=14,body_size=11):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.015,rounding_size=.09',fc=fill,ec=LINE,lw=1.2))
    ax.add_patch(Rectangle((x,y),.08,h,color=accent,lw=0))
    ax.text(x+.25,y+h-.28,title,fontsize=title_size,fontweight='bold',color=NAVY,va='top')
    if body: ax.text(x+.25,y+h-.78,body,fontsize=body_size,color=MUTED,va='top',linespacing=1.35)

def arrow(ax,x1,y1,x2,y2,color=CYAN,lw=2.2,style='-|>'):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle=style,mutation_scale=15,lw=lw,color=color))

def save(fig,name):
    fig.savefig(OUT/f'{name}.png',dpi=180,bbox_inches='tight',facecolor=fig.get_facecolor())
    fig.savefig(OUT/f'{name}.svg',bbox_inches='tight',facecolor=fig.get_facecolor())
    plt.close(fig)

# 1. Model hierarchy
fig,ax=canvas('Figure 1 — From local membrane physics to system power',
              'Every higher layer reuses the solved state from the layer below.')
layers=[
 ('1D membrane','$a_w(x)$, $V(x)$, $N_w$, $j$',CYAN),
 ('Gas films','bulk ↔ surface activity',ORANGE),
 ('Axial core','air states, area, power',BLUE),
 ('Electrode state','$\eta(t)$, charge and clamp',RED),
 ('System ledger','ERV, coil and known power',NAVY)
]
for i,(t,b,c) in enumerate(layers):
    x=1.0+i*3.02
    box(ax,x,3.25,2.43,2.25,t,b,c,WHITE,13,9.8)
    ax.add_patch(Circle((x+1.21,6.15),.28,fc=c,ec=WHITE,lw=1.5))
    ax.text(x+1.21,6.15,str(i+1),color=WHITE,fontweight='bold',ha='center',va='center')
    if i<4: arrow(ax,x+2.47,4.38,x+2.97,4.38,CYAN,2.4)
ax.add_patch(FancyBboxPatch((2.2,1.55),11.6,.78,boxstyle='round,pad=.02,rounding_size=.08',fc=NAVY2,ec=NAVY2))
ax.text(8,1.94,'Conservation contract: water removed from process = water gained by receiver',
        color=WHITE,fontweight='bold',fontsize=14,ha='center',va='center')
ax.text(8,.72,'Use this figure to introduce the hierarchy before showing any equations.',ha='center',color=MUTED,fontsize=11)
save(fig,'01_model_hierarchy')

# 2. Local membrane control volume
fig,ax=canvas('Figure 2 — Local membrane control volume and boundary conditions',
              'Positive water flux and current are defined from process/source to receiver.')
ax.add_patch(FancyBboxPatch((4.2,2.45),7.6,2.55,boxstyle='round,pad=.02,rounding_size=.08',fc=PALE_TEAL,ec=TEAL,lw=1.5))
ax.text(8,4.72,'ACTIVE MEMBRANE  |  $x\in[0,L]$',ha='center',va='top',color=NAVY,fontweight='bold',fontsize=15)
ax.add_patch(FancyBboxPatch((1.05,2.45),2.35,2.55,boxstyle='round,pad=.02,rounding_size=.08',fc=PALE_BLUE,ec=BLUE,lw=1.3))
ax.add_patch(FancyBboxPatch((12.6,2.45),2.35,2.55,boxstyle='round,pad=.02,rounding_size=.08',fc=PALE_ORANGE,ec=ORANGE,lw=1.3))
ax.text(2.22,4.48,'PROCESS BULK',ha='center',fontweight='bold',color=BLUE)
ax.text(13.78,4.48,'RECEIVER BULK',ha='center',fontweight='bold',color=ORANGE)
ax.text(2.22,3.72,'$a_{s,bulk}$',ha='center',fontsize=18,color=NAVY)
ax.text(13.78,3.72,'$a_{r,bulk}$',ha='center',fontsize=18,color=NAVY)
arrow(ax,3.4,3.40,4.2,3.40,BLUE,2.4)
arrow(ax,11.8,3.40,12.6,3.40,ORANGE,2.4)
ax.text(3.80,3.66,'$K_s$',ha='center',color=BLUE,fontweight='bold')
ax.text(12.20,3.66,'$K_r$',ha='center',color=ORANGE,fontweight='bold')
ax.axvline(4.55,ymin=.27,ymax=.54,color=TEAL,lw=2); ax.axvline(11.45,ymin=.27,ymax=.54,color=TEAL,lw=2)
ax.text(4.56,2.12,'$a_{s,surf}$',ha='center',fontsize=15,color=NAVY)
ax.text(11.45,2.12,'$a_{r,surf}$',ha='center',fontsize=15,color=NAVY)
arrow(ax,5.1,3.48,10.9,3.48,CYAN,3.2)
ax.text(8,3.76,'positive $N_w$ and $j$',ha='center',color=CYAN,fontweight='bold')
ax.text(8,2.95,r'$N_w=n_d,j/F-D_w(a_w)S_w(a_w),da_w/dx$',ha='center',fontsize=18,color=NAVY)
ax.text(8,1.35,r'$N_w=K_s(a_{s,bulk}-a_{s,surf})=K_r(a_{r,surf}-a_{r,bulk})$',ha='center',fontsize=16,color=NAVY)
ax.add_patch(FancyBboxPatch((4.15,.48),7.7,.52,boxstyle='round,pad=.02,rounding_size=.06',fc=PALE_RED,ec=PALE_RED))
ax.text(8,.74,r'Admissibility: $0<a_{s,surf},a_{r,surf}<1$ and finite positive net flux',ha='center',va='center',color=RED,fontweight='bold')
save(fig,'02_local_membrane_control_volume')

# 3. Voltage solution algorithm
fig,ax=canvas('Figure 3 — Applied terminal voltage determines the current density',
              'The model does not independently prescribe voltage and current.')
steps=[
 ('Input','$V_{applied}$ and\nlocal air states',BLUE),
 ('Physical bracket','$j_{low}=0$; $j_{high}$\nfrom the film limit',ORANGE),
 ('Local solve','Solve $N_w$, surfaces\nand $V_{calc}$',CYAN),
 ('Bisection','Update the current bracket\nfrom the voltage residual',TEAL),
 ('Acceptance','Voltage residual and\nlocal gates pass',NAVY)
]
for i,(t,b,c) in enumerate(steps):
    x=.8+i*3.08
    box(ax,x,3.05,2.55,2.25,t,b,c,WHITE,13,9.8)
    if i<4: arrow(ax,x+2.58,4.18,x+3.02,4.18,CYAN,2.2)
ax.add_patch(FancyBboxPatch((3.45,1.44),9.1,.78,boxstyle='round,pad=.02,rounding_size=.08',fc=PALE_TEAL,ec=TEAL,lw=1.2))
ax.text(8,1.83,r'Converged state: $|V_{calc}-V_{applied}|\leq\epsilon_V$  →  report $j$, $N_w$, area and power',
        ha='center',va='center',fontsize=14,color=NAVY,fontweight='bold')
loop=FancyArrowPatch((11.6,2.95),(8.0,2.58),connectionstyle='arc3,rad=-.25',arrowstyle='-|>',mutation_scale=16,lw=2,color=TEAL)
ax.add_patch(loop); ax.text(10.05,2.32,'repeat until voltage closes',ha='center',color=TEAL,fontweight='bold',fontsize=11)
ax.text(8,.62,'Internal current search ceilings are numerical guards, not engineering acceptance limits.',ha='center',color=RED,fontweight='bold',fontsize=11.5)
save(fig,'03_voltage_to_current_algorithm')

# 4. Two integration paths
fig,ax=canvas('Figure 4 — Two core-integration paths answer different questions',
              'Do not compare areas unless material, geometry, receiver boundary and numerical basis are matched.')
box(ax,.8,1.45,7.0,5.55,'PATH A — COUPLED V12.1','',TEAL,PALE_TEAL,16,11)
box(ax,8.2,1.45,7.0,5.55,'PATH B — DIRECT ACTIVE-ERV SCREEN','',ORANGE,PALE_ORANGE,16,11)
left=[('Start','process inlet + conditioned receiver outlet'),('March','update both streams with same flux'),('Adapt','halve area step when end state fails'),('Finish','resolve exact target event and far-end residual')]
right=[('Construct','balanced process/receiver endpoints'),('Interpolate','bulk T and w over fixed segments'),('Size','solve each local state; $A_i=\dot n_i/N_i$'),('Audit','midpoints + n+1 physical boundaries')]
for col,data,c,x in [('L',left,TEAL,1.18),('R',right,ORANGE,8.58)]:
    for i,(t,b) in enumerate(data):
        y=5.85-i*1.02
        ax.add_patch(Circle((x+.28,y),.22,fc=c,ec=WHITE,lw=1))
        ax.text(x+.28,y,str(i+1),ha='center',va='center',color=WHITE,fontweight='bold',fontsize=10)
        ax.text(x+.72,y+.15,t,color=NAVY,fontweight='bold',fontsize=12,va='center')
        ax.text(x+.72,y-.19,b,color=MUTED,fontsize=10.5,va='center')
        if i<3: arrow(ax,x+.28,y-.28,x+.28,y-.73,c,1.7)
ax.add_patch(FancyBboxPatch((2.3,.48),11.4,.57,boxstyle='round,pad=.02,rounding_size=.07',fc=NAVY2,ec=NAVY2))
ax.text(8,.765,'Path A: target-reaching receiver sensitivity  |  Path B: fast architecture/material frontier screening',
        ha='center',va='center',color=WHITE,fontweight='bold',fontsize=12.2)
save(fig,'04_two_integration_paths')

# 5. Counter-current state evolution schematic
fig,ax=canvas('Figure 5 — Counter-current evolution changes the local driving force',
              'Schematic profiles; direction and shape are illustrative, not a simulated case.')
x=np.linspace(0,1,200)
wp=14.5-5.8*(x**.78)
wr=12.2-3.5*x**1.25  # plotted in process coordinate; receiver flows opposite
axp=fig.add_axes([.10,.25,.78,.48],facecolor=WHITE)
axp.plot(x,wp,color=BLUE,lw=3,label='Process humidity ratio')
axp.plot(x,wr,color=TEAL,lw=3,label='Receiver humidity ratio (process coordinate)')
axp.fill_between(x,wr,wp,where=wp>=wr,color=CYAN,alpha=.12,label='local humidity-ratio separation')
axp.set_xlim(0,1); axp.set_ylim(7.5,15.5); axp.grid(color=LINE,lw=.8)
axp.set_xlabel('Normalized position in process direction  x/Lcore',fontweight='bold',color=MUTED)
axp.set_ylabel('Humidity ratio  [g/kg dry air]',fontweight='bold',color=MUTED)
axp.spines[['top','right']].set_visible(False)
axp.legend(loc='upper center',ncol=3,frameon=False,fontsize=10)
axp.annotate('process flow',xy=(.98,14.9),xytext=(.70,14.9),arrowprops=dict(arrowstyle='-|>',color=BLUE,lw=2),color=BLUE,fontweight='bold')
axp.annotate('receiver flow',xy=(.02,8.4),xytext=(.30,8.4),arrowprops=dict(arrowstyle='-|>',color=TEAL,lw=2),color=TEAL,fontweight='bold',ha='right')
for xx in [.12,.32,.52,.72,.92]:
    yp=np.interp(xx,x,wp); yr=np.interp(xx,x,wr)
    axp.annotate('',xy=(xx,yr+.08),xytext=(xx,yp-.08),arrowprops=dict(arrowstyle='-|>',color=CYAN,lw=1.5))
save(fig,'05_countercurrent_state_evolution')

# 6. Verification / validation / closure
fig,ax=canvas('Figure 6 — Evidence ladder: verification is necessary but not sufficient',
              'A system claim is only as strong as the least-closed layer.')
levels=[
 ('1  Numerical verification','Equations implemented consistently\nResiduals, equivalence tests, step convergence',BLUE,PALE_BLUE),
 ('2  Component validation','Measured vapor flux, drag, ASR and films\nMatched donor/receiver balance',TEAL,PALE_TEAL),
 ('3  Subsystem validation','Active core, electrodes, fans and heat\nRepresentative boundary conditions',ORANGE,PALE_ORANGE),
 ('4  System closure','Receiver handling + heat rejection + controls\nComplete equal-service power ledger',RED,PALE_RED)
]
for i,(t,b,c,f) in enumerate(levels):
    x=1.1+i*.72; y=1.35+i*1.35; w=13.8-i*1.44
    ax.add_patch(FancyBboxPatch((x,y),w,1.05,boxstyle='round,pad=.02,rounding_size=.07',fc=f,ec=c,lw=1.2))
    ax.text(x+.32,y+.70,t,color=NAVY,fontweight='bold',fontsize=14,va='center')
    ax.text(x+4.45,y+.55,b,color=MUTED,fontsize=10.8,va='center',linespacing=1.25)
    if i<3: arrow(ax,8,y+1.08,8,y+1.30,c,1.8)
ax.text(8,.58,'V10 status: numerical verification passes; measured electrode/material response and dynamic system validation remain open.',ha='center',color=RED,fontweight='bold',fontsize=11.5)
save(fig,'06_evidence_ladder')

# 7. Electrode transient as a system boundary (block diagram, not a trend plot)
fig,ax=canvas('Figure 7 — The steady transport state is nested inside an electrode transient',
              'The time-domain replay converts local steady demand into charge accumulation and a terminal-voltage limit.')
box(ax,.70,3.00,3.15,2.35,'STEADY EO DEMAND',
    'Local air states + applied voltage\n→ solved $j_{cmd}$ and $N_w$\n→ required active area',CYAN,PALE_TEAL,12.5,10)
box(ax,4.45,3.00,3.15,2.35,'ELECTRODE STATE',
    '$C_{pair,A}\,d\eta/dt=j_{cmd}-j_F$\n\n$j_F=\eta/R_{leak,A}$',ORANGE,PALE_ORANGE,12.5,10.5)
box(ax,8.20,3.00,3.15,2.35,'TERMINAL CLAMP',
    '$V_{term}=V_{mem}+jR_{int,A}+\eta$\n\nThe clamp sets admissible $j$.',RED,PALE_RED,12.5,9.8)
box(ax,11.95,3.00,3.15,2.35,'DYNAMIC OUTPUT',
    'retained current\nretained EO flux\ncharge and energy audit',NAVY,LIGHT,12.5,10)
for x in [3.85,7.60,11.35]:
    arrow(ax,x,4.18,x+.60,4.18,CYAN,2.3)
arrow(ax,13.52,2.92,6.02,2.25,RED,2.0)
ax.text(9.75,2.10,'voltage saturation feeds back to the admissible current',
        ha='center',color=RED,fontweight='bold',fontsize=11)
ax.add_patch(FancyBboxPatch((1.35,.72),13.30,.76,boxstyle='round,pad=.02,rounding_size=.08',fc=NAVY2,ec=NAVY2))
ax.text(8,1.10,'Complete-cycle audit: a symmetric blocking cycle returns stored charge and transported water to their initial states.',
        ha='center',va='center',color=WHITE,fontweight='bold',fontsize=10.8)
ax.text(8,6.58,'Primary O30 replay at the original 0.025 V limit: 16.2% retained after 1 h; 0.68% over 24 h.',
        ha='center',color=NAVY,fontweight='bold',fontsize=11.8)
ax.text(8,6.18,'Separate optimistic 1.8 V upper bound: 98.5% after 1 h; 4.6% over 24 h — not a same-voltage replay.',
        ha='center',color=ORANGE,fontweight='bold',fontsize=11.2)
ax.text(8,5.78,'Measured Faradaic, pseudocapacitive or asymmetric behavior is required before assigning sustained-duty performance.',
        ha='center',color=RED,fontweight='bold',fontsize=10.8)
save(fig,'07_electrode_transient_boundary')

# Contact sheet
from PIL import Image, ImageDraw
files=sorted(f for f in OUT.glob('*.png') if f.name != 'contact_sheet.png')
thumbs=[]
for f in files:
    im=Image.open(f).convert('RGB'); im.thumbnail((560,315))
    c=Image.new('RGB',(580,350),'white'); c.paste(im,((580-im.width)//2,8))
    ImageDraw.Draw(c).text((10,330),f.stem,fill=INK)
    thumbs.append(c)
rows=(len(thumbs)+1)//2
sheet=Image.new('RGB',(1160,rows*350),(225,232,237))
for i,t in enumerate(thumbs): sheet.paste(t,((i%2)*580,(i//2)*350))
sheet.save(OUT/'contact_sheet.png')
print(f'Wrote {len(files)} figures plus contact sheet to {OUT}')
