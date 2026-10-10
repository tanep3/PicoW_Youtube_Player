import bpy,math
from pathlib import Path
from mathutils import Vector,Matrix
P=Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(P/'YouTube_LCD_Case_SLIM_Fit_v3.blend'))
def render(sn,fn,pos,target,scale):
 s=bpy.data.scenes[sn];bpy.context.window.scene=s;cam=s.camera;cam.location=pos;direction=Vector(target)-cam.location;d=direction.normalized();right=d.cross(Vector((0,-1,0))).normalized();up=right.cross(d);q=Matrix((right,up,-d)).transposed().to_quaternion() if pos[2]<target[2] else direction.to_track_quat('-Z','Y');cam.rotation_euler=q.to_euler();cam.data.ortho_scale=scale;s.render.filepath=str(P/fn);bpy.ops.render.render(write_still=True)
render('01_ASSEMBLED_DRAFT_mm','01_front_3quarter.png',(-45,-60,-110),(32,16,10),112)
s=bpy.data.scenes['01_ASSEMBLED_DRAFT_mm'];bpy.context.window.scene=s;s.camera.location=(32,16,-120);s.camera.rotation_euler=(math.pi,0,0);s.camera.data.ortho_scale=75;s.render.filepath=str(P/'02_front_orthographic.png');bpy.ops.render.render(write_still=True)
render('01_ASSEMBLED_DRAFT_mm','03_back_3quarter.png',(104,86,115),(32,16,10),104)
render('02_EXPLODED_DISPLAY_ONLY','05_exploded.png',(108,95,145),(32,16,34),160)
render('03_CUTAWAY_DISPLAY_ONLY','04_cutaway.png',(91,101,92),(32,14,9),104)
render('04_REAR_OPEN_INSPECTION','06_rear_open.png',(94,96,118),(32,16,9),103)
render('05_LID_FLEXURE_INSPECTION','07_lid_snap_detail.png',(-30,-45,-85),(32,16,18),100)
render('06_INTERNAL_RETENTION_INSPECTION','08_integral_tabs_and_hole_seats.png',(82,82,103),(30,15,8),99)
render('06_INTERNAL_RETENTION_INSPECTION','09_LCD_corner_snap_detail.png',(43,54,65),(19,16,2.7),47)
