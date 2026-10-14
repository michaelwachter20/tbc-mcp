# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server. Prepended: ACTION, ARGS. Sets `result`.
# Read-only view of the user's TBC license: which features are licensed and which commands are usable.
# The license key id is hashed here (SHA-256) so the raw id never leaves TBC; no user names/emails are read.
import clr
from System import Array, DateTime
from System.Text import Encoding
from System.Security.Cryptography import SHA256
from Trimble.Vce.Core import Server
from Trimble.Vce.License import Feature


def _sha(text):
    h = SHA256.Create().ComputeHash(Encoding.UTF8.GetBytes(text))
    return "".join("%02x" % b for b in h)


def _service():
    try:
        return Server.TheServer.LicenseService
    except Exception:
        return None


def _date(d):
    try:
        if d is None or d == DateTime.MinValue or d == DateTime.MaxValue:
            return None
        return d.ToString("yyyy-MM-dd")
    except Exception:
        return None


def _features(svc):
    lic, unl = [], []
    try:
        from System.Collections.Generic import List
        from Trimble.Vce.License import IFeatureInformation
        r1 = clr.Reference[List[IFeatureInformation]]()
        r2 = clr.Reference[List[IFeatureInformation]]()
        svc.GetFeatures(r1, r2, False)
        for src, dst in ((r1.Value, lic), (r2.Value, unl)):
            if src is None:
                continue
            for f in src:
                d = {"name": str(f.Name)}
                try:
                    d["product"] = str(f.Product) if f.Product else None
                    d["usable"] = bool(f.Usable)
                    d["expires"] = _date(f.ExpirationDate)
                    if f.Expired:
                        d["expired"] = True
                except Exception:
                    pass
                dst.append(d)
    except Exception as ex:
        lic.append({"error": "GetFeatures failed: %s" % ex})
    return lic, unl


def fingerprint(args):
    svc = _service()
    key = ""
    try:
        key = str(svc.KeyId) if svc is not None else ""
    except Exception:
        pass
    lic, _ = _features(svc) if svc is not None else ([], [])
    names = sorted(f.get("name", "") for f in lic if f.get("usable", True))
    return {"fingerprint": _sha(key + "|" + ",".join(names))[:16], "licensed_feature_count": len(names)}


def profile(args):
    svc = _service()
    srv = Server.TheServer
    out = fingerprint(args)
    if svc is not None:
        for name, attr in (("key_type", "KeyType"), ("licensed_major_version", "LicensedMajorVersion"),
                           ("valid_key_found", "ValidKeyFound"), ("search_scope", "SelectedSearchScope")):
            try:
                v = getattr(svc, attr)
                out[name] = v if isinstance(v, (bool, int)) else str(v)
            except Exception:
                pass
        out["subscription_expires"] = _date(getattr(svc, "SubscriptionExpireDate", None))
        out["maintenance_expires"] = _date(getattr(svc, "MaintenanceExpireDate", None))
        lic, unl = _features(svc)
        out["features_licensed"] = lic
        out["features_unlicensed"] = [f.get("name") for f in unl]
    cl = TrimbleOffice.TheOffice.CommandProcessor.CommandList
    cmds = {}
    for kv in cl:
        k = str(kv.Key)
        try:
            codes = list(kv.Value.LicenseCodes or [])
        except Exception:
            codes = []
        try:
            ok = True if not codes else bool(srv.CanUseFeature(Array[Feature](codes)))
        except Exception:
            ok = None
        try:
            cap = str(kv.Value.Caption).replace("&", "").replace("_", "")
        except Exception:
            cap = ""
        cmds[k] = {"licensed": ok, "caption": cap, "needs_any_of": [str(c) for c in codes]}
    out["commands"] = cmds
    return out


result = {"fingerprint": fingerprint, "profile": profile}[ACTION](ARGS)
