# -*- coding: utf-8 -*-
"""M4 scene parsing from GET /api/fleet/scenes/schema/{sceneId}: structure.areas[].mergedMap {points, paths, bins}.
MapPoint / MapPath / SceneBin layouts are not fully documented, so every field is looked up under several names and
unknown fields are ignored. Output matches rds_scene.parse_scene (stations) / parse_groups / extract_geom.

Geometry: point cloud from normalPosList when present in the schema (RDS-shaped, including mergedMap); otherwise core falls back to download_maps (.smap). Routes tessellated
from className/curveType + control points via rds_scene.tessellate — not bare start→end segments. Stations include LM
and AP (same as RDS) so the Map tab can click and label them."""
import math
from . import rds_scene

def _num(v):
    try: return float(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError): return None

def _first(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""): return v
    return None

def _xy(o):
    if not isinstance(o, dict): return None, None
    pos = o.get("pos") if isinstance(o.get("pos"), dict) else o.get("position") if isinstance(o.get("position"), dict) else o
    return _num(pos.get("x")), _num(pos.get("y"))

def _xy_pair(o):
    """(x, y) or None — accepts RDS pos wrappers and flat {x,y}."""
    if o is None: return None
    if isinstance(o, (list, tuple)) and len(o) >= 2:
        x, y = _num(o[0]), _num(o[1])
        return (x, y) if x is not None and y is not None else None
    if isinstance(o, dict):
        p = rds_scene._xy(o)
        if p: return p
        x, y = _xy(o)
        return (x, y) if x is not None and y is not None else None
    return None

def _name(o):
    v = _first(o, "name", "instanceName", "pointName", "id")
    return str(v) if v is not None else None

def _ref(v):
    """path endpoint: a name string, or an object carrying a name"""
    if isinstance(v, dict): return _name(v)
    return str(v) if v not in (None, "") else None

def _areas(js):
    st = js.get("structure") if isinstance(js, dict) else None
    areas = st.get("areas") if isinstance(st, dict) else None
    return [a for a in (areas or []) if isinstance(a, dict) and not a.get("disabled")]

def _maps(js):
    for a in _areas(js):
        m = a.get("mergedMap")
        if isinstance(m, dict): yield m

def _list(m, k): return [x for x in (m.get(k) or []) if isinstance(x, dict)] if isinstance(m.get(k), list) else []

def is_lm(name, typ=""):
    return str(name).startswith("LM") or "LocationMark" in str(typ)

def parse_scene(js):
    pts = {}; edges = []
    for m in _maps(js):
        for p in _list(m, "points"):
            n = _name(p)
            if not n: continue
            x, y = _xy(p)
            q = pts.setdefault(n, {"name": n, "type": str(_first(p, "type", "className", "kind") or "?"), "x": x, "y": y, "bins": [], "props": {}})
            d = _num(_first(p, "dir", "direction", "angle", "theta"))
            if d is not None and "dir" not in q: q["dir"] = round(d, 6); q["dirDeg"] = round(math.degrees(d), 1)
        for pa in _list(m, "paths"):
            a = _ref(_first(pa, "fromPointName", "from", "startPointName", "start", "startPos", "fromPoint"))
            b = _ref(_first(pa, "toPointName", "to", "endPointName", "end", "endPos", "toPoint"))
            if a and b: edges.append((a, b))
        for b in _list(m, "bins"):
            bn = _name(b); pn = _ref(_first(b, "pointName", "point", "workPointName", "location", "loc"))
            if not bn: continue
            if pn:
                q = pts.setdefault(pn, {"name": pn, "type": "?", "x": None, "y": None, "bins": [], "props": {}})
                q["bins"].append(bn)
    out = []
    for n, p in pts.items():
        # Include LM and AP (RDS returns every map point). Only non-LM get pre-point candidates.
        if is_lm(n, p["type"]):
            out.append(dict(p, pre="", preSrc="", preCands=[], preInfo=[]))
            continue
        cands = []
        for a, b in edges:
            o = a if b == n else b if a == n else None
            if o and o in pts and is_lm(o, pts[o]["type"]) and o not in cands: cands.append(o)
        def dist(c):
            q = pts[c]
            if None in (p["x"], p["y"], q["x"], q["y"]): return 1e18
            return math.hypot(p["x"] - q["x"], p["y"] - q["y"])
        cands.sort(key=dist)
        info = [{"name": c, "dir": None, "dist": None if dist(c) >= 1e18 else round(dist(c), 3), "lm": True} for c in cands]
        out.append(dict(p, pre=cands[0] if cands else "", preSrc="path" if cands else "", preCands=cands, preInfo=info))
    out.sort(key=lambda s: s["name"])
    return out

def parse_groups(js):
    st = js.get("structure") if isinstance(js, dict) else None
    if not isinstance(st, dict): return []
    groups = {}; ids = {}
    for g in st.get("robotGroups") or []:
        if isinstance(g, dict) and g.get("name"):
            groups[g["name"]] = {"name": g["name"], "robots": []}; ids[str(g.get("id"))] = g["name"]
    for r in st.get("robots") or []:
        if not isinstance(r, dict): continue
        rn = _first(r, "robotName", "name", "id")
        gn = _first(r, "groupName") or ids.get(str(_first(r, "groupId", "group")))
        if rn and gn in groups: groups[gn]["robots"].append(str(rn))
    return list(groups.values())

def _rds_shaped_curve(o):
    """True when rds_scene.extract_geom would already tessellate this object."""
    if not isinstance(o, dict) or not o.get("className"): return False
    sp, ep = o.get("startPos"), o.get("endPos")
    return (isinstance(sp, dict) and isinstance(ep, dict) and isinstance(sp.get("pos"), dict)
            and rds_scene._xy(sp) and rds_scene._xy(ep))

def _controls(pa):
    """Up to 3 control points from named fields or a controlPoints/controls list."""
    out = []
    for k in ("controlPos1", "controlPos2", "controlPos3", "control1", "control2", "control3", "cp1", "cp2", "cp3"):
        p = _xy_pair(pa.get(k))
        if p: out.append(p)
    if len(out) < 3:
        for item in (pa.get("controlPoints") or pa.get("controls") or []):
            p = _xy_pair(item)
            if p: out.append(p)
            if len(out) >= 3: break
    # single controlPos / midPos (Arc-style)
    if not out:
        for k in ("controlPos", "midPos", "via", "arcPos"):
            p = _xy_pair(pa.get(k))
            if p: out.append(p); break
    while len(out) < 3: out.append(None)
    return out[0], out[1], out[2]

def _path_endpoints(pa, byname):
    """Resolve (p0, p1, name0, name1) from embedded coords or point-name refs."""
    sp, ep = pa.get("startPos"), pa.get("endPos")
    p0 = _xy_pair(sp) if isinstance(sp, dict) else None
    p1 = _xy_pair(ep) if isinstance(ep, dict) else None
    n0 = _ref(sp) if isinstance(sp, dict) else ""
    n1 = _ref(ep) if isinstance(ep, dict) else ""
    if p0 is None or p1 is None:
        a = _ref(_first(pa, "fromPointName", "from", "startPointName", "start", "fromPoint")) or n0
        b = _ref(_first(pa, "toPointName", "to", "endPointName", "end", "toPoint")) or n1
        if p0 is None and a in byname: p0 = byname[a]; n0 = a
        if p1 is None and b in byname: p1 = byname[b]; n1 = b
    else:
        if not n0: n0 = _ref(_first(pa, "fromPointName", "from", "startPointName")) or ""
        if not n1: n1 = _ref(_first(pa, "toPointName", "to", "endPointName")) or ""
    return p0, p1, n0, n1

def extract_geom(js, points_only=False):
    """Point cloud = normalPosList (and RDS-equivalent nested lists), never map station dots.
    Curves = tessellated polylines from className/curveType + control points when present."""
    # Reuse RDS walk for normalPosList + any embedded advancedCurveList / startPos-endPos curves
    curves_rds, pts = rds_scene.extract_geom(js, points_only=points_only)
    if points_only:
        return [], pts

    curves = list(curves_rds)
    byname = {}
    for m in _maps(js):
        for p in _list(m, "points"):
            n = _name(p); xy = _xy_pair(p)
            if n and xy: byname[n] = xy

    for m in _maps(js):
        for pa in _list(m, "paths"):
            if _rds_shaped_curve(pa):
                continue  # already tessellated by rds_scene.extract_geom
            p0, p1, a, b = _path_endpoints(pa, byname)
            if not p0 or not p1: continue
            cls = str(_first(pa, "className", "curveType", "type") or "Straight")
            c1, c2, c3 = _controls(pa)
            pl = rds_scene.tessellate(cls, p0, p1, c1, c2, c3)
            name = str(_first(pa, "instanceName", "name", "id") or ("%s-%s" % (a, b)))
            curves.append({"n": name, "c": cls, "p": [[round(x, 3), round(y, 3)] for x, y in pl]})
    return curves, pts
