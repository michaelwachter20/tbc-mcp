"""tbc-script
{
 "name": "points_in_box",
 "description": "List points inside an easting/northing box (display units), optionally by layer.",
 "mode": "read",
 "parameters": [
  {
   "name": "min_e",
   "type": "number",
   "required": true
  },
  {
   "name": "min_n",
   "type": "number",
   "required": true
  },
  {
   "name": "max_e",
   "type": "number",
   "required": true
  },
  {
   "name": "max_n",
   "type": "number",
   "required": true
  },
  {
   "name": "layer",
   "type": "string",
   "default": null,
   "description": "exact layer name"
  },
  {
   "name": "limit",
   "type": "integer",
   "default": 200
  }
 ],
 "updated": "2026-10-13T11:03:11",
 "script_version": 1,
 "tbc_versions": [
  "2026.10"
 ],
 "tbc_build": "44.0.9666.28609"
}
"""
f = bridge.factor(prj)
out = []
total = 0
for pt in TbcPoint.GetAllPoints(prj):
    pos = pt.Position
    e, n = pos.X * f, pos.Y * f
    if not (args['min_e'] <= e <= args['max_e'] and args['min_n'] <= n <= args['max_n']):
        continue
    lay = bridge.layer_name(prj, pt.Layer)
    if args['layer'] and lay != args['layer']:
        continue
    total += 1
    if len(out) < args['limit']:
        out.append({'name': str(pt.Name), 'e': e, 'n': n, 'z': pos.Z * f, 'layer': lay})
result = {'total': total, 'points': out}
