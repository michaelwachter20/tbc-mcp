"""tbc-script
{
 "name": "relayer_points_by_code",
 "description": "Move points whose feature code starts with a prefix onto a layer. dry_run by default.",
 "mode": "write",
 "parameters": [
  {
   "name": "code_prefix",
   "type": "string",
   "required": true
  },
  {
   "name": "layer",
   "type": "string",
   "required": true
  },
  {
   "name": "dry_run",
   "type": "boolean",
   "default": true
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
pref = args['code_prefix'].upper()
dry = args['dry_run']
hits = []
for pt in TbcPoint.GetAllPoints(prj):
    try:
        code = str(pt.FeatureCode or '')
        if code.upper().startswith(pref):
            hits.append(str(pt.Name))
            if not dry:
                pt.Layer = Layer.FindOrCreateLayer(prj, args['layer']).SerialNumber
    except Exception as ex:
        print('skipped %s: %s' % (pt.Name, ex))
print('%s %d points' % ('would move' if dry else 'moved', len(hits)))
result = {'count': len(hits), 'sample': hits[:15], 'dry_run': dry}
