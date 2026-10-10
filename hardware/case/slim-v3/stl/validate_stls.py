"""Independent binary STL audit; no mesh repair, no source-file mutation."""
import json,struct,hashlib,itertools
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
P=Path(__file__).resolve().parent
manifest=json.loads((P/'export_manifest.json').read_text())
DT=np.dtype([('normal','<f4',(3,)),('verts','<f4',(3,3)),('attr','<u2')])

def read(path):
 data=path.read_bytes();n=struct.unpack_from('<I',data,80)[0];assert len(data)==84+n*50
 a=np.frombuffer(data,DT,n,offset=84);return a['verts'].astype('float64'),a['normal'].astype('float64')
def audit(path):
 tri,normals=read(path);vertices,inverse=np.unique(tri.reshape(-1,3),axis=0,return_inverse=True);faces=inverse.reshape(-1,3)
 edges=defaultdict(list)
 for i,f in enumerate(faces):
  for j in range(3):a,b=int(f[j]),int(f[(j+1)%3]);edges[tuple(sorted((a,b)))].append((i,a,b))
 # Vertex links of a closed 2-manifold must each form one cycle.
 vertex_links=defaultdict(list)
 for face in faces:
  for j in range(3):vertex_links[int(face[j])].append((int(face[(j+1)%3]),int(face[(j+2)%3])))
 bad_vertices=0
 for vertex,links in vertex_links.items():
  link_adj=defaultdict(set)
  for a,b in links:link_adj[a].add(b);link_adj[b].add(a)
  seen=set();stack=[next(iter(link_adj))]
  while stack:
   x=stack.pop()
   if x in seen:continue
   seen.add(x);stack.extend(link_adj[x]-seen)
  if len(seen)!=len(link_adj) or any(len(x)!=2 for x in link_adj.values()):bad_vertices+=1
 assert bad_vertices==0,path.name
 adj=defaultdict(set)
 for inc in edges.values():
  for a,b in itertools.combinations(inc,2):adj[a[0]].add(b[0]);adj[b[0]].add(a[0])
 unseen=set(range(len(faces)));components=[]
 while unseen:
  stack=[unseen.pop()];comp=[]
  while stack:
   x=stack.pop();comp.append(x)
   for y in adj[x]:
    if y in unseen:unseen.remove(y);stack.append(y)
  components.append(comp)
 cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);area2=np.linalg.norm(cross,axis=1)
 unit=np.divide(cross,area2[:,None],out=np.zeros_like(cross),where=area2[:,None]>0)
 # Translation-stable signed-volume calculation, separately for each component.
 volumes=[]
 for comp in components:
  ctri=tri[comp];origin=ctri.reshape(-1,3).mean(axis=0);v=ctri-origin
  volumes.append(float(np.einsum('ij,ij->i',v[:,0],np.cross(v[:,1],v[:,2])).sum()/6))
 bounds=np.vstack((vertices.min(axis=0),vertices.max(axis=0)));downward=(unit[:,2]<-0.70710678)&(tri[:,:,2].mean(axis=1)>0.001)
 # Coplanar downward-facing groups show possible overhang roofs, not a slicer support simulation.
 down_groups=defaultdict(lambda:{'area_mm2':0.,'xy_min':[float('inf')]*2,'xy_max':[float('-inf')]*2,'triangle_count':0})
 for i in np.flatnonzero(downward):
  z=round(float(tri[i,:,2].mean()),3);g=down_groups[str(z)];g['area_mm2']+=area2[i]/2;g['triangle_count']+=1
  g['xy_min']=np.minimum(g['xy_min'],tri[i,:,:2].min(axis=0)).tolist();g['xy_max']=np.maximum(g['xy_max'],tri[i,:,:2].max(axis=0)).tolist()
 result={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'triangles':len(tri),'vertices_exact_weld':len(vertices),'nonmanifold_vertices':bad_vertices,'bounds_mm':bounds.tolist(),'dimensions_mm':np.diff(bounds,axis=0)[0].tolist(),'min_Z_mm':float(bounds[0,2]),'max_Z_mm':float(bounds[1,2]),'connected_components':len(components),'boundary_edges':sum(len(x)==1 for x in edges.values()),'nonmanifold_edges':sum(len(x)!=2 for x in edges.values()),'inconsistent_winding_edges':sum(len(x)==2 and x[0][1:]==x[1][1:] for x in edges.values()),'degenerate_triangles':int(sum(area2<1e-10)),'min_triangle_area_mm2':float(area2.min()/2),'duplicate_triangles':len(faces)-len(set(tuple(sorted(f)) for f in faces)),'stored_normal_mismatch_count':int(sum(np.linalg.norm(unit-normals,axis=1)>1e-4)),'signed_component_volumes_mm3':volumes,'total_volume_mm3':sum(volumes),'finite_coordinates':bool(np.isfinite(vertices).all()),'downward_facing_non_bed_area_mm2':float(area2[downward].sum()/2),'downward_face_groups_by_print_Z_mm':down_groups}
 
 assert result['finite_coordinates'] and result['nonmanifold_edges']==0 and result['inconsistent_winding_edges']==0 and result['degenerate_triangles']==0 and result['duplicate_triangles']==0 and result['stored_normal_mismatch_count']==0 and min(volumes)>0,path.name
 return result,tri
results={};tri_by_name={}
for path in sorted(P.glob('*.stl')):results[path.name],tri_by_name[path.name]=audit(path)
for p in manifest['parts']:
 r=results[p['file']];assert r['connected_components']==1;assert abs(r['min_Z_mm'])<1e-6
 base=p['base_mesh'];assert np.allclose(r['dimensions_mm'],np.array(base['bounds_mm'][1])-base['bounds_mm'][0],atol=3e-5,rtol=0)
 r['relative_volume_change_from_base']=abs(r['total_volume_mm3']-base['signed_volume_mm3'])/base['signed_volume_mm3'];assert r['relative_volume_change_from_base']<1e-5
all_=results['00_all_parts_A1mini.stl'];assert all_['connected_components']==4;assert np.all(np.array(all_['bounds_mm'])[0]>=0) and np.all(np.array(all_['bounds_mm'])[1]<180)
# Combined file uses precisely the individual-file triangles after rigid translation, within STL float32 precision.
expect=np.concatenate([tri_by_name[p['file']]+p['individual_to_plate_translation_mm'] for p in manifest['parts']]);actual=tri_by_name['00_all_parts_A1mini.stl'];max_err=float(abs(expect-actual).max());assert max_err<2e-5
# Nonoverlapping XY bounding boxes ensure no parts collide on the plate.
placed=[]
for p in manifest['parts']:
 b=np.array(results[p['file']]['bounds_mm'])+p['individual_to_plate_translation_mm'];placed.append((p['file'],b))
min_gap=float('inf')
for (an,a),(bn,b) in itertools.combinations(placed,2):
 gap=np.maximum(0,np.maximum(a[0,:2]-b[1,:2],b[0,:2]-a[1,:2]));assert np.any(gap>0),(an,bn);min_gap=min(min_gap,float(np.linalg.norm(gap)))
report={'status':'STL_GEOMETRY_CHECKS_PASS_TRIAL_PRINT_ONLY','units':'mm coordinates; STL itself contains no standardized unit metadata','scale_percent':100,'source_geometry_preserved':True,'actual_stl_checks':'Parsed final binary files, exact vertex welding, all edges incident to two oppositely wound faces; positive volumes and stored outward normals; no repair performed','checks_not_performed':['Bambu Studio slicing or support simulation','Physical print, fit, insertion force, fatigue, switch travel or electronic assembly test','Exhaustive triangle self-intersection test'],'combined_triangle_coordinate_max_error_mm':max_err,'plate_part_count':4,'plate_min_part_bbox_gap_mm':min_gap,'plate_fits_180_mm':True,'files':results}
(P/'stl_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'plate_bounds':all_['bounds_mm'],'plate_dimensions':all_['dimensions_mm'],'min_gap':min_gap,'files':{n:{k:r[k] for k in ['triangles','dimensions_mm','connected_components','nonmanifold_edges','degenerate_triangles','total_volume_mm3','downward_facing_non_bed_area_mm2']} for n,r in results.items()}},indent=2))
