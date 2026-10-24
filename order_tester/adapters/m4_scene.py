# -*- coding: utf-8 -*-
"""M4 scene parsing from GET /api/fleet/scenes/schema/{sceneId}: structure.areas[].mergedMap {points, paths, bins}.
MapPoint / MapPath / SceneBin layouts are not fully documented, so every field is looked up under several names and
unknown fields are ignored. Output matches rds_scene.parse_scene (stations) / parse_groups / extract_geom."""
import math

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
        if is_lm(n, p["type"]): continue
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

def extract_geom(js, points_only=False):
    pts = []; curves = []; byname = {}
    for m in _maps(js):
        for p in _list(m, "points"):
            x, y = _xy(p)
            if x is not None and y is not None: pts.append((x, y)); byname[_name(p)] = (x, y)
    if points_only: return [], pts
    for m in _maps(js):
        for pa in _list(m, "paths"):
            a = _ref(_first(pa, "fromPointName", "from", "startPointName", "start", "startPos", "fromPoint"))
            b = _ref(_first(pa, "toPointName", "to", "endPointName", "end", "endPos", "toPoint"))
            if a in byname and b in byname:
                curves.append({"n": "%s-%s" % (a, b), "c": "M4Path", "p": [list(byname[a]), list(byname[b])]})
    return curves, pts
