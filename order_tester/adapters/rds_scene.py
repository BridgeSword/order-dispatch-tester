# -*- coding: utf-8 -*-
"""RDS scene / .smap parsing (stations, pre-point derivation, routes, point cloud, robot groups)."""
import io, json, math, zipfile

# ---------- scene parsing ----------
ANGLE_KEYS = ("dir", "angle", "theta", "yaw")

def parse_scene(js):
    pts = {}; curves = []
    def walk(o):
        if isinstance(o, dict):
            name = o.get("instanceName"); cls = o.get("className")
            if name and isinstance(o.get("pos"), dict) and cls and not isinstance(o.get("startPos"), dict):
                p = pts.setdefault(name, {"name": name, "type": cls, "x": o["pos"].get("x"), "y": o["pos"].get("y"), "bins": [], "props": {}})
                for ak in ANGLE_KEYS:  # station heading (RDS: "dir", radians); kept only if numeric
                    av = o.get(ak)
                    if isinstance(av, (int, float)) and not isinstance(av, bool) and "dir" not in p:
                        p["dir"] = round(float(av), 6); p["dirDeg"] = round(math.degrees(float(av)), 1); p["dirField"] = ak
                        break
                if o.get("ignoreDir") is True and "dir" in p: p["ignoreDir"] = True
                for prop in o.get("property", []) or []:
                    if isinstance(prop, dict) and prop.get("key"):
                        v = prop.get("stringValue")
                        if v is None:
                            v = next((prop[k] for k in prop if k.endswith("Value") and k != "stringValue"), None)
                        p["props"][prop["key"]] = v
            sp, ep = o.get("startPos"), o.get("endPos")
            if isinstance(sp, dict) and isinstance(ep, dict) and sp.get("instanceName") and ep.get("instanceName"):
                curves.append((sp["instanceName"], ep["instanceName"]))
            if cls == "GeneralLocation" or ("pointName" in o and name and "pos" not in o):
                pn = o.get("pointName")
                if pn:
                    p = pts.setdefault(pn, {"name": pn, "type": "?", "x": None, "y": None, "bins": [], "props": {}})
                    p["bins"].append(name)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(js)
    # 前置点推导: 1) 站点属性里名字含 pre 的值; 2) 曲线 LM->AP (驶入); 3) 曲线 AP->LM; 多个取最近
    def is_lm(n): return n in pts and (n.startswith("LM") or "LocationMark" in str(pts[n]["type"]))
    def dist(a, b):
        A, B = pts.get(a), pts.get(b)
        if not A or not B or A["x"] is None or B["x"] is None: return 1e9
        return ((A["x"]-B["x"])**2 + (A["y"]-B["y"])**2) ** 0.5
    for n, p in pts.items():
        pre = None; src = ""
        for k, v in p["props"].items():
            if "pre" in k.lower() and isinstance(v, str) and v.strip() in pts and v.strip() != n:
                pre = v.strip(); src = "property:" + k; break
        into = sorted({a for a, b in curves if b == n and a != n}, key=lambda a: dist(a, n))
        outof = sorted({b for a, b in curves if a == n and b != n}, key=lambda b: dist(b, n))
        cands = [c for c in into if is_lm(c)] or [c for c in outof if is_lm(c)] or into or outof
        p["preCands"] = list(dict.fromkeys(([pre] if pre else []) + cands))
        # every candidate with direction / distance / LM flag, in default preference order:
        # property, drive-in LM, drive-out LM, drive-in other, drive-out other (nearest first inside each group)
        info, seen = [], set()
        def add(c, d):
            if c in seen: return
            seen.add(c); info.append({"name": c, "dir": d, "dist": round(dist(c, n), 3) if dist(c, n) < 1e9 else None, "lm": bool(is_lm(c))})
        if pre: add(pre, "prop")
        for c in into:
            if is_lm(c): add(c, "in")
        for c in outof:
            if is_lm(c): add(c, "out")
        if not info:  # non-LM neighbours (e.g. an AP-AP link) only when there is no LM candidate at all
            for c in into: add(c, "in")
            for c in outof: add(c, "out")
        for c in info: c["src"] = "property" if c["dir"] == "prop" else ("curve-in" if c["dir"] == "in" else "curve-out")
        p["preInfo"] = info
        if not pre and cands: pre = cands[0]; src = "curve-in" if pre in into else "curve-out"
        p["pre"] = pre or ""; p["preSrc"] = src
        p.pop("props", None)
    return sorted(pts.values(), key=lambda p: p["name"])

# ---------- 地图几何: 路线 + 点云 ----------
def _xy(p):
    if isinstance(p, dict):
        if isinstance(p.get("pos"), dict): p = p["pos"]
        if "x" in p or "y" in p:
            return (float(p.get("x") or 0), float(p.get("y") or 0))
    return None

def tessellate(cls, p0, p1, c1=None, c2=None, c3=None, n=16):
    cls = cls or ""
    if "Arc" in cls and c1:  # 圆弧: 起点/c1(弧上点)/终点 三点定圆
        (ax, ay), (bx, by), (cx, cy) = p0, c1, p1
        d = 2 * (ax*(by-cy) + bx*(cy-ay) + cx*(ay-by))
        if abs(d) > 1e-9:
            ux = ((ax*ax+ay*ay)*(by-cy) + (bx*bx+by*by)*(cy-ay) + (cx*cx+cy*cy)*(ay-by)) / d
            uy = ((ax*ax+ay*ay)*(cx-bx) + (bx*bx+by*by)*(ax-cx) + (cx*cx+cy*cy)*(bx-ax)) / d
            r = math.hypot(ax-ux, ay-uy); t0 = math.atan2(ay-uy, ax-ux); tm = math.atan2(by-uy, bx-ux); t1 = math.atan2(cy-uy, cx-ux)
            def norm(a): return a % (2*math.pi)
            sweep = norm(t1 - t0)
            if norm(tm - t0) > sweep: sweep -= 2*math.pi  # 经过 c1 的方向
            return [(ux + r*math.cos(t0 + sweep*i/n), uy + r*math.sin(t0 + sweep*i/n)) for i in range(n+1)]
        return [p0, p1]
    ctrl = [c for c in (c1, c2, c3) if c]
    if "Straight" in cls or not ctrl: return [p0, p1]
    pts = [p0] + ctrl + [p1]  # Bezier / DegenerateBezier / NURBS(近似): de Casteljau
    out = []
    for i in range(n+1):
        t = i / n; q = pts[:]
        while len(q) > 1: q = [((1-t)*a[0]+t*b[0], (1-t)*a[1]+t*b[1]) for a, b in zip(q, q[1:])]
        out.append(q[0])
    return out

def extract_geom(js, points_only=False):
    """points_only: skip route tessellation (routes already known from /scene)"""
    curves, pts = [], []
    def walk(o):
        if isinstance(o, dict):
            sp, ep = o.get("startPos"), o.get("endPos")
            if not points_only and isinstance(sp, dict) and isinstance(ep, dict) and o.get("className") and _xy(sp) and _xy(ep) and isinstance(sp.get("pos"), dict):
                pl = tessellate(o.get("className"), _xy(sp), _xy(ep), _xy(o.get("controlPos1")), _xy(o.get("controlPos2")), _xy(o.get("controlPos3")))
                curves.append({"n": o.get("instanceName", ""), "c": o.get("className"), "p": [[round(x, 3), round(y, 3)] for x, y in pl]})
            npl = o.get("normalPosList")
            if isinstance(npl, list):
                for q in npl:
                    if isinstance(q, dict): pts.append((float(q.get("x") or 0), float(q.get("y") or 0)))
            for k, v in o.items():
                if k != "normalPosList": walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(js)
    return curves, pts

def point_dirs(js):
    """{point name: (dir radians, ignoreDir)} from a scene/.smap JSON. A map point without 'dir' has heading 0
    (the field is omitted when 0), so every point found gets a value."""
    out = {}
    def walk(o):
        if isinstance(o, dict):
            n = o.get("instanceName")
            if n and o.get("className") and isinstance(o.get("pos"), dict) and not isinstance(o.get("startPos"), dict) and n not in out:
                v = next((o[k] for k in ANGLE_KEYS if isinstance(o.get(k), (int, float)) and not isinstance(o.get(k), bool)), 0.0)
                out[n] = (float(v), o.get("ignoreDir") is True)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(js)
    return out

def downsample(pts, maxn=200000):
    cell = 0.05
    while True:
        seen = {}
        for x, y in pts:
            k = (int(math.floor(x / cell)), int(math.floor(y / cell)))
            if k not in seen: seen[k] = (x, y)
        if len(seen) <= maxn: return list(seen.values()), cell
        cell *= 1.5

def geom_bounds(curves, pts, stations=()):
    xs, ys = [], []
    if pts: xs += [p[0] for p in pts]; ys += [p[1] for p in pts]
    for c in curves:
        for x, y in c["p"]: xs.append(x); ys.append(y)
    for st in stations:
        if st.get("x") is not None: xs.append(st["x"]); ys.append(st["y"])
    if not xs: return None
    return {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}

def decode_smap(raw, depth=0):
    """.smap 可能是纯 JSON, 也可能是 zip 包(内含 N.smap JSON + .3dsmap/.3dfeature protobuf + info.json), 或 gzip. 返回 JSON 对象列表"""
    if raw[:2] == b"PK" and depth < 3:
        out = []; zf = zipfile.ZipFile(io.BytesIO(raw))
        for nm in zf.namelist():
            if nm.lower().endswith(".smap"): out += decode_smap(zf.read(nm), depth + 1)
        return out
    if raw[:2] == b"\x1f\x8b":
        import gzip; raw = gzip.decompress(raw)
    try:
        js = json.loads(raw.decode("utf-8-sig"))
        return [js] if isinstance(js, dict) else []
    except Exception: return []

def parse_groups(js):
    """场景 robotGroup: [{name, robot:[{id}]}] (可能包在 {"scene": {...}} 里)"""
    sc = js.get("scene") if isinstance(js, dict) and isinstance(js.get("scene"), dict) else js
    out = []
    for g in (sc.get("robotGroup") or []) if isinstance(sc, dict) else []:
        if isinstance(g, dict) and g.get("name"):
            out.append({"name": g["name"], "robots": [r.get("id") for r in (g.get("robot") or []) if isinstance(r, dict) and r.get("id")]})
    return out

