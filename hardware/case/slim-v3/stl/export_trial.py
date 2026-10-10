"""Export approved SLIM v3 base geometry; rigid transforms only; STL coordinates are mm."""
import bpy,bmesh,json,struct,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
OUT=Path(__file__).resolve().parent
SOURCE=OUT.parent/'youtube_case_draft_v3/YouTube_LCD_Case_SLIM_Fit_v3.blend'
source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
s=bpy.data.scenes['01_ASSEMBLED_DRAFT_mm'];bpy.context.window.scene=s
parts=[
('01_shell.stl','PRINT_Shell_64x32_InternalDepth22',(20,10),False,'Front exterior on bed; open rear faces up'),
('02_lid.stl','PRINT_Lid_Flexure_Snaps_No_Wiring',(96,10),True,'Flat rear exterior on bed; locating ring and tongues face up'),
('03_button_row_1.stl','PRINT_Button_Row_1_Slide_X_Positive',(44,61),False,'Broad flat face on bed'),
('04_button_row_2.stl','PRINT_Button_Row_2_Slide_X_Positive',(81,61),False,'Broad flat face on bed')]
assert len([o for o in s.objects if o.type=='MESH' and o.name.startswith('PRINT_')])==4
report={'source_blend':SOURCE.name,'source_blend_sha256':source_hash,'scene':s.name,'source_blender_unit_scale':s.unit_settings.scale_length,'coordinate_convention':'1 stored Blender coordinate unit = 1 mm; no scene-unit factor applied','geometry':'Validated trial base meshes; visual-only bevel and weighted-normal modifiers excluded','geometry_changes':'None; triangulation and rigid print-orientation/placement transforms only','scale_percent':100,'parts':[]}
alltris=[]

def stats(mesh,world):
 bm=bmesh.new();bm.from_mesh(mesh);bm.transform(world);bm.normal_update()
 co=[v.co for v in bm.verts]; result={'vertices':len(bm.verts),'faces':len(bm.faces),'nonmanifold_edges':sum(not e.is_manifold for e in bm.edges),'boundary_edges':sum(e.is_boundary for e in bm.edges),'signed_volume_mm3':bm.calc_volume(signed=True),'bounds_mm':[[min(v[i] for v in co) for i in range(3)],[max(v[i] for v in co) for i in range(3)]]}
 bm.free();return result

def write_stl(path,tris):
 with path.open('wb') as f:
  f.write(b'SLIM v3 approved base geometry; rigid transform only; units mm'.ljust(80,b' '));f.write(struct.pack('<I',len(tris)))
  for tri in tris:
   n=(tri[1]-tri[0]).cross(tri[2]-tri[0]);n.normalize();f.write(struct.pack('<12fH',*n,*tri[0],*tri[1],*tri[2],0))

for filename,name,xy,flip,orientation in parts:
 o=s.objects[name];mesh=o.data
 assert o.type=='MESH'
 assert all(m.type in ('BEVEL','WEIGHTED_NORMAL') for m in o.modifiers)
 dg=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(dg);em=ev.to_mesh()
 base_stats=stats(mesh,o.matrix_world);eval_stats=stats(em,o.matrix_world);ev.to_mesh_clear()
 mods=[]
 for m in o.modifiers:
  d={'name':m.name,'type':m.type,'show_viewport':m.show_viewport,'show_render':m.show_render}
  if m.type=='BEVEL': d.update(width_mm=m.width,segments=m.segments,limit_method=m.limit_method,angle_limit=m.angle_limit)
  mods.append(d)
 # Exact rotation matrix to avoid tiny sine(pi) terms: 180 degrees about X.
 R=Matrix(((1,0,0,0),(0,-1 if flip else 1,0,0),(0,0,-1 if flip else 1,0),(0,0,0,1)))
 coords=[R@o.matrix_world@v.co for v in mesh.vertices]
 lo=Vector([min(v[i] for v in coords) for i in range(3)])
 T=Matrix.Translation(-lo)@R@o.matrix_world
 # Beauty triangulation only changes diagonals; preserve every surface vertex.
 bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.triangulate(bm,faces=list(bm.faces),quad_method='BEAUTY',ngon_method='BEAUTY');bm.normal_update()
 tris=[tuple(T@v.co for v in f.verts) for f in bm.faces];bm.free()
 write_stl(OUT/filename,tris)
 shift=Vector((xy[0],xy[1],0));alltris.extend(tuple(v+shift for v in tri) for tri in tris)
 r={'file':filename,'source_object':name,'print_orientation':parts[len(report['parts'])][4],'rotation_about_x_degrees':180 if flip else 0,'source_to_individual_stl_matrix':[[float(x) for x in row] for row in T],'individual_to_plate_translation_mm':[xy[0],xy[1],0],'base_mesh':base_stats,'evaluated_visual_modifiers_mesh':eval_stats,'excluded_modifiers':mods,'triangle_count':len(tris),'sha256':hashlib.sha256((OUT/filename).read_bytes()).hexdigest()}
 report['parts'].append(r)
write_stl(OUT/'00_all_parts_A1mini.stl',alltris)
report['arranged_plate']={'file':'00_all_parts_A1mini.stl','build_volume_mm':[180,180,180],'part_count':4,'triangle_count':len(alltris),'sha256':hashlib.sha256((OUT/'00_all_parts_A1mini.stl').read_bytes()).hexdigest(),'supports_included':False,'brims_included':False}
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash
report['source_unchanged_sha256_verified']=True
(OUT/'export_manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('EXPORT_COMPLETE',flush=True)
for p in report['parts']:print(p['file'],'base',p['base_mesh'],'eval',p['evaluated_visual_modifiers_mesh'],flush=True)
