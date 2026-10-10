"""YouTube LCD case SLIM fit revision v3. 1 Blender unit = 1 mm. No originals changed.
Front coordinates: X right, Y down, +Z into enclosure. Front inner Z0, lid inner Z22.
Measurements versus assumptions are recorded in README_JA.md and validation.json.
Run: blender --background --python build_youtube_case_draft.py
"""
import bpy,bmesh,math,json,os
from pathlib import Path
from mathutils import Vector, Quaternion, Matrix
OUT=Path(__file__).resolve().parent
bpy.ops.wm.read_factory_settings(use_empty=True)
s=bpy.context.scene;s.name='01_ASSEMBLED_DRAFT_mm'
s.unit_settings.system='METRIC';s.unit_settings.scale_length=.001;s.unit_settings.length_unit='MILLIMETERS'
COL={}
for n in ['01_PRINT_Shell','02_PRINT_Removable_Lid','03_PRINT_Switch_Retainers','04_PRINT_LCD_Retainers','05_REF_LCD_Measured','06_REF_PicoW_Assumed','07_REF_4_Switches_Assumed','08_REF_Wires_Assumed','09_CLEARANCE_Hidden','10_PRESENTATION']:
 c=bpy.data.collections.new(n);s.collection.children.link(c);COL[n]=c
COL['09_CLEARANCE_Hidden'].hide_render=True;COL['09_CLEARANCE_Hidden'].hide_viewport=True

def mat(n,rgba,metal=0,rough=.5):
 m=bpy.data.materials.new(n);m.diffuse_color=rgba;m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=rgba;p.inputs['Metallic'].default_value=metal;p.inputs['Roughness'].default_value=rough;return m
TEAL=mat('PRINT / teal polymer',(.018,.31,.32,1));LID=mat('PRINT / lid teal',(.028,.38,.38,1));ORANGE=mat('PRINT / removable retainers',(.95,.38,.075,1));BLUE=mat('REF / measured LCD board',(.035,.12,.42,1));GREEN=mat('REF / Pico W assumed',(.035,.32,.17,1));DARK=mat('REF / black component',(.018,.024,.032,1));SCREEN=mat('REF / LCD glass',(.024,.066,.084,1),.3,.17);METAL=mat('REF / metal',(.53,.60,.64,1),.7,.26);GOLD=mat('REF / pins',(.64,.43,.095,1),.75);WHITE=mat('Graphic white',(.7,.86,.87,1));WIRE=mat('REF / wire assumed',(.93,.27,.085,1));PURPLE=mat('REF / clearance violet',(.65,.2,.7,.3))

def link(o,collection):
 for c in list(o.users_collection):c.objects.unlink(o)
 COL[collection].objects.link(o);return o

def finish(o,name,col,material=None,kind='PRINTABLE_DRAFT'):
 o.name=name;link(o,col)
 if material:o.data.materials.append(material)
 o['part_type']=kind;o['units']='mm';o['status']='DRAFT — NOT PRINT VALIDATED'
 return o

def repair(o):
 bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-5);bmesh.ops.dissolve_degenerate(bm,dist=1e-6,edges=list(bm.edges));edges=[e for e in bm.edges if e.is_boundary];vv=list(set(v for e in edges for v in e.verts))
 if len(edges)==3 and len(vv)==3 and (vv[1].co-vv[0].co).cross(vv[2].co-vv[0].co).length<1e-3:bmesh.ops.holes_fill(bm,edges=edges,sides=3)
 bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(o.data);bm.free();o.data.update()

def cube(n,lo,hi,col=None,material=None):
 bpy.ops.mesh.primitive_cube_add(size=1,location=[(a+b)/2 for a,b in zip(lo,hi)]);o=bpy.context.object;o.name=n;o.dimensions=[b-a for a,b in zip(lo,hi)];bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
 if col:finish(o,n,col,material)
 return o

def cylinder(n,center,r,depth,col=None,material=None,axis='Z'):
 rot={'Z':(0,0,0),'X':(0,math.pi/2,0),'Y':(math.pi/2,0,0)}[axis]
 bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=r,depth=depth,location=center,rotation=rot);o=bpy.context.object;o.name=n;bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
 if col:finish(o,n,col,material)
 return o

def prism(n,xy,z0,z1):
 N=len(xy);m=bpy.data.meshes.new(n);m.from_pydata([(x,y,z) for z in [z0,z1] for x,y in xy],[],[tuple(reversed(range(N))),tuple(range(N,N*2))]+[(i,(i+1)%N,(i+1)%N+N,i+N) for i in range(N)]);m.update();o=bpy.data.objects.new(n,m);s.collection.objects.link(o);repair(o);return o

def roundrect(n,x0,x1,y0,y1,z0,z1,r=2,wave=False):
 pts=[]
 # Clockwise in front view / mathematically CCW in XY.
 for cx,cy,a0 in [(x1-r,y1-r,0),(x0+r,y1-r,90),(x0+r,y0+r,180),(x1-r,y0+r,270)]:
  for j in range(13):
   a=math.radians(a0+j*90/12);p=(cx+r*math.cos(a),cy+r*math.sin(a));pts.append(p)
  # straight long horizontal wall, sample with real sinusoidal relief
  if wave and a0 in (0,180):
   start=x1-r if a0==0 else x0+r;end=x0+r if a0==0 else x1-r;yy=y1 if a0==0 else y0;sign=1 if a0==0 else -1
   count=round(abs(end-start)/.16)
   for k in range(1,count):
    x=start+(end-start)*k/count;t=min(abs(x-start),abs(x-end));taper=min(1,t/1.8);d=.35*(.5+.5*math.cos(2*math.pi*(x-3)/2.4))*taper;pts.append((x,yy+sign*d))
 return prism(n,pts,z0,z1)

def boolean(o,c,operation='UNION'):
 bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o;m=o.modifiers.new(operation,'BOOLEAN');m.operation=operation;m.solver='EXACT';m.object=c;bpy.ops.object.modifier_apply(modifier=m.name);cn=c.name;bpy.data.objects.remove(c,do_unlink=True);repair(o)
 bm=bmesh.new();bm.from_mesh(o.data);bad=sum(not e.is_manifold for e in bm.edges);bm.free()
 if bad:
  bm=bmesh.new();bm.from_mesh(o.data);print('BOOLEAN_BAD',o.name,cn,bad,[(e.is_boundary,[tuple(v.co) for v in e.verts]) for e in bm.edges if not e.is_manifold][:5],flush=True);bm.free()

def add(o,n,lo,hi):boolean(o,cube(n,lo,hi))
def cut(o,n,lo,hi):boolean(o,cube(n,lo,hi),'DIFFERENCE')
def tag(o,**kw):
 for k,v in kw.items():o[k]=v

def bevel(o,width=.18):
 m=o.modifiers.new('Small edge highlights (non-destructive)','BEVEL');m.width=width;m.segments=2;m.limit_method='ANGLE';m.angle_limit=.55
 m=o.modifiers.new('Weighted normals','WEIGHTED_NORMAL');m.keep_sharp=True

def textobj(n,body,loc,size=1,rot=(0,0,0),col='10_PRESENTATION',material=WHITE):
 cu=bpy.data.curves.new(n,'FONT');cu.body=body;cu.size=size;cu.extrude=0;cu.align_x='LEFT';o=bpy.data.objects.new(n,cu);COL[col].objects.link(o);o.location=loc;o.rotation_euler=rot;cu.materials.append(material);o['part_type']='REFERENCE_LABEL_NOT_PRINTED';return o

# SLIM layout: rigid electronic shapes are translated, never scaled.
W,H,D=64.,32.,22.
LCD_X,LCD_Y=4.,4.1
PICO_Y,PICO_Z=2.8,16.8
shell=roundrect('Shell',0,W,0,H,-2.4,D,3,True)
finish(shell,'PRINT_Shell_64x32_InternalDepth22','01_PRINT_Shell',TEAL)
boolean(shell,roundrect('Rear open cavity',2.2,W-2.2,2.2,H-2.2,0,D+5,.8),'DIFFERENCE')
cut(shell,'Measured LCD through aperture',(4.9,9.4,-4),(27.9,23.2,1))
# LCD measured envelope preserved. Four front-rooted elastic corner tabs.
# Internal isolation wells deepen root to -1.2 without breaking 1.2mm front skin.
for lo,hi in [((2.8,7.0,-.3),(3.8,25.2,3.1)),((9.0,2.8,-.3),(29.5,3.8,3.1)),((9,28.32,-.3),(29.5,29.4,3.1)),((34.2,4.1,-.3),(35.2,7.1,3.1)),((34.2,24.4,-.3),(35.2,28.1,3.1))]:
 add(shell,'LCD edge guide',lo,hi)
LCD_TABS=[]
for x in [6.1,32.0]:
 for edge in ['TOP','BOTTOM']:
  y0,y1=(3.10,3.80) if edge=='TOP' else (28.42,29.12)
  # Continuous gap outside beam and at both ends; free beam starts atZ-1.2.
  cut(shell,'LCD corner spring isolation well',(x-1.45,2.35 if edge=='TOP' else 28.15,-1.2),(x+1.45,4.02 if edge=='TOP' else 29.70,5.0))
  add(shell,'LCD elastic corner beam',(x-1.0,y0,-1.35),(x+1.0,y1,4.70))
  yz=[(3.10,3.35),(4.35,3.35),(4.35,3.65),(3.80,4.70),(3.10,4.70)] if edge=='TOP' else [(28.42,4.70),(27.87,3.65),(27.87,3.35),(29.12,3.35),(29.12,4.70)]
  hook=prism('LCD integral ramp and shoulder',yz,x-1.,x+1.)
  for v in hook.data.vertices:v.co=(v.co.z,v.co.x,v.co.y)
  repair(hook);boolean(shell,hook)
  LCD_TABS.append({'center_X':x,'edge':edge,'beam_thickness':.7,'beam_width':2.,'root_Z':-1.2,'shoulder_Z':3.35,'retention_overlap':.25,'required_deflection':.30})
# V8-derived switch architecture, flat exterior; two independent X slide plates.
rows=[10.,22.];centers=[(x,y) for y in rows for x in [43.,56.]]
for i,(x,y) in enumerate(centers,1):
 add(shell,f'Switch {i} guide cup',(x-4.1,y-4.1,-1.2),(x+4.1,y+4.1,3.15))
 cut(shell,f'Switch {i} 6.2 pocket',(x-3.1,y-3.1,-.8),(x+3.1,y+3.1,7.0))
 boolean(shell,cylinder('Stem diameter 4',(x,y,-1.5),2,5),'DIFFERENCE')
 for xx in [x-2.25,x+2.25]:
  for yy in [y-3.25,y+3.25]:cut(shell,'Assumed terminal escape',(xx-.55,yy-.65,1.8),(xx+.55,yy+.65,3.5))
retainers=[]
for idx,y in enumerate(rows,1):
 for xa,xb in [(37.6,39.7),(47.5,51.5),(59.35,61.7)]:
  for ya,yb in [(y-2.35,y-1.45),(y+1.45,y+2.35)]:add(shell,'Row rail support',(xa,ya,-.25),(xb,yb,6.05))
  add(shell,'Row lower datum',(xa,y-2.35,2.9),(xb,y+2.35,3.7))
  add(shell,'Row retaining roof',(xa,y-2.35,5.35),(xb,y+2.35,6.05))
 add(shell,'Row end stop',(61.0,y-2.35,-.25),(62.0,y+2.35,6.05))
 p=cube('Row retainer',(35.7,y-2.8,3.7),(37.3,y+2.8,5.1))
 add(p,'Bearing spine',(37.1,y-1.2,3.7),(60.8,y+1.2,5.1))
 wedge=prism('Lead-in wedge',[(60.0,3.68),(60.85,3.68),(60.85,4.15)],y-1.3,y+1.3)
 for v in wedge.data.vertices:v.co=(v.co.x,v.co.z,v.co.y)
 repair(wedge);boolean(p,wedge,'DIFFERENCE')
 finish(p,f'PRINT_Button_Row_{idx}_Slide_X_Positive','03_PRINT_Switch_Retainers',ORANGE)
 tag(p,insertion='From rear, slide +X before installing Pico',bearing_Z_mm=3.7,thickness_mm=1.4,clearance_to_switch_base_mm=.3,detent='Provisional friction fit, needs physical tuning')
 retainers.append(p)
# Pico W four official mounting holes. No upper clips obstruct the board.
PICO_HOLES=[(7.,7.6),(7.,19.),(54.,7.6),(54.,19.)]
# Two normal locators and two smaller floating locators avoid four-point overconstraint.
PIN_RADII=[.825,.65,.65,.825]
# The arms are fully connected wedges with rising undersides, not full-height posts.
def arm(n,start,end,w,zroot=7.4,zend=15.55):
 a=Vector(start);b=Vector(end);v=(b-a).normalized();q=Vector((-v.y,v.x))*w/2
 xy=[a+q,a-q,b-q,b+q]
 vs=[(pt.x,pt.y,zroot if i<2 else zend) for i,pt in enumerate(xy)]+[(pt.x,pt.y,16.8) for pt in xy]
 me=bpy.data.meshes.new(n);me.from_pydata(vs,[],[(3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]);me.update();o=bpy.data.objects.new(n,me);s.collection.objects.link(o);repair(o);boolean(shell,o)
for x,y in PICO_HOLES[:2]:
 arm('Pico left sloped wall arm',(1.9,y),(8.6,y),1.7,9.5,15.50)
 shoulder=cylinder('Pico left annular support',(x,y,16.125),1.6,1.35)
 boolean(shell,shoulder)
 boolean(shell,cylinder('Lid locator through clearance',(x,y,16.5),1.15,1.2),'DIFFERENCE')
# Central underside saddle is outside the LCD/FPC final footprint and between buttons.
# Entire pillar is right of staged LCD/FPC route; no leftward overhang.
add(shell,'Central Pico support pillar',(41.2,14.7,-.2),(44.0,17.3,16.8))

# Open, upright X/Y guides help align the board before the lid pins enter holes.
# They have no overhanging hooks; PCB and sockets still descend directly from rear.
for y in [7.6,19.]:add(shell,'Pico open left edge guide',(4.45,y-1.25,15.4),(4.80,y+1.25,18.2))
for x in [9.,50.]:add(shell,'Pico open upper edge guide',(x-2.,1.9,15.4),(x+2.,2.60,18.2))
# Rear-open USB slot enables direct -Z insertion of the projecting USB connector.
# Only the wall is cut: the internal support arms remain clear of the USB housing.
cut(shell,'Rear open USB assembly slot',(-2,7.3,13.6),(2.42,19.3,27))
# Four improved catches. Upper right catch relocated away from support-arm root.
SNAP_LOCS=[('LEFT',4.5),('LEFT',26.4),('RIGHT',11.5),('RIGHT',26.4)];SNAP_W=3.4
for side,y in SNAP_LOCS:
 if side=='LEFT':
  cut(shell,'Left tighter catch recess',(1.50,y-2.05,13.40),(2.25,y+2.05,15.12))
  cut(shell,'Left release tool port',(-1,y-.95,14.25),(2.25,y+.95,15.12))
 else:
  cut(shell,'Right tighter catch recess',(61.75,y-2.05,13.40),(62.50,y+2.05,15.12))
  cut(shell,'Right release tool port',(61.75,y-.95,14.25),(65,y+.95,15.12))
tag(shell,front_inner_Z_mm=0.,closed_lid_inner_Z_mm=22.,clear_internal_depth_mm=22.,front_thickness_mm=2.4,wave_relief_mm=.35,wave_pitch_mm=2.4,window_measured_mm='23 x 13.8',window_front_top_left_mm='PCB +X0.9, +Y5.3',button_seat_from_front_exterior_mm=1.6,LCD_retention='Four integral corner elastic tabs; no separate bars',Pico_retention='Two left hole seats and central non-antenna pillar; four locating pins and shoulders on lid; no upper clips')
lid=roundrect('Lid',0,W,0,H,D,D+2.4,3,True);finish(lid,'PRINT_Lid_Flexure_Snaps_No_Wiring','02_PRINT_Removable_Lid',LID)
plug=roundrect('Closer locating ring',2.35,W-2.35,2.35,H-2.35,20.,22.05,.8)
boolean(plug,roundrect('Ring inner hollow',3.55,W-3.55,3.55,H-3.55,19.,23.,.4),'DIFFERENCE');boolean(lid,plug)
cut(lid,'USB locating ring relief',(1.5,8.9,19.5),(4.2,17.7,21.15))
for side,y in SNAP_LOCS:
 x0,x1=(2.45,3.35) if side=='LEFT' else (60.65,61.55)
 cut(lid,'Tongue radial isolation',(1.4 if side=='LEFT' else 60.,y-SNAP_W/2-.65,12.5),(4.05 if side=='LEFT' else 62.6,y+SNAP_W/2+.65,21.5))
 add(lid,'Longer cantilever tongue',(x0,y-SNAP_W/2,13.),(x1,y+SNAP_W/2,22.05))
 xz=[(2.45,13.),(3.35,13.),(3.35,15.),(1.8,15.),(1.8,14.4)] if side=='LEFT' else [(60.65,13.),(61.55,13.),(62.2,14.4),(62.2,15.),(60.65,15.)]
 hook=prism('Stronger tapered catch',xz,y-SNAP_W/2,y+SNAP_W/2)
 for v in hook.data.vertices:v.co=(v.co.x,v.co.z,v.co.y)
 repair(hook);boolean(lid,hook)
for i,(x,y) in enumerate(PICO_HOLES):
 boss=cylinder('Pico lid shoulder',(x,y,(17.92+22.08)/2),1.6,22.08-17.92);boolean(lid,boss)
 boolean(lid,cylinder('Lid hole locating pin',(x,y,(16.55+18.05)/2),PIN_RADII[i],18.05-16.55))
 bpy.ops.mesh.primitive_cone_add(vertices=48,radius1=PIN_RADII[i]-.22,radius2=PIN_RADII[i],depth=.4,location=(x,y,16.35))
 cone=bpy.context.object;bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);boolean(lid,cone)
tag(lid,inner_Z_mm=22.,outer_Z_mm=24.4,thickness_mm=2.4,detachable=True,contains_wires=False,closure='Four stronger extended flexures, tighter recesses/ring and release ports; trial fit required',snap_overall_length_mm=9.,snap_isolated_flexure_length_mm=8.5,snap_catch_lever_length_mm=6.5,snap_beam_thickness_mm=.9,snap_required_deflection_mm=.4,snap_catch_axial_clearance_mm=.12,Pico_stop_axial_clearance_mm=.12)
# Reference LCD measured at full size, solely translated up by 2.9 mm from v1.
lcd=cube('LCD measured PCB',(4,4.1,0),(34,28.12,3.2),'05_REF_LCD_Measured',BLUE);tag(lcd,measurement='OWNER MEASURED',pcb_mm='30 x 24.02 x 3.2',header_orientation='DOWN in front view')
glass=cube('LCD measured visible rectangle',(4.9,9.4,-.12),(27.9,23.2,0),'05_REF_LCD_Measured',SCREEN);glass['measurement']='23 x 13.8, top-left PCB+(0.9,5.3)'
flex=cube('FPC right protrusion 1mm',(34,8.1,.45),(35,24.1,2.2),'05_REF_LCD_Measured',GOLD);tag(flex,measurement='Only 1mm right protrusion confirmed; Y/Z assumed')
header=cube('LCD downward header socket ASSUMED',(8.1,25.6,3.2),(29.9,28.12,11.2),'05_REF_LCD_Measured',DARK);header['measurement']='21.8 x 2.52 x 8 mm connector ASSUMED'
for i in range(8):cylinder('LCD pin ASSUMED',(10.1+2.54*i,26.86,7.3),.29,8.2,'05_REF_LCD_Measured',GOLD)
play=prism('Neutral video play placeholder',[(14,12.8),(14,19.8),(20,16.3)],-.14,-.13);finish(play,'REF_Video_Play_Placeholder','05_REF_LCD_Measured',WHITE,'REFERENCE_GRAPHIC_NOT_PRINTED')
pico=cube('Pico W board 51x21 official',(5,2.8,16.8),(56,23.8,17.8),'06_REF_PicoW_Assumed',GREEN)
for x,y in PICO_HOLES:boolean(pico,cylinder('Official mounting hole',(x,y,17.3),1.05,2.0),'DIFFERENCE')
tag(pico,measurement='Official 51 x 21 x 1 mm; 4 holes diameter2.1+/-0.05 on47x11.4 pattern',orientation='USB LEFT, antenna RIGHT')
usb=cube('Micro USB ASSUMED',(1.65,9.5,17.8),(10.2,17.1,20.6),'06_REF_PicoW_Assumed',METAL)
shield=cube('RF shield ASSUMED',(32,6.3,17.8),(43.8,20.3,21.0),'06_REF_PicoW_Assumed',METAL)
chip=cube('RP2040 ASSUMED',(20,8.3,17.8),(26,14.3,19.05),'06_REF_PicoW_Assumed',DARK)
sockets=[]
for y in [4.41,22.19]:
 so=cube('Pico 20 pin socket ASSUMED',(5.87,y-1.3,8.3),(55.13,y+1.3,16.6),'06_REF_PicoW_Assumed',DARK);so['measurement']='49.26 x2.6 x8.3 socket envelope ASSUMED; row/pin axes from official board';sockets.append(so)
 for i in range(20):cylinder('Pico header contact ASSUMED',(6.37+2.54*i,y,17.2),.31,2.5,'06_REF_PicoW_Assumed',GOLD)
textobj('Pico reference label','PICO W / REF',(34,11.3,21.03),1.3,(0,0,0),'06_REF_PicoW_Assumed',DARK)
switches=[]
for i,(x,y) in enumerate(centers,1):
 sw=cube('Tact body',(x-3,y-3,-.8),(x+3,y+3,3.4),'07_REF_4_Switches_Assumed',DARK);sw.name=f'REF_Switch_{i}_Body_ASSUMED_6x6x4p2';switches.append(sw)
 cube('Switch metal face',(x-2.9,y-2.9,-.8),(x+2.9,y+2.9,-.7),'07_REF_4_Switches_Assumed',METAL)
 cylinder(f'REF_Switch_{i}_Existing_Long_Actuator',(x,y,-2.18),1.75,2.84,'07_REF_4_Switches_Assumed',DARK)
 for xx in [x-2.25,x+2.25]:
  for yy in [y-3.25,y+3.25]:cube('Switch terminal ASSUMED',(xx-.22,yy-.22,2.9),(xx+.22,yy+.22,6.9),'07_REF_4_Switches_Assumed',GOLD)
 tag(sw,body_dimensions='6 x 6 x 4.2 inferred V8, verify actual switches',stem_diameter_assumed_mm=3.5,stem_projection_assumed_mm=1.2)
def wire(n,pts,r,material):
 cu=bpy.data.curves.new(n,'CURVE');cu.dimensions='3D';cu.bevel_depth=r;cu.bevel_resolution=3;sp=cu.splines.new('BEZIER');sp.bezier_points.add(len(pts)-1)
 for p,co in zip(sp.bezier_points,pts):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
 o=bpy.data.objects.new(n,cu);COL['08_REF_Wires_Assumed'].objects.link(o);cu.materials.append(material);o['part_type']='ASSUMED_ROUTING_NOT_PRINTED';return o
wire('LCD cable schematic',[(19,26.86,11.4),(22,28.8,12.1),(30,28.6,12.5),(37,26.1,11.8),(41,23.9,6.5)],.40,WIRE)
for y in rows:wire('Button wiring schematic',[(56,y+3.25,6.8),(59.6,y+3.6,8.8),(59.6,27.3,11.4),(49,26.8,11.5),(48,23.9,6.5)],.28,WIRE)
for n,lo,hi in [('DATUM_22mm_Usable_Depth',(2.2,2.2,0),(61.8,29.8,22)),('KEEP_FPC_Right',(34,7.1,0),(36,25.1,5)),('ASSUMED_USB_Cable_Hood_OUTSIDE',(-14,7.3,15.2),(-.5,19.3,23.2)),('Antenna_Region_Reference',(44.5,8.8,17.8),(56,17.8,21.5))]:
 o=cube(n,lo,hi,'09_CLEARANCE_Hidden',PURPLE);o.display_type='WIRE';o.hide_render=True;o['part_type']='CLEARANCE_NOT_PRINTED'
info=bpy.data.texts.new('READ_ME_v3.txt');info.write('SLIM v3 TRIAL FIT REVISION. Units mm. Front inner Z0, lid inner Z22, outer nominal64x32x26.8. Four printed parts: shell, lid, two button sliders. Integral LCD tabs. Pico on two left seats and central pillar; four lid hole pins and shoulder stops retain PCB. No upper Pico clips. USB slot open to rear for assembly. Read README_JA.md and audits; actual hardware and printed snap forces are not verified. Master scene01_ASSEMBLED_DRAFT_mm. Display scenes are copies, not master geometry.')
# Basic mesh and intersection audit. These are CAD envelope checks, not physical validation.
def stats(o):
 bm=bmesh.new();bm.from_mesh(o.data);v=[o.matrix_world@p.co for p in bm.verts];seen=set(bm.verts);comp=0
 while seen:
  comp+=1;todo=[seen.pop()]
  while todo:
   p=todo.pop()
   for e in p.link_edges:
    q=e.other_vert(p)
    if q in seen:seen.remove(q);todo.append(q)
 r={'vertices':len(v),'faces':len(bm.faces),'nonmanifold_edges':sum(not e.is_manifold for e in bm.edges),'boundary_edges':sum(e.is_boundary for e in bm.edges),'connected_components':comp,'volume_mm3':bm.calc_volume(signed=True),'bounds_mm':[[min(p[k] for p in v) for k in range(3)],[max(p[k] for p in v) for k in range(3)]]};bm.free();return r

def intersection_volume(a,b):
 # Copy source mesh with no optional bevel modifiers and exact Boolean intersection.
 obj=bpy.data.objects.new('_AUDIT_'+a.name,a.data.copy());s.collection.objects.link(obj);obj.matrix_world=a.matrix_world.copy()
 mod=obj.modifiers.new('INTERSECTION','BOOLEAN');mod.operation='INTERSECT';mod.solver='EXACT';mod.object=b
 bpy.context.view_layer.objects.active=obj;obj.select_set(True);bpy.ops.object.modifier_apply(modifier=mod.name)
 bm=bmesh.new();bm.from_mesh(obj.data);vol=abs(bm.calc_volume(signed=True));bm.free();bpy.data.objects.remove(obj,do_unlink=True);return round(vol,8)
prints=[shell,lid,*retainers]
# Eliminate Boolean floating-point crumbs before STL triangulation/plate transforms.
# Maximum coordinate rounding is0.00005mm, far below printer resolution.
for o in prints:
 bm=bmesh.new();bm.from_mesh(o.data)
 for v in bm.verts:
  for axis in range(3):v.co[axis]=round(v.co[axis],4)
 bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-5)
 bmesh.ops.triangulate(bm,faces=list(bm.faces),quad_method='BEAUTY',ngon_method='BEAUTY')
 bmesh.ops.dissolve_degenerate(bm,dist=1e-5,edges=list(bm.edges))
 bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(o.data);bm.free();o.data.update()
audit={}
pairs=[(shell,lid,'closed_shell_vs_lid'),(shell,lcd,'shell_vs_LCD_PCB'),(shell,header,'shell_vs_LCD_header'),(shell,flex,'shell_vs_FPC'),(shell,pico,'shell_vs_Pico_PCB'),(shell,usb,'shell_vs_USB'),(shell,shield,'shell_vs_shield'),(lid,pico,'lid_vs_Pico_PCB'),(lid,shield,'lid_vs_shield'),(lid,usb,'lid_vs_USB'),(lid,header,'lid_vs_LCD_header')]
pairs +=[(shell,x,'shell_vs_'+x.name) for x in sockets+retainers+switches]
pairs +=[(lid,x,'lid_vs_'+x.name) for x in sockets]
pairs +=[(header,x,'LCD_header_vs_'+x.name) for x in sockets]
pairs +=[(x,y,x.name+'_vs_'+y.name) for x in retainers for y in sockets]
for a,b,label in pairs:audit[label]=intersection_volume(a,b)
report={'status':'V3_TRIAL_PRINT_NOT_PHYSICALLY_VALIDATED','coordinate_system':'+X right,+Y down in front view,+Z rearward','internal_depth_mm':22.,'outer_nominal_mm':[64,32,26.8],'outer_max_wave_mm':[64,32.7,26.8],'measured_LCD':{'board':[30,24.02,3.2],'origin':[4,4.1,0],'window':[23,13.8],'window_offset':[.9,5.3],'FPC_protrusion_right':1},'LCD_tabs':LCD_TABS,'Pico':{'official_source':'https://datasheets.raspberrypi.com/picow/pico-w-datasheet.pdf','board':[51,21,1],'origin':[5,2.8,16.8],'hole_centers':PICO_HOLES,'hole_diameter_nominal':2.1,'hole_diameter_tolerance':.05,'pin_diameters':[r*2 for r in PIN_RADII],'shoulder_diameter':3.2,'lid_boss_outer_diameter':3.2,'case_left_pin_clearance_diameter':2.3,'lid_stop_clearance_Z':.12,'socket_envelope_ASSUMED':[49.26,2.6,8.3],'socket_row_centers_Y':[4.41,22.19]},'fit_mm':{'socket_to_button_rail':2.25,'shield_to_lid':1.,'lid_ring_side_clearance':.15,'lid_catch_wall_engagement':.4,'lid_catch_axial_play':.12,'LCD_catch_overlap':.25,'LCD_catch_axial_play':.15,'LCD_tab_side_travel':.3},'elastic_estimates':{'formula':'nominal small-deflection cantilever root strain=1.5*t*delta/L^2; not FEA or print validation','LCD_percent':1.5*.7*.3/4.55**2*100,'lid_percent':1.5*.9*.4/6.5**2*100},'intersection_volumes_mm3':audit,'print_candidates':{o.name:stats(o) for o in prints},'limitations':['Real LCD corner contact edges and glass assembly require visual hardware verification','Socket body/solder/USB/switch envelopes remain assumed; wired assembly not proven','Printed flexure forces, fatigue and dimensional fit require trial print; PETG preferred for spring trial','No assertion of RF performance; localized hole supports minimize but do not eliminate antenna dielectric impact']}
report['buttons']={'count': 4, 'centers_XY': [[43, 10], [56, 10], [43, 22], [56, 22]], 'pocket_mm': 6.2, 'stem_hole_diameter_mm': 4.0, 'seat_depth_from_front_exterior_mm': 1.6, 'retainer_thickness_mm': 1.4, 'retainer_switch_gap_mm': 0.3, 'unchanged_from_v2': True}
report['source_numeric_cleanup']={'max_coordinate_rounding_mm': 5e-05, 'mesh_cleanup': 'quantize coordinates0.0001mm then remove degenerate triangles before base-mesh validation and STL export'}
json.dump(report,open(OUT/'validation.json','w'),ensure_ascii=False,indent=2)
for o in prints:
 st=report['print_candidates'][o.name];print('PRINT_STATS',o.name,st,flush=True);assert st['nonmanifold_edges']==0 and st['connected_components']==1 and st['volume_mm3']>0,o.name
print('INTERSECTIONS',audit,flush=True)
for label,vol in audit.items():assert vol<.0001,(label,vol)
for o in prints:bevel(o,.07)
for col in ['05_REF_LCD_Measured','06_REF_PicoW_Assumed','07_REF_4_Switches_Assumed']:
 for o in COL[col].objects:
  if o.type=='MESH':bevel(o,.04)
# Render genuine Blender geometry. All view orientation is kept from reviewed v1.
s.render.engine='BLENDER_WORKBENCH';s.display.shading.light='STUDIO';s.display.shading.studiolight_rotate_z=.45;s.display.shading.studio_light='paint.sl';s.display.shading.color_type='MATERIAL';s.display.shading.show_shadows=True;s.display.shading.show_cavity=True;s.display.shading.cavity_type='BOTH';s.display.shading.curvature_ridge_factor=1.25;s.display.shading.curvature_valley_factor=1.;s.display.shading.show_specular_highlight=True;s.display.shading.background_type='WORLD';s.world=bpy.data.worlds.new('Draft Studio');s.world.color=(.87,.89,.90);s.render.film_transparent=False;s.render.resolution_x=1600;s.render.resolution_y=1100;s.render.resolution_percentage=100;s.view_settings.view_transform='Standard'
bpy.ops.object.camera_add();cam=bpy.context.object;finish(cam,'Review_Camera','10_PRESENTATION');cam.data.type='ORTHO';s.camera=cam

def camera(scene,pos,target,scale):
 cam=scene.camera;cam.location=pos;direction=Vector(target)-cam.location;d=direction.normalized();right=d.cross(Vector((0,-1,0))).normalized();up=right.cross(d);q=Matrix((right,up,-d)).transposed().to_quaternion() if pos[2]<target[2] else direction.to_track_quat('-Z','Y');cam.rotation_euler=q.to_euler();cam.data.ortho_scale=scale

def render(scene,fn,pos,target,scale):
 bpy.context.window.scene=scene;camera(scene,pos,target,scale);scene.render.filepath=str(OUT/fn);bpy.ops.render.render(write_still=True) if not os.environ.get('SKIP_RENDERS') else None

def duplicate_scene(name):
 bpy.context.window.scene=s;bpy.ops.scene.new(type='FULL_COPY');ns=bpy.context.scene;ns.name=name;return ns
camera(s,(-45,-60,-110),(32,16,10),112)
for sc in bpy.data.screens:
 for a in sc.areas:
  if a.type=='VIEW_3D':
   a.spaces.active.shading.type='SOLID';a.spaces.active.shading.color_type='MATERIAL';a.spaces.active.region_3d.view_distance=115;a.spaces.active.region_3d.view_location=(32,16,10);a.spaces.active.region_3d.view_rotation=cam.rotation_euler.to_quaternion();a.spaces.active.region_3d.view_perspective='ORTHO'
bpy.ops.object.select_all(action='DESELECT');shell.select_set(True);bpy.context.view_layer.objects.active=shell
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'YouTube_LCD_Case_SLIM_Fit_v3.blend'))
render(s,'01_front_3quarter.png',(-45,-60,-110),(32,16,10),112)
cam.location=(32,16,-120);cam.rotation_euler=(math.pi,0,0);cam.data.ortho_scale=75;s.render.filepath=str(OUT/'02_front_orthographic.png');bpy.ops.render.render(write_still=True) if not os.environ.get('SKIP_RENDERS') else None
render(s,'03_back_3quarter.png',(104,86,115),(32,16,10),104)
ex=duplicate_scene('02_EXPLODED_DISPLAY_ONLY')
for o in ex.objects:
 if o.name.startswith('PRINT_Lid'):o.location.z+=43
 elif o.name.startswith('PRINT_Button_Row'):o.location.z+=11
 
 elif any('06_REF_Pico' in c.name for c in o.users_collection):o.location.z+=28
 elif any('08_REF_Wires' in c.name for c in o.users_collection):o.hide_render=True;o.hide_set(True)
 elif any('07_REF_4_Switch' in c.name for c in o.users_collection):o.location.z+=3
 elif any('05_REF_LCD' in c.name for c in o.users_collection):o.location.z+=3
render(ex,'05_exploded.png',(108,95,145),(32,16,33),160)
cutscene=duplicate_scene('03_CUTAWAY_DISPLAY_ONLY')
for o in list(cutscene.objects):
 if o.name.startswith('PRINT_Lid'):o.hide_render=True;o.hide_set(True)
 elif o.name.startswith('PRINT_Shell'):
  cutter=cube('Cutaway presentation removal',(-2,16,-3),(67,36,28));boolean(o,cutter,'DIFFERENCE');o.name='DISPLAY_ONLY_Cutaway_Shell'
render(cutscene,'04_cutaway.png',(91,101,92),(32,14,9),104)
rear=duplicate_scene('04_REAR_OPEN_INSPECTION')
for o in rear.objects:
 if o.name.startswith('PRINT_Lid'):o.hide_render=True;o.hide_set(True)
render(rear,'06_rear_open.png',(94,96,118),(32,16,9),103)
# Lid underside detail: actual tongues and release mechanism, other models hidden.
lidscene=duplicate_scene('05_LID_FLEXURE_INSPECTION')
for o in lidscene.objects:
 if o.type!='CAMERA' and not o.name.startswith('PRINT_Lid'):o.hide_render=True;o.hide_set(True)
render(lidscene,'07_lid_snap_detail.png',(-30,-45,-85),(32,16,18),100)
bpy.context.window.scene=s;camera(s,(-45,-60,-110),(32,16,10),112)
bpy.ops.object.select_all(action='DESELECT');shell.select_set(True);bpy.context.view_layer.objects.active=shell
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'YouTube_LCD_Case_SLIM_Fit_v3.blend'))
# Additional clean internal mechanics inspection with LCD/Pico hidden.
mechanical=duplicate_scene('06_INTERNAL_RETENTION_INSPECTION')
for o in mechanical.objects:
 if o.type!='CAMERA' and not o.name.startswith('PRINT_Shell'):o.hide_render=True;o.hide_set(True)
render(mechanical,'08_integral_tabs_and_hole_seats.png',(82,82,103),(30,15,8),99)
render(mechanical,'09_LCD_corner_snap_detail.png',(43,54,65),(19,16,2.7),47)
bpy.context.window.scene=s
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'YouTube_LCD_Case_SLIM_Fit_v3.blend'))
print('DONE',str(OUT),flush=True)
