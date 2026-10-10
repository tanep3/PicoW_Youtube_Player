from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle,Circle,FancyArrowPatch
from matplotlib.font_manager import FontProperties
P=Path(__file__).resolve().parent
font=FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':font.get_name(),'font.size':10,'axes.titleweight':'bold'})
from matplotlib import font_manager
font_manager.fontManager.addfont(font.get_file())
fig=plt.figure(figsize=(15,10.6),facecolor='#f7fafc');gs=fig.add_gridspec(2,3,height_ratios=[1,1.1],hspace=.40,wspace=.20,left=.035,right=.97,top=.89,bottom=.08)
fig.text(.035,.956,'SLIM v3  組立・支持点ガイド',fontproperties=font,fontsize=23,color='#123c47',weight='bold')
fig.text(.035,.918,'模式図の左右・上下は正面から見た座標。LCDは「ボタン側へずらす → 左座の下を滑らせる → 四隅を押す」',fontproperties=font,fontsize=12,color='#526772')
BLUE='#127c93';ORANGE='#d97824';GREEN='#398965';PURPLE='#91539c'
def label(ax,x,y,text,fs=10,**kw):return ax.text(x,y,text,fontproperties=font,fontsize=fs,**kw)
def plan(ax,showbuttons=True):
 ax.set_aspect('equal');ax.set_xlim(-3,67);ax.set_ylim(36,-4);ax.axis('off');ax.add_patch(Rectangle((0,0),64,32,fill=False,lw=2,ec='#275964'));ax.add_patch(Rectangle((2.2,2.2),59.6,27.6,fill=False,lw=.8,ec='#bdcdd1'))
 for x,y in [(7,7.6),(7,19)]:ax.add_patch(Circle((x,y),1.6,color=BLUE));ax.add_patch(Circle((x,y),1.15,color='#f7fafc'))
 ax.add_patch(Rectangle((41.2,14.7),2.8,2.6,color=BLUE))
 if showbuttons:
  for x in [43,56]:
   for y in [10,22]:ax.add_patch(Rectangle((x-3,y-3),6,6,fill=False,ec='#9ba9af',ls='--'))
 label(ax,55,-1,'ボタン側',9,ha='center',color='#6d7f87')
def lcd(ax,shift=0,alpha=1,ls='-'):
 ax.add_patch(Rectangle((4+shift,4.1),30,24.02,lw=1.8,ec=GREEN,fc='#bed8be',alpha=alpha,ls=ls));ax.add_patch(Rectangle((4.9+shift,9.4),23,13.8,ec=GREEN,fc='#e5f2e7',alpha=alpha));ax.add_patch(Rectangle((34+shift,8.1),1,16,color='#d7b248',alpha=alpha));ax.add_patch(Rectangle((8.1+shift,25.6),21.8,2.52,color='#4c5962',alpha=alpha))
def arrow(ax,a,b,c=ORANGE):ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'-|>','lw':2,'color':c,'mutation_scale':15})
ax=fig.add_subplot(gs[0,0]);plan(ax);lcd(ax,5.5);ax.set_title('① ボタン側へ5.5 mmずらして入れる',fontproperties=font,fontsize=12,pad=16)
label(ax,24,15,'LCD',13,ha='center',color=GREEN);label(ax,22,34.5,'PCB左上 X9.5 / Y4.1',10,ha='center');arrow(ax,(7,31),(12.5,31));label(ax,10,-1,'左の高い座を避ける',9,ha='center',color=BLUE)
ax=fig.add_subplot(gs[0,1]);plan(ax);lcd(ax,5.5,.25,'--');lcd(ax,0,.65);arrow(ax,(31,16),(14,16));ax.set_title('② この高さで窓側へ5.5 mm滑らせる',fontproperties=font,fontsize=12,pad=16)
label(ax,25,34.5,'PCB前面 Z6.8 / 後面 Z10.0',10,ha='center');label(ax,23,38,'左座より下、ボタンレールより上',10,ha='center',color='#526772')
ax=fig.add_subplot(gs[0,2]);plan(ax);lcd(ax);ax.set_title('③ 位置を合わせ、PCB四隅を押す',fontproperties=font,fontsize=12,pad=16)
for x in [6.1,32]:
 for y in [4.1,28.12]:ax.add_patch(Circle((x,y),1.35,color=ORANGE));arrow(ax,(x,y-4 if y<10 else y+4),(x,y),ORANGE)
label(ax,20,16,'ガラスを押さない',10,ha='center',color='#a14a22');label(ax,24,34.5,'4か所の爪がPCB端に掛かる',10,ha='center');label(ax,24,38,'ヘッダ下 / FPC右を維持',10,ha='center',color='#526772')
ax=fig.add_subplot(gs[1,0:2]);plan(ax,False);ax.set_xlim(-3,94);ax.set_ylim(36,-6);ax.add_patch(Rectangle((5,2.8),51,21,fc='#d8ebe0',ec=GREEN,lw=1.5,alpha=.6))
for i,(x,y) in enumerate([(7,7.6),(7,19),(54,7.6),(54,19)]):
 ax.add_patch(Circle((x,y),1.6,fill=False,ec=PURPLE,lw=2));ax.add_patch(Circle((x,y),.825 if i in [0,3] else .65,color=PURPLE));label(ax,x,y-2.5,str(i+1),9,ha='center',color=PURPLE)
ax.add_patch(Rectangle((41.2,14.7),2.8,2.6,color=BLUE));ax.add_patch(Rectangle((1.65,9.5),8.55,7.6,fc='#879fa9',ec='#5d7680'));label(ax,6,14,'USB',9,ha='center',color='white')
ax.set_title('Picoは背面からまっすぐ。基板を左・上ガイドへ寄せ、蓋の4ピンを穴へ合わせる',fontproperties=font,fontsize=12,pad=18,loc='left')
label(ax,67,6,'本体：左2座＋中央支柱',10,color=BLUE);label(ax,67,12,'蓋：4穴のピン＋肩',10,color=PURPLE);label(ax,67,18,'①④ φ1.65 / ②③ φ1.30',10,color=PURPLE);label(ax,67,24,'穴 φ2.1（公式寸法）',10,color='#526772');label(ax,25,34.5,'スイッチ4個 → ボタン板2枚 → Pico → 蓋の順に組立',11,ha='center',color='#275964')
ax=fig.add_subplot(gs[1,2]);ax.set_xlim(-3,11);ax.set_ylim(14.0,23.0);ax.axis('off');ax.set_title('蓋ピンと押さえ肩：断面（模式図）',fontproperties=font,fontsize=12,pad=18)
ax.add_patch(Rectangle((-1,22),8,0.6,color=PURPLE,alpha=.45));ax.add_patch(Rectangle((1.4,17.92),3.2,4.08,color=PURPLE,alpha=.45));ax.add_patch(Rectangle((2.175,16.15),1.65,1.77,color=PURPLE));ax.add_patch(Rectangle((-1,16.8),2.95,1,fc='#a8d4b6',ec=GREEN));ax.add_patch(Rectangle((4.05,16.8),2.95,1,fc='#a8d4b6',ec=GREEN));ax.add_patch(Rectangle((1.4,15.5),.45,1.3,color=BLUE));ax.add_patch(Rectangle((4.15,15.5),.45,1.3,color=BLUE))
for z,t in [(22,'蓋内面 Z22'),(17.92,'肩 Z17.92'),(17.8,'PCB上面 Z17.8'),(16.8,'PCB下面 Z16.8')]:
 yy=22 if z==22 else 19.7 if z==17.92 else 18.6 if z==17.8 else 16.9
 ax.annotate(t,xy=(4.7,z),xytext=(7.2,yy),fontproperties=font,fontsize=9,arrowprops={'arrowstyle':'-','color':'#88999e'},va='center')
label(ax,-1,15.1,'公称隙間0.12 mm\n蓋の遊び込みで最大約0.24 mm\n強制的に基板を締め付けない',9,color='#526772',va='top')
fig.text(.035,.025,'寸法はmm。実ソケット・はんだ・配線は未実測部分あり。無理に押し込まず、ガラス/FPCに荷重を掛けない。実物の嵌合と爪の強度は試作で確認',fontproperties=font,fontsize=10,color='#9a5c27')
fig.savefig(P/'10_assembly_guide.png',dpi=180,facecolor=fig.get_facecolor());plt.close(fig)
