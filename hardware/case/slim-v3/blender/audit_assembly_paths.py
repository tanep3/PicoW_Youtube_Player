"""Independent rigid-envelope and continuous translation sweep audit. Never physical validation."""
import bpy,bmesh,json,sys,math,hashlib
from pathlib import Path
from mathutils import Vector
args=sys.argv[sys.argv.index('--')+1:]
src=Path(args[0]);out=Path(args[1])
bpy.ops.wm.open_mainfile(filepath=str(src));s=next(sc for sc in bpy.data.scenes if sc.name.startswith('01_ASSEMBLED'));bpy.context.window.scene=s
base=list(s.objects)
for o in base:
 for m in list(o.modifiers):o.modifiers.remove(m)
prints=[o for o in base if o.type=='MESH' and o.name.startswith('PRINT_')]
shell=next(o for o in prints if o.name.startswith('PRINT_Shell'));lid=next(o for o in prints if o.name.startswith('PRINT_Lid'))
def bounds(o):
 vv=[o.matrix_world@v.co for v in o.data.vertices]
 return [[min(p[k] for p in vv) for k in range(3)],[max(p[k] for p in vv) for k in range(3)]] if vv else None
def stat(o):
 bm=bmesh.new();bm.from_mesh(o.data);bm.transform(o.matrix_world);todo=set(bm.verts);cc=0
 while todo:
  cc+=1;work=[todo.pop()]
  while work:
   v=work.pop()
   for e in v.link_edges:
    w=e.other_vert(v)
    if w in todo:todo.remove(w);work.append(w)
 z={'bounds_mm':bounds(o),'nonmanifold_edges':sum(not e.is_manifold for e in bm.edges),'components':cc,'volume_mm3':bm.calc_volume(signed=True),'vertices':len(bm.verts),'faces':len(bm.faces)};bm.free();return z
def overlap(a,b):
 A=bounds(a);B=bounds(b)
 return A and B and all(min(A[1][k],B[1][k])-max(A[0][k],B[0][k])>1e-5 for k in range(3))
def inter(a,b):
 if not overlap(a,b):return {'volume_mm3':0,'bounds_mm':None}
 cp=a.copy();cp.data=a.data.copy();s.collection.objects.link(cp)
 bpy.ops.object.select_all(action='DESELECT');cp.select_set(True);bpy.context.view_layer.objects.active=cp
 m=cp.modifiers.new('Independent sweep check','BOOLEAN');m.operation='INTERSECT';m.solver='EXACT';m.object=b;bpy.ops.object.modifier_apply(modifier=m.name)
 bm=bmesh.new();bm.from_mesh(cp.data);v=abs(bm.calc_volume(signed=True));bm.free();r={'volume_mm3':round(v,6),'bounds_mm':bounds(cp)}
 if v>1e-4:
  bm=bmesh.new();bm.from_mesh(cp.data);todo=set(bm.verts);parts=[]
  while todo:
   work=[todo.pop()];verts=[]
   while work:
    p=work.pop();verts.append(cp.matrix_world@p.co)
    for e in p.link_edges:
     q=e.other_vert(p)
     if q in todo:todo.remove(q);work.append(q)
   parts.append([[min(p[k] for p in verts) for k in range(3)],[max(p[k] for p in verts) for k in range(3)]])
  r['overlap_component_bounds_mm']=parts;bm.free()
 bpy.data.objects.remove(cp,do_unlink=True);return r
def cube(n,lo,hi):
 bpy.ops.mesh.primitive_cube_add(size=1,location=[(a+b)/2 for a,b in zip(lo,hi)]);o=bpy.context.object;o.name=n;o.dimensions=[b-a for a,b in zip(lo,hi)];bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);return o
def bbox_sweep(o,start,end):
 bb=bounds(o);lo=[bb[0][k]+min(start[k],end[k]) for k in range(3)];hi=[bb[1][k]+max(start[k],end[k]) for k in range(3)];return cube('_Swept_'+o.name,lo,hi)
def convex_sweep(o,start,end):
 bm=bmesh.new()
 for shift in [start,end]:
  for v in o.data.vertices:bm.verts.new(o.matrix_world@v.co+Vector(shift))
 bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
 bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
 bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));m=bpy.data.meshes.new('_ConvexSweep');bm.to_mesh(m);bm.free();cp=bpy.data.objects.new('_Swept_'+o.name,m);s.collection.objects.link(cp);return cp
def vertical_prism_sweep(o,shift=30):
 cp=o.copy();cp.data=o.data.copy();s.collection.objects.link(cp);bb=bounds(o);zmax=bb[1][2]
 for v in cp.data.vertices:
  w=cp.matrix_world@v.co
  if abs(w.z-zmax)<1e-4:v.co=cp.matrix_world.inverted()@Vector((w.x,w.y,w.z+shift))
 return cp
refs=[o for o in base if o.type=='MESH' and any(o.name.startswith(p) for p in ['LCD measured PCB','LCD measured visible','LCD pin ASSUMED','LCD downward header','FPC right protrusion','Pico W board','Pico 20 pin socket','Pico header contact','RF shield','Micro USB','RP2040','REF_Switch_','Switch terminal','Switch metal face'])]
lcdrefs=[o for o in refs if any(o.name.startswith(p) for p in ['LCD measured PCB','LCD measured visible','LCD pin ASSUMED','LCD downward header','FPC right protrusion'])]
picorefs=[o for o in refs if any(o.name.startswith(p) for p in ['Pico W board','Pico 20 pin socket','Pico header contact','RF shield','Micro USB','RP2040'])]
r={'source':str(src),'sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'status':'GEOMETRIC_MODEL_ONLY_NOT_PHYSICAL_VERIFICATION','scene':s.name,'print_mesh':{o.name:stat(o) for o in prints},'reference_bounds':{o.name:bounds(o) for o in refs},'closed_intersections':{},'lcd_continuous_translation_sweeps':{},'pico_continuous_vertical_sweeps':{},'button_retainer_slide_sweeps':{},'switch_insertion_sweeps':{},'limitations':['Only explicit rigid reference envelopes modeled; no physical FDM tolerances, friction, material/fatigue or actuation forces established.','Sweeps are continuous solids for axis-aligned translating box/prism envelopes, not just sampled endpoints.','LCD final press intentionally crosses elastic noses; any such intersections require localized flex/clearance analysis.','No claim actual hardware/socket/wire/solder dimensions are verified.']}
for i,a in enumerate(prints):
 for b in prints[i+1:]+refs:
  if overlap(a,b):
   x=inter(a,b);r['closed_intersections'][a.name+' / '+b.name]=x
   print('CLOSED',a.name,b.name,x,flush=True)
for label,start,end in [('01_shifted_right_vertical_entry',(5.5,0,35),(5.5,0,6.8)),('02_slide_left_below_seats',(5.5,0,6.8),(0,0,6.8)),('03_final_press_into_snaps',(0,0,6.8),(0,0,0))]:
 r['lcd_continuous_translation_sweeps'][label]={}
 for ref in lcdrefs:
  sweep=bbox_sweep(ref,start,end);x=inter(sweep,shell);r['lcd_continuous_translation_sweeps'][label][ref.name]=x;print('LCD_SWEEP',label,ref.name,x,flush=True);bpy.data.objects.remove(sweep,do_unlink=True)
for ref in picorefs:
 if ref.name.startswith('Pico W board'):sweep=vertical_prism_sweep(ref)
 else:sweep=bbox_sweep(ref,(0,0,30),(0,0,0))
 r['pico_continuous_vertical_sweeps'][ref.name]={}
 for obstacle in [shell]+lcdrefs+[o for o in prints if o not in [shell,lid]]:
  if overlap(sweep,obstacle):
   x=inter(sweep,obstacle);r['pico_continuous_vertical_sweeps'][ref.name][obstacle.name]=x;print('PICO_SWEEP',ref.name,obstacle.name,x,flush=True)
 bpy.data.objects.remove(sweep,do_unlink=True)
# Conservative constituent-box sweep for the inherited two-piece button-row plate geometry.
# Handle is full width only at left end; sweeping whole-object AABB would falsely hit the rails.
for plate in [o for o in prints if o.name.startswith('PRINT_Button_Row')]:
 bb=bounds(plate);yc=(bb[0][1]+bb[1][1])/2;z0,z1=bb[0][2],bb[1][2]
 parts=[('handle',[bb[0][0]-25,bb[0][1],z0],[bb[0][0]+1.6,bb[1][1],z1]),('spine',[bb[0][0]+1.4-25,yc-1.2,z0],[bb[1][0],yc+1.2,z1])]
 r['button_retainer_slide_sweeps'][plate.name]={}
 for part,lo,hi in parts:
  sweep=cube('_Button_slide_'+part,lo,hi)
  for obstacle in [shell]+lcdrefs:
   if overlap(sweep,obstacle):
    x=inter(sweep,obstacle);r['button_retainer_slide_sweeps'][plate.name][part+' / '+obstacle.name]=x;print('BUTTON_SWEEP',plate.name,part,obstacle.name,x,flush=True)
  bpy.data.objects.remove(sweep,do_unlink=True)
switchrefs=[o for o in base if o.type=='MESH' and any(c.name.startswith('07_REF_4_Switches') for c in o.users_collection)]
for ref in switchrefs:
 bb=bounds(ref);xc=(bb[0][0]+bb[1][0])/2
 stages=[('direct_drop',(0,0,30),(0,0,0))]
 r['switch_insertion_sweeps'][ref.name]={}
 for label,start,end in stages:
  sweep=convex_sweep(ref,start,end)
  for obstacle in [shell]+lcdrefs:
   if overlap(sweep,obstacle):
    x=inter(sweep,obstacle);r['switch_insertion_sweeps'][ref.name][label+' / '+obstacle.name]=x
    if x['volume_mm3']>1e-4:print('SWITCH_SWEEP_POSITIVE',ref.name,label,obstacle.name,x,flush=True)
  bpy.data.objects.remove(sweep,do_unlink=True)
r['unexpected_closed_positive']={k:v for k,v in r['closed_intersections'].items() if v['volume_mm3']>1e-4}
out.write_text(json.dumps(r,ensure_ascii=False,indent=2));print('AUDIT_SAVED',out,flush=True)
