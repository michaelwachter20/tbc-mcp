# Written for and verified on Trimble Business Center 2026.10 (build 44.0.9666.28609). For a newer release, ADD handling for it and keep the 2026.10 behaviour (see README > TBC versions).
# IronPython 3.4 code executed INSIDE TBC by the MCP server. Prepended: ACTION, ARGS. Sets `result`.
# Read-only view of the user's TBC license: which features are licensed and which commands are usable.
# The license key id is hashed here (SHA-256) so the raw id never leaves TBC; no user names/emails are read.
"""License helper run inside TBC through the bridge's execute_python.

How it is called
----------------
The server's run_ipy("license", ACTION, ARGS) reads this file fresh on every call (so editing it needs no macro
reinstall), prepends `ACTION = "<action>"` and `ARGS = <dict from JSON>`, and sends it to the bridge's
execute_python with transaction=False (nothing here changes the project). The code runs in the bridge's namespace,
so TrimbleOffice (and prj, bridge, ...) are available without importing them. The last line dispatches ACTION and
stores the return value in `result`, which the bridge sends back as JSON.

Caller: license_profile() in mcp_server/tbc_mcp_server.py. On every MCP server start it calls "fingerprint", then
builds the profile with "profile" and saves it as %LOCALAPPDATA%\\TBC-MCP\\license\\<fingerprint>.json on this
machine only (never in the repository or the shared knowledge base). The fingerprint is also registered as private
so it is kept out of shared project notes.

Actions (ARGS is ignored by both)
---------------------------------
fingerprint -> {"fingerprint": 16 hex chars, "licensed_feature_count": int}
    First 16 hex digits of SHA-256(license key id + "|" + sorted names of the usable licensed features). It changes
    when the license key or its usable features change, so a new license gets a new profile file.
profile -> fingerprint's keys plus, when the license service is available:
    key_type, licensed_major_version, valid_key_found, search_scope (bools/ints as-is, anything else as str),
    subscription_expires, maintenance_expires ("yyyy-MM-dd" or None),
    features_licensed [{name, product, usable, expires, expired?}], features_unlicensed [names],
    and always:
    commands {command key: {"licensed": True/False/None, "caption": str, "needs_any_of": [feature codes]}}
    for every command in TBC's CommandList (about 1180). licensed is True when the command needs no feature,
    None when the check itself failed.

Privacy
-------
- The license key id is only used inside the hash; the raw id is never returned.
- Nothing personal is read: no user, licensee or company names, no e-mail addresses.
- What is returned is license metadata (key type, dates, feature and command names), which the server keeps on
  this machine only.

TBC SDK notes
-------------
- The license service is Trimble.Vce.Core.Server.TheServer.LicenseService. Command checks use
  Server.TheServer.CanUseFeature on the command's LicenseCodes, the same check command_ui.py's "license" action
  makes before a command is opened (the server refuses unlicensed commands up front instead of letting TBC show
  its license popups).
- Every SDK read is wrapped in try/except: a property missing on some license type must not break the profile.
"""
import clr
from System import Array, DateTime
from System.Text import Encoding
from System.Security.Cryptography import SHA256
from Trimble.Vce.Core import Server
from Trimble.Vce.License import Feature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha(text):
    """Lowercase hex SHA-256 of `text` (UTF-8), computed with .NET's System.Security.Cryptography.SHA256."""
    h = SHA256.Create().ComputeHash(Encoding.UTF8.GetBytes(text))
    return "".join("%02x" % b for b in h)


def _service():
    """TBC's license service (Server.TheServer.LicenseService), or None if it can't be reached."""
    try:
        return Server.TheServer.LicenseService
    except Exception:
        return None


def _date(d):
    """A .NET DateTime as "yyyy-MM-dd", or None.

    DateTime.MinValue / MaxValue are treated as "no date".
    Anything that isn't a DateTime also gives None.
    """
    try:
        if d is None or d == DateTime.MinValue or d == DateTime.MaxValue:
            return None
        return d.ToString("yyyy-MM-dd")
    except Exception:
        return None


def _features(svc):
    """Read the license's features. Returns (licensed, unlicensed), two lists of feature dicts.

    GetFeatures fills two out-parameters of type List<IFeatureInformation>; IronPython passes them as
    clr.Reference[...] objects and reads .Value afterwards. The first list is treated as licensed, the second as
    unlicensed. The meaning of the third argument (False) is not documented in this repository.
    Each dict: {"name", "product" (or None), "usable", "expires" ("yyyy-MM-dd"/None), "expired": True (only when
    expired)}; a feature whose details can't all be read keeps the keys read so far.
    If GetFeatures itself fails, licensed is [{"error": "GetFeatures failed: ..."}].
    """
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


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def fingerprint(args):
    """ACTION "fingerprint": a short anonymous id for this license. Returns {fingerprint, licensed_feature_count}.

    Hash input: key id (empty if unreadable) + "|" + comma-joined sorted names of licensed features that are usable
    (a feature without a "usable" value counts as usable). Only the first 16 hex characters are returned.
    """
    svc = _service()
    key = ""
    try:
        key = str(svc.KeyId) if svc is not None else ""
    except Exception:
        pass
    lic, _ = _features(svc) if svc is not None else ([], [])
    # Note: if GetFeatures failed, its {"error": ...} entry has no name and counts here as one feature named "".
    names = sorted(f.get("name", "") for f in lic if f.get("usable", True))
    return {"fingerprint": _sha(key + "|" + ",".join(names))[:16], "licensed_feature_count": len(names)}


def profile(args):
    """ACTION "profile": the full license profile (see the module docstring for the shape).

    Starts from fingerprint(), adds the license service's key facts, dates and features, then checks every TBC
    command: a command's LicenseCodes are the features it needs, and CanUseFeature(codes) says whether this license
    has any of them (hence "needs_any_of"). Read-only.
    """
    svc = _service()
    srv = Server.TheServer
    out = fingerprint(args)
    if svc is not None:
        # Simple license facts; each read separately so one missing property doesn't drop the rest.
        for name, attr in (("key_type", "KeyType"), ("licensed_major_version", "LicensedMajorVersion"),
                           ("valid_key_found", "ValidKeyFound"), ("search_scope", "SelectedSearchScope")):
            try:
                v = getattr(svc, attr)
                out[name] = v if isinstance(v, (bool, int)) else str(v)  # enums and other .NET values -> text
            except Exception:
                pass
        out["subscription_expires"] = _date(getattr(svc, "SubscriptionExpireDate", None))
        out["maintenance_expires"] = _date(getattr(svc, "MaintenanceExpireDate", None))
        lic, unl = _features(svc)
        out["features_licensed"] = lic
        out["features_unlicensed"] = [f.get("name") for f in unl]
    # TrimbleOffice comes from the bridge's execute_python namespace (not imported here).
    cl = TrimbleOffice.TheOffice.CommandProcessor.CommandList
    cmds = {}
    for kv in cl:
        k = str(kv.Key)
        try:
            codes = list(kv.Value.LicenseCodes or [])
        except Exception:
            codes = []
        try:
            # No license codes = the command needs no licensed feature. Otherwise ask TBC with a .NET Feature[] array.
            ok = True if not codes else bool(srv.CanUseFeature(Array[Feature](codes)))
        except Exception:
            ok = None  # unknown: the server treats None as "not known", not as unlicensed
        try:
            cap = str(kv.Value.Caption).replace("&", "").replace("_", "")  # strip access-key markers
        except Exception:
            cap = ""
        cmds[k] = {"licensed": ok, "caption": cap, "needs_any_of": [str(c) for c in codes]}
    out["commands"] = cmds
    return out


# Dispatch: the server prepends ACTION/ARGS; the bridge returns `result`. An unknown ACTION raises KeyError.
result = {"fingerprint": fingerprint, "profile": profile}[ACTION](ARGS)
