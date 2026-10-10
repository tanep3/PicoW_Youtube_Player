"""Preview exact final STL bytes; no bevel/subdivision or electronics added."""
import bpy,struct,json,math
from pathlib import Path
from mathutils import Vector
P=Path(__file__).resolve().parent
bpy.ops.wm.read_factory_settings(use_empty=True)
s=bpy.context.scene;s.name='ACTUAL_STL_PRINT_LAYOUT';s.unit_settings.system='METRIC';s.unit_settings.scale_length=.001;s.unit_settings.length_unit='MILLIMETERS'
man=json.loads((P/'export_manifest.json').read_text())
def material(name,col):
 m=bpy.data.materials.new(name);m.diffuse_color=(*col,1);return m
teal=material('Shell STL',(.02,.37,.40));lidmat=material('Lid STL',(.04,.50,.50));amber=material('Retainer STL',(.93,.40,.065));floor=material('Surface',(.89,.91,.93));grid=material('10 mm reference grid',(.69,.74,.77));ink=material('Labels',(.06,.12,.19))
# Read the all-parts STL, divide triangles by manifest counts, weld exact identical coordinates only.
data=(P/'00_all_parts_A1mini.stl').read_bytes();off=84
for part in man['parts']:
 verts=[];faces=[];lookup={}
 for _ in range(part['triangle_count']):
  row=struct.unpack_from('<12fH',data,off);off+=50;face=[]
  for j in range(3):
   co=tuple(row[3+j*3:6+j*3])
   if co not in lookup:lookup[co]=len(verts);verts.append(co)
   face.append(lookup[co])
  faces.append(face)
 mesh=bpy.data.meshes.new(part['file']);mesh.from_pydata(verts,[],faces);mesh.update();o=bpy.data.objects.new(part['file'],mesh);s.collection.objects.link(o);o.data.materials.append(teal if part['file'].startswith('01') else lidmat if part['file'].startswith('02') else amber)
bpy.ops.mesh.primitive_plane_add(size=400,location=(90,40,-.025));bpy.context.object.data.materials.append(floor)
# Thin reference grid lines on the floor, not printable objects.
for is_x in [True,False]:
 for a in range(-60,221,10):
  cu=bpy.data.curves.new('Grid line','CURVE');cu.dimensions='3D';cu.bevel_depth=.027;cu.bevel_resolution=0;sp=cu.splines.new('POLY');sp.points.add(1)
  sp.points[0].co=(a,-60,-.012,1) if is_x else (-60,a,-.012,1);sp.points[1].co=(a,220,-.012,1) if is_x else (220,a,-.012,1);ob=bpy.data.objects.new('Grid 10 mm',cu);s.collection.objects.link(ob);cu.materials.append(grid)
labels=[]
for body,loc in [('01  SHELL',(21,47,0)),('02  LID',(97,47,0)),('03',(34,62,0)),('04',(72,62,0))]:
 cu=bpy.data.curves.new(body,'FONT');cu.body=body;cu.size=2.7;cu.extrude=0;ob=bpy.data.objects.new(body,cu);s.collection.objects.link(ob);ob.location=loc;cu.materials.append(ink);labels.append(ob)
s.render.engine='BLENDER_WORKBENCH';s.display.shading.light='STUDIO';s.display.shading.studio_light='paint.sl';s.display.shading.studiolight_rotate_z=.4;s.display.shading.color_type='MATERIAL';s.display.shading.show_shadows=True;s.display.shading.show_cavity=True;s.display.shading.cavity_type='BOTH';s.display.shading.curvature_ridge_factor=1.1;s.display.shading.curvature_valley_factor=1.3;s.display.shading.show_specular_highlight=True;s.display.shading.background_type='WORLD';s.world=bpy.data.worlds.new('Preview World');s.world.color=(.93,.94,.96);s.render.resolution_x=1600;s.render.resolution_y=1000;s.render.resolution_percentage=100;s.view_settings.view_transform='Standard';s.render.image_settings.file_format='PNG';s.render.film_transparent=False
bpy.ops.object.camera_add();cam=bpy.context.object;cam.data.type='ORTHO';cam.data.clip_end=1000;s.camera=cam
for fn,pos,target,scale in [('layout_top_raw.png',(90,42,200),(90,42,0),167),('layout_angle_raw.png',(196,-111,179),(90,36,3),167)]:
 cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=scale;s.render.filepath=str(P/fn);bpy.ops.render.render(write_still=True)
print('ACTUAL_STL_PREVIEWS_COMPLETE',flush=True)
