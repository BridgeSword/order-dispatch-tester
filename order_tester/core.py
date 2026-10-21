# -*- coding: utf-8 -*-
"""Dispatcher-neutral core: settings, templates, drafts, batches, polling, stuck detection.
All dispatcher I/O goes through ``S["adapter"]`` (see adapters/base.py)."""
import datetime, io, json, math, os, random, sys, threading, time, uuid, zipfile
from . import templates as T
from .adapters import get_adapter
from .adapters import rds_scene
from . import i18n

lock = threading.RLock()
DRAFT = "待下发"            # draft state value (kept as-is for compatibility with existing drafts.json/sent_orders.json)
MOVE_EPS_M = 0.05           # vehicle moved more than this (m) -> order counts as changed
MOVE_EPS_DEG = 2.0          # heading changed more than this (deg) -> order counts as changed
MOVE_LOG_SEC = 30           # order_move log throttle per order
HIST_GAP_SEC = 900          # legacy orders without batch: new group if send gap > this
HIST_CREATED_SEC = 60       # ... or created differs by more than this

S = {"running": False, "sent": 0, "cfg": {}, "orders": {}, "robots": {}, "robots_raw": None, "msg": "", "prepoints": {}, "geom": None,
     "groups": [], "robot_group": {}, "groups_try": 0, "odcache": {}, "opos": {}, "omovelog": {}, "adapter": None}
P = {}  # paths

def init(data_dir, adapter="rds", base="http://127.0.0.1:8088"):
    P["data"] = os.path.abspath(data_dir); os.makedirs(P["data"], exist_ok=True)
    P["logs"] = os.path.join(P["data"], "logs"); os.makedirs(P["logs"], exist_ok=True)
    P["settings"] = os.path.join(P["data"], "settings.json")
    P["drafts"] = os.path.join(P["data"], "drafts.json")
    P["sent"] = os.path.join(P["data"], "sent_orders.json")
    P["smap_cache"] = os.path.join(P["data"], "pointcloud_cache.json")
    P["maps"] = os.path.join(P["data"], "maps")
    P["scene_cache"] = os.path.join(P["data"], "scene_cache.json")
    P["log"] = os.path.join(P["logs"], "rds_%s.jsonl" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    S["store"] = T.Store(os.path.join(P["data"], "templates"))
    S["adapter"] = get_adapter(adapter, base, log)
    restore_scene_cache()

def AD(): return S["adapter"]
def TERMINAL(): return AD().terminal_states
def msg(key, **kw): return i18n.t(load_settings().get("lang") or "zh", key, **kw)

# ---------------------------------------------------------------- settings
def load_settings():
    try:
        with open(P["settings"], encoding="utf-8") as f: d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception: return {}

def save_settings(part):
    """merge into settings.json: only the given keys are updated"""
    if not isinstance(part, dict) or not part: return
    with lock:
        cur = load_settings()
        for k, v in part.items():
            if isinstance(v, dict) and isinstance(cur.get(k), dict) and k not in ("pools", "pmPool"): cur[k].update(v)
            else: cur[k] = v
        tmp = P["settings"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(cur, f, ensure_ascii=False, indent=1)
        os.replace(tmp, P["settings"])

VS_ROLES = ["pre", "s", "script", "e", "lift"]

def migrate_vs_settings():
    """very old: global vs_on/vs_head/vs_tail + vsBlocks -> vsPerBlock (only once)"""
    st = load_settings()
    if not st or isinstance(st.get("vsPerBlock"), dict) or not isinstance(st.get("fields"), dict): return False
    f = st.get("fields") or {}
    def num(v, d=1.539):
        try: return float(v)
        except Exception: return d
    on = f.get("vs_on")
    if on is None and str(f.get("vs") or "").strip():
        try:
            v = json.loads(f["vs"]); on = isinstance(v, dict); f = dict(f, vs_head=v.get("head", 1.539), vs_tail=v.get("tail", 1.539))
        except Exception: on = False
    vsb = st.get("vsBlocks") if isinstance(st.get("vsBlocks"), list) else ["e", "lift"]
    h, t = num(f.get("vs_head")), num(f.get("vs_tail"))
    save_settings({"vsPerBlock": {r: {"on": bool(on) and r in vsb, "head": h, "tail": t} for r in VS_ROLES}})
    return True

def migrate_templates():
    """legacy settings.json (fixed five-block form) -> templates/default.json + settings.pools/activeTemplate. Idempotent."""
    st = load_settings(); notes = []
    store = S["store"]
    if "default" not in store.names():
        t = T.from_legacy_settings(st) if st else None
        store.put(t or T.builtin_default()); notes.append("templates/default.json created" + (" from legacy settings" if t else ""))
    part = {}
    if not isinstance(st.get("pools"), dict):
        part["pools"] = {"start": list(st.get("starts") or []), "end": list(st.get("ends") or [])}
        notes.append("pools migrated from starts/ends")
    if not st.get("activeTemplate"): part["activeTemplate"] = "default"
    if part:
        if os.path.exists(P["settings"]) and not os.path.exists(P["settings"] + ".bak-v1"):
            import shutil; shutil.copy2(P["settings"], P["settings"] + ".bak-v1")
        save_settings(part)
    return notes

# ---------------------------------------------------------------- log
def log(kind, **kw):
    kw.update(ts=time.time(), t=datetime.datetime.now().isoformat(timespec="milliseconds"), kind=kind)
    with lock, open(P["log"], "a", encoding="utf-8") as f: f.write(json.dumps(kw, ensure_ascii=False) + "\n")

def set_base(url):
    if url: AD().base = url

# ---------------------------------------------------------------- scene
def set_groups(js):
    gs = AD().parse_groups(js)
    if gs:
        with lock: S["groups"] = gs; S["robot_group"] = {rid: g["name"] for g in gs for rid in g["robots"]}

def load_scene_stations():
    st, js, txt = AD().scene()
    if js is None: return None, "/scene %s %s" % (st, txt[:200])
    try: set_groups(js); stations = AD().parse_stations(js)
    except Exception as e: return None, "/scene parse error: %s" % e
    S["st_cache"] = (time.time(), stations)
    with lock: S["prepoints"] = {p["name"]: p["pre"] for p in stations if p.get("pre")}
    return stations, ""

def ensure_prepoints():
    if not S["prepoints"]:
        st, err = load_scene_stations()
        return err
    return ""

def load_smap(path):
    stt = os.stat(path); key = [os.path.abspath(path), stt.st_mtime, stt.st_size]
    try:
        with open(P["smap_cache"], encoding="utf-8") as f: c = json.load(f)
        if c.get("key") == key: return c["curves"], [tuple(p) for p in c["points"]], c.get("cell")
    except Exception: pass
    with open(path, "rb") as f: raw = f.read()
    curves, pts = [], []
    for js in AD().decode_map(raw):
        c, p = AD().extract_geom(js); curves += c; pts += p
    if not curves and not pts: raise ValueError("no 2D map JSON in file")
    pts, cell = rds_scene.downsample(pts)
    pts = [(round(x, 3), round(y, 3)) for x, y in pts]
    try:
        with open(P["smap_cache"], "w", encoding="utf-8") as f: json.dump({"key": key, "curves": curves, "points": pts, "cell": cell}, f)
    except Exception as e: log("smap_cache_err", err=str(e))
    return curves, pts, cell

def _apply_geom(g):
    """make a successfully loaded scene the current one (memory)"""
    with lock:
        S["geom"] = g; st = g.get("stations") or []
        if st: S["prepoints"] = {q["name"]: q["pre"] for q in st if q.get("pre")}; S["st_cache"] = (g.get("loadedAt") or time.time(), st)
        gs = g.get("groups") or []
        if gs: S["groups"] = gs; S["robot_group"] = {rid: x["name"] for x in gs for rid in x["robots"]}

def save_scene_cache(g):
    try:
        tmp = P["scene_cache"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(g, f, ensure_ascii=False)
        os.replace(tmp, P["scene_cache"])
    except Exception as e: log("scene_cache_save_fail", err=str(e))

def restore_scene_cache():
    """last successful scene load survives page reloads and server restarts"""
    try:
        with open(P["scene_cache"], encoding="utf-8") as f: g = json.load(f)
        if isinstance(g, dict) and g.get("ok") and g.get("stations"): g["fromCache"] = True; _apply_geom(g); return True
    except FileNotFoundError: pass
    except Exception as e: log("scene_cache_load_fail", err=str(e))
    return False

SCENE_JOB = {}  # the one scene-load job: {id, stage, done, total, t0, t, finished, result}

def start_scene_job(refresh=False):
    """run build_geom in the background; concurrent callers share the running job"""
    with lock:
        j = SCENE_JOB
        if j and not j.get("finished"): return j["id"]
        jid = uuid.uuid4().hex[:12]
        SCENE_JOB.clear(); SCENE_JOB.update(id=jid, stage="request", done=None, total=None, t0=time.time(), t=time.time(), finished=False, result=None)
    def prog(stage, done=None, total=None):
        if SCENE_JOB.get("id") != jid: return
        SCENE_JOB.update(stage=stage, done=done, total=total, t=time.time())
    def run():
        try: g = build_geom(refresh=refresh, progress=prog)
        except Exception as e: g = {"ok": False, "err": str(e)}
        SCENE_JOB.update(finished=True, result=g, stage="done" if g.get("ok") and not g.get("sceneErr") else "failed", t=time.time())
    threading.Thread(target=run, daemon=True).start()
    return jid

def scene_job_status(jid):
    j = dict(SCENE_JOB)
    if not j or j.get("id") != jid: return {"ok": False, "err": "unknown job"}
    j["ok"] = True; j["elapsed"] = round(time.time() - j["t0"], 1)
    if not j["finished"]: j.pop("result", None)
    return j

def build_geom(refresh=False, progress=None):
    prog = progress or (lambda *a, **k: None)
    notes = []; curves, pts, cell = [], [], None; psrc = ""; csrc = ""; stations = []
    st, js, txt = AD().scene(progress=prog)
    scene_err = ""
    if js is not None:
      try:
        prog("parse")
        set_groups(js)
        curves, p0 = AD().extract_geom(js); stations = AD().parse_stations(js)
        csrc = "/scene" if curves else ""
        prog("pointcloud")
        if p0: pts, cell = rds_scene.downsample(p0); psrc = "/scene normalPosList"
        else: notes.append("/scene: no point cloud (normalPosList)")
      except Exception as e:
        scene_err = "/scene parse error: %s" % e; js = None; curves, stations = [], []; notes.append(scene_err)
    else: scene_err = "/scene %s %s" % (st, txt[:200]); notes.append("/scene failed: %s %s" % (st, txt[:120]))
    smap = load_settings().get("smapPath")
    if not pts and smap:
        if os.path.isfile(smap):
            try:
                c2, pts, cell = load_smap(smap); psrc = "smap: " + smap
                if not curves and c2: curves = c2; csrc = "smap: " + smap
            except Exception as e: notes.append("smap parse failed %s: %s" % (smap, e))
        else: notes.append("smapPath not found: " + smap)
    auto = load_settings().get("smapAuto")
    if not pts and auto and os.path.isfile(auto) and not refresh:
        try:
            c2, pts, cell = load_smap(auto); psrc = "/downloadScene (cache " + os.path.basename(auto) + ")"
            if not curves and c2: curves = c2; csrc = psrc
        except Exception as e: notes.append("cached map parse failed: %s" % e)
    if not pts and js is not None:
        code, raw = AD().download_maps()
        if code == 200 and raw[:2] == b"PK":
            try:
                zf = zipfile.ZipFile(io.BytesIO(raw)); seen = {}
                for nm in zf.namelist():
                    if nm.lower().endswith(".smap") and os.path.basename(nm) not in seen: seen[os.path.basename(nm)] = nm
                if seen:
                    os.makedirs(P["maps"], exist_ok=True)
                    if len(seen) == 1:
                        dst = os.path.join(P["maps"], "rds_" + next(iter(seen)))
                        with open(dst, "wb") as f: f.write(zf.read(next(iter(seen.values()))))
                    else:
                        dst = os.path.join(P["maps"], "rds_scene_maps.smap")
                        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
                            for b2, nm in seen.items(): out.writestr(b2, zf.read(nm))
                    save_settings({"smapAuto": dst})
                    c2, pts, cell = load_smap(dst); psrc = "/downloadScene (" + ", ".join(seen) + ")"
                    if not curves and c2: curves = c2; csrc = psrc
                else: notes.append("/downloadScene: zip without .smap")
            except Exception as e: notes.append("/downloadScene parse failed: %s" % e)
        else: notes.append("/downloadScene unavailable (HTTP %s)" % code)
    if not pts: notes.append("no point cloud: upload a .smap or set a local smap path on the Map tab")
    g = {"ok": True, "curves": curves, "points": [c for p in pts for c in p], "npoints": len(pts), "cell": cell,
         "bounds": rds_scene.geom_bounds(curves, pts, stations), "stations": stations, "pointSrc": psrc, "curveSrc": csrc, "notes": notes, "sceneErr": scene_err}
    if not scene_err:
        prog("cache")
        g["loadedAt"] = time.time(); g["groups"] = S.get("groups") or []
        _apply_geom(g); save_scene_cache(g)
    elif not S.get("geom"): S["geom"] = g   # keep the last good scene on failure
    log("geom", npoints=len(pts), ncurves=len(curves), pointSrc=psrc, curveSrc=csrc, notes=notes)
    return g

def load_groups_bg():
    st, js, _ = AD().scene()
    if js is not None: set_groups(js)

def order_state(oid):
    """current order state with light cache (active 5 s, terminal 10 min)"""
    now = time.time(); c = S["odcache"].get(oid)
    if c and now - c[1] < (600 if c[0] in TERMINAL() else 5): return c[0]
    r = AD().order_status(oid, timeout=5)
    state = (r or {}).get("state") or ""
    S["odcache"][oid] = (state or "?", now)
    if len(S["odcache"]) > 500:
        for k in sorted(S["odcache"], key=lambda k: S["odcache"][k][1])[:200]: S["odcache"].pop(k, None)
    return state or "?"

def pre_point(name, cfg):
    ov = cfg.get("preOverrides") or {}
    if ov.get(name): return ov[name]
    return S["prepoints"].get(name, "")

# ---------------------------------------------------------------- templates / cfg
def resolve_template(b):
    """request -> template. Accepts {template: obj}, {templateName}, or the legacy flat form (startOp/...)."""
    if isinstance(b.get("template"), dict):
        t = json.loads(json.dumps(b["template"])); errs = T.validate(t)
        if errs: raise ValueError("; ".join(errs))
        return t
    if "startOp" in b or "scriptOn" in b: return T.from_legacy_cfg(b)
    name = b.get("templateName") or load_settings().get("activeTemplate") or "default"
    t = S["store"].get(name)
    if t is None: raise ValueError("template not found: " + name)
    return t

def cfg_pools(b, t):
    """{pool: [stations]} for the template's pools (deduplicated). Legacy startPool/endPool accepted."""
    pools = dict(b.get("pools") or {})
    if b.get("startPool") is not None: pools["start"] = b["startPool"]
    if b.get("endPool") is not None: pools["end"] = b["endPool"]
    return {r: list(dict.fromkeys(pools.get(r) or [])) for r in T.pool_roles(t)}

def prepare_cfg(b):
    """validate pools + pre-points. returns (cfg, template, pools, warn, err)"""
    set_base(b.get("base"))
    try: t = resolve_template(b)
    except ValueError as e: return b, None, {}, "", str(e)
    pools = cfg_pools(b, t); roles = T.pool_roles(t)
    if not roles: return b, t, pools, "", msg("srv.noPoolStep")
    empty = [r for r in roles if not pools[r]]
    if empty: return b, t, pools, "", msg("srv.poolEmpty", pools=", ".join(empty))
    if b.get("noSelf", True) and len(roles) > 1 and all(len(pools[r]) == 1 for r in roles) and len({pools[r][0] for r in roles}) < len(roles):
        return b, t, pools, "", msg("srv.sameOnly")
    warn = []
    need = T.needed_pre_roles(t)
    if need:
        err = ensure_prepoints()
        if err and not S["prepoints"] and not b.get("preOverrides"): return b, t, pools, "", msg("srv.sceneFail", err=err)
        for r in roles:
            if r not in need: continue
            miss = sorted({x for x in pools[r] if not pre_point(x, b)})
            if miss:
                warn.append(msg("srv.noPre", pool=r, list=", ".join(miss))); log("no_prepoint", pool=r, stations=miss)
                pools[r] = [x for x in pools[r] if x not in miss]
                if not pools[r]: return b, t, pools, "", "\n".join(warn) + " " + msg("srv.poolNowEmpty", pool=r)
    return b, t, pools, "\n".join(warn), ""

def make_draft(picks, t, cfg, oid=None):
    """neutral order -> adapter payload -> draft record (ValueError: missing pre-point)"""
    order = T.build_order(t, picks, cfg, lambda n: pre_point(n, cfg), oid)
    body = AD().build_payload(order)
    roles = T.pool_roles(t)
    g = lambda x: "%g" % x if isinstance(x, (int, float)) else str(x)
    vsTag = ",".join("%s%s/%s" % (st["name"], g(st["variableShape"].get("head")), g(st["variableShape"].get("tail")))
                     for st in order["steps"] if isinstance(st.get("variableShape"), dict))
    first, last = (picks.get(roles[0], ""), picks.get(roles[-1], "")) if roles else ("", "")
    now = time.time(); dpre = pre_point(last, cfg)
    return {"id": body["id"], "pair": [picks[r] for r in roles], "picks": dict(picks), "template": t.get("name"), "adapter": AD().name,
            "pre": dpre, "dropPre": dpre, "pickPre": pre_point(first, cfg),
            "vsTag": vsTag, "vehicle": body.get("vehicle", ""), "group": body.get("group", ""), "state": DRAFT,
            "sent": now, "changed": now, "created": now, "sig": "", "error": None, "body": body}

def preview(b):
    """sample order for the template editor: first station of each pool (or placeholders)"""
    t = resolve_template(b); roles = T.pool_roles(t); pools = cfg_pools(b, t)
    picks = {}
    for i, r in enumerate(roles):
        cand = [x for x in pools.get(r, []) if x not in picks.values()] or pools.get(r) or ["<%s>" % r]
        picks[r] = cand[0]
    def pre(n): return pre_point(n, b) or ("<pre:%s>" % n if b.get("placeholderPre", True) else "")
    order = T.build_order(t, picks, b, pre, "dl-preview")
    return {"ok": True, "picks": picks, "order": order, "payload": AD().build_payload(order)}

# ---------------------------------------------------------------- persistence
def is_active(o): return o["state"] not in TERMINAL() and o["state"] != DRAFT and not o.get("error")
def count_active(): return sum(1 for o in S["orders"].values() if is_active(o))

def _upgrade_record(o):
    """old records (start/end only) -> picks/template/adapter"""
    if not isinstance(o.get("picks"), dict):
        pr = o.get("pair") if isinstance(o.get("pair"), list) else []
        o["picks"] = {"start": pr[0] if len(pr) > 0 else "?", "end": pr[1] if len(pr) > 1 else "?"}
    o.setdefault("template", "default"); o.setdefault("adapter", "rds")
    return o

def save_drafts():
    with lock:
        d = [o for o in S["orders"].values() if o["state"] == DRAFT]
        tmp = P["drafts"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, P["drafts"])

_sent_sig = [None]
def save_sent():
    try:
        with lock: d = [o for o in S["orders"].values() if o["state"] != DRAFT]
        sig = json.dumps([(o["id"], o["state"], o.get("sig"), o.get("changed"), o.get("vehicle"), o.get("error"), o.get("started"), o.get("ended"), o.get("assigned"), o.get("batch")) for o in d], ensure_ascii=False)
        if sig == _sent_sig[0]: return
        tmp = P["sent"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, P["sent"]); _sent_sig[0] = sig
    except Exception as e: print("save_sent error:", e, flush=True)

def load_sent():
    try:
        with open(P["sent"], encoding="utf-8-sig") as f: d = json.load(f)
    except Exception: return 0
    n = 0
    with lock:
        for o in d:
            if not isinstance(o, dict) or not o.get("id") or o.get("state") == DRAFT or o["id"] in S["orders"]: continue
            for k in ("age", "idle"): o.pop(k, None)
            if o.get("state") not in TERMINAL() and o.get("ended"):  # old versions treated FAILED as terminal
                for k in ("ended", "endedSrc", "_tfill"): o.pop(k, None)
                o["_reopened"] = True
            now = time.time()
            for k, v in (("pair", ["?", "?"]), ("vehicle", ""), ("sig", ""), ("error", None), ("sent", now), ("changed", now), ("pre", "")): o.setdefault(k, v)
            S["orders"][o["id"]] = _upgrade_record(o); n += 1
    try: assign_hist_batches()
    except Exception as e: print("assign_hist_batches error:", e, flush=True)
    return n

def load_drafts():
    try:
        with open(P["drafts"], encoding="utf-8-sig") as f: d = json.load(f)
        with lock:
            for o in d:
                if isinstance(o, dict) and o.get("id") and o.get("state") == DRAFT: S["orders"][o["id"]] = _upgrade_record(o)
        return len(d)
    except Exception: return 0

# ---------------------------------------------------------------- batches
def _max_batch_no():
    return max([o["batchMeta"].get("no", 0) for o in S["orders"].values() if isinstance(o.get("batchMeta"), dict)] + [0])

def new_batch(ids, interval=None, max_active=None, kind="send", group=""):
    with lock: no = _max_batch_no() + 1
    return {"id": "b%d-%s" % (no, uuid.uuid4().hex[:6]), "no": no, "name": "#%d" % no, "start": time.time(), "n": len(ids),
            "interval": interval, "maxActive": max_active, "group": group, "kind": kind}

def _log_send_batches():
    out = []
    try: files = sorted(f for f in os.listdir(P["logs"]) if f.endswith(".jsonl"))
    except Exception: return out
    for fn in files:
        try:
            with open(os.path.join(P["logs"], fn), encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"send_batch"' not in line: continue
                    try: e = json.loads(line)
                    except Exception: continue
                    if e.get("kind") == "send_batch" and isinstance(e.get("ids"), list):
                        out.append((e.get("ts") or 0, e["ids"], e.get("interval"), e.get("maxActive")))
        except Exception: pass
    return sorted(out, key=lambda x: x[0])

def assign_hist_batches():
    with lock: todo = {k: o for k, o in S["orders"].items() if o["state"] != DRAFT and not o.get("batch")}
    if not todo: return 0
    groups = []
    for ts_, ids, iv, ma in reversed(_log_send_batches()):
        g = [i for i in ids if i in todo]
        if g:
            groups.append((g, "log", iv, ma))
            for i in g: todo.pop(i)
    rest = sorted(todo.values(), key=lambda o: o.get("sent") or 0); cur = []; prev = None
    for o in rest:
        if prev and ((o.get("sent") or 0) - (prev.get("sent") or 0) > HIST_GAP_SEC or
                     abs((o.get("created") or o.get("sent") or 0) - (prev.get("created") or prev.get("sent") or 0)) > HIST_CREATED_SEC):
            groups.append(([x["id"] for x in cur], "gap", None, None)); cur = []
        cur.append(o); prev = o
    if cur: groups.append(([x["id"] for x in cur], "gap", None, None))
    with lock:
        first = lambda g: min((S["orders"][i].get("sent") or 0) for i in g[0])
        base = _max_batch_no()
        for k, g in enumerate(sorted(groups, key=first), 1):
            ids, src, iv, ma = g; no = base + k
            grp = sorted({(S["orders"][i].get("body") or {}).get("group", "") for i in ids} - {""})
            meta = {"id": "h%d-%s" % (no, uuid.uuid4().hex[:6]), "no": no, "name": "#%d" % no, "start": first(g), "n": len(ids),
                    "interval": iv, "maxActive": ma, "group": ",".join(grp), "kind": "hist", "src": src}
            for i in ids: S["orders"][i]["batch"] = meta["id"]; S["orders"][i]["batchMeta"] = dict(meta)
    log("assign_hist_batches", n=len(groups), src={s_: sum(1 for g in groups if g[1] == s_) for s_ in ("log", "gap")})
    return len(groups)

def backfill_times():
    with lock: ids = [k for k, o in S["orders"].items() if o["state"] in TERMINAL() and not o.get("error") and o["state"] != "SKIPPED"
                      and (not o.get("ended") or not o.get("started")) and not o.get("_tfill")]
    for oid in ids:
        js = AD().order_status(oid)
        if js is None: continue
        bst = js.get("blockStartTimes") or []
        started = min(bst) if bst else js.get("receiveTime") or js.get("createTime")
        ended = js.get("terminateTime") or js.get("finishTime")
        with lock:
            o = S["orders"].get(oid)
            if not o: continue
            o["_tfill"] = True
            if started and not o.get("started"): o["started"] = started; o["startedSrc"] = "rds"
            if ended and not o.get("ended"): o["ended"] = ended; o["endedSrc"] = "rds"
        log("backfill_times", id=oid, started=started, ended=ended)

# ---------------------------------------------------------------- generate / swap / send
def generate_drafts(cfg, t, pools, rng=None, id_factory=None):
    ensure_prepoints()
    roles = T.pool_roles(t)
    picker = T.make_picker(cfg.get("strategy") or "random", [(r, pools[r]) for r in roles], cfg.get("noSelf", True), cfg.get("noReuse", True), rng)
    n = cfg.get("count"); n = picker.default_count() if n in (None, "") else int(n or 0)
    made, skipped = [], []
    for _ in range(n):
        try: picks = picker.next()
        except ValueError as e: skipped.append({"pair": [], "err": str(e)}); break
        try: rec = make_draft(picks, t, cfg, id_factory() if id_factory else None)
        except ValueError as e: skipped.append({"pair": [picks[r] for r in roles], "err": str(e)}); continue
        with lock: S["orders"][rec["id"]] = rec
        made.append(rec["id"])
    save_drafts()
    first = roles[0] if roles else None
    no_pick = sorted({s for s in pools.get("start", []) if not pre_point(s, cfg)}) if "start" in roles and "start" not in T.needed_pre_roles(t) else []
    log("generate", n=len(made), template=t.get("name"), strategy=cfg.get("strategy") or "random", ids=made, skipped=skipped, pools=pools,
        noSelf=cfg.get("noSelf"), noReuse=cfg.get("noReuse"))
    return {"n": len(made), "ids": made, "skipped": skipped, "noPickPre": no_pick}

def swap_drafts(ids, cfg, t):
    """swap the first and last pool picks of the selected drafts; rebuild (draft's own template, else t); keep id + group"""
    ensure_prepoints(); done, errs = [], []
    for oid in ids:
        with lock:
            o = S["orders"].get(oid)
            if not o or o["state"] != DRAFT: errs.append({"id": oid, "err": msg("srv.notDraft")}); continue
            if S["running"] and oid in S.get("batch", ()): errs.append({"id": oid, "err": msg("srv.inBatch")}); continue
            old = dict(_upgrade_record(o)["picks"])
            # rebuild with the draft's own template (current saved version); fall back to the given one
            tt = S["store"].get(o["template"]) if o.get("template") and o["template"] in S["store"].names() else t
            roles = T.pool_roles(tt)
            vals = [old.get(r, "") for r in roles]
            if len(vals) >= 2: vals[0], vals[-1] = vals[-1], vals[0]
            picks = dict(zip(roles, vals))
            ocfg = dict(cfg, group=(o.get("body") or {}).get("group", ""))
        try: rec = make_draft(picks, tt, ocfg, oid)
        except ValueError as e: errs.append({"id": oid, "pair": vals, "err": str(e)}); continue
        with lock:
            cur = S["orders"].get(oid)
            if not cur or cur["state"] != DRAFT: errs.append({"id": oid, "err": msg("srv.changed")}); continue
            rec["created"] = cur.get("created", rec["created"]); rec["swapped"] = cur.get("swapped", 0) + 1
            S["orders"][oid] = rec
        done.append({"id": oid, "pair": vals})
    save_drafts(); log("swap_drafts", done=done, errors=errs)
    return {"n": len(done), "done": done, "errors": errs}

def send_batch(ids, interval, max_active, meta=None):
    done = 0
    try:
        for oid in ids:
            while S["running"] and max_active and count_active() >= max_active: time.sleep(0.5)
            if not S["running"]: break
            with lock:
                o = S["orders"].get(oid)
                if not o or o["state"] != DRAFT: continue
                body = o["body"]
            ok, err = AD().submit(body)
            now = time.time()
            with lock:
                o.update(state="SENT" if ok else "SEND_FAIL", sent=now, changed=now, error=err)
                if meta: o["batch"] = meta["id"]; o["batchMeta"] = meta
                S["sent"] += 1; done += 1; S["msg"] = "%d/%d" % (done, len(ids))
            save_drafts()
            t_end = time.time() + interval
            while S["running"] and time.time() < t_end and oid != ids[-1]: time.sleep(0.1)
    finally:
        left = sum(1 for i in ids if i in S["orders"] and S["orders"][i]["state"] == DRAFT)
        S["running"] = False; S["msg"] = msg("srv.sendEnd", n=done) + (msg("srv.sendLeft", n=left) if left else "")
        log("send_batch_end", sent=done, left=left)

def dispatcher(t, pools):
    """auto mode (/api/start): generate + send continuously, keeping at most maxActive open"""
    cfg = S["cfg"]; roles = T.pool_roles(t)
    picker = T.make_picker(cfg.get("strategy") or "random", [(r, pools[r]) for r in roles], cfg.get("noSelf", True), cfg.get("noReuse", True))
    while S["running"] and S["sent"] < int(cfg["count"]):
        with lock: active = count_active()
        if active >= int(cfg.get("maxActive") or 1): time.sleep(0.5); continue
        picks = picker.next()
        try: rec = make_draft(picks, t, cfg)
        except ValueError as e:
            log("order_skip", picks=picks, err=str(e)); now = time.time(); sid = "skip-" + uuid.uuid4().hex[:8]
            with lock:
                S["orders"][sid] = {"id": sid, "pair": [picks[r] for r in roles], "picks": picks, "vehicle": "", "state": "SKIPPED", "sent": now, "changed": now, "sig": "", "error": str(e), "body": None}
                S["sent"] += 1
            continue
        ok, err = AD().submit(rec["body"]); now = time.time()
        rec.update(state="SENT" if ok else "SEND_FAIL", sent=now, changed=now, error=err, batch=(S.get("dbatch") or {}).get("id"), batchMeta=S.get("dbatch"))
        with lock: S["orders"][rec["id"]] = rec; S["sent"] += 1
        t_end = time.time() + float(cfg.get("interval") or 0)
        while S["running"] and time.time() < t_end: time.sleep(0.1)
    S["running"] = False; S["msg"] = msg("srv.autoEnd")

# ---------------------------------------------------------------- polling
def poll_once():
    TERM = TERMINAL()
    with lock: ids = [k for k, o in S["orders"].items() if is_active(o)]
    for oid in ids:
        js = AD().order_status(oid)
        if js is None: continue
        with lock:
            o = S["orders"][oid]
            new = {"state": js["state"] if js.get("state") is not None else o["state"], "vehicle": js.get("vehicle") or o["vehicle"]}
            bl = js.get("blockStates") or []
            bsig = ",".join(str(b) for b in bl)
            sig = "%s|%s|%s" % (new["state"], new["vehicle"], bsig)
            if sig != o["sig"]:
                o["changed"] = time.time(); log("order_change", id=oid, state=new["state"], vehicle=new["vehicle"], blocks=bsig)
            tnow = time.time()
            if js.get("vehicle") and not o.get("assigned"):
                if o.get("started"): o["assigned"] = o["started"]
                else: o["assigned"] = tnow; o["changed"] = tnow  # first assignment: idle counts from here
            o.update(new, sig=sig, blocks=bsig)
            if not o.get("started"):
                began = new["state"] == "RUNNING" or bool(js.get("vehicle")) or any(b not in (None, "", "CREATED") for b in bl)
                if began or new["state"] in TERM: o["started"] = tnow; o["startedSrc"] = "poll"
            if new["state"] in TERM and not o.get("ended"):
                rt = js.get("terminateTime") if o.get("_reopened") else None
                if rt and rt <= tnow: o["ended"] = rt; o["endedSrc"] = "rds"
                else: o["ended"] = tnow; o["endedSrc"] = "poll"
            elif new["state"] not in TERM and o.get("ended"):
                o.pop("ended", None); o.pop("endedSrc", None)
    rl = AD().robots()
    if rl is not None:
        now = time.time()
        if not S["groups"] and now - S["groups_try"] > 300:
            S["groups_try"] = now; threading.Thread(target=load_groups_bg, daemon=True).start()
        ost_map = {}
        for r in rl:
            if r.get("order"): ost_map[r["order"]] = r.get("orderState") or order_state(r["order"])
        with lock:
            S["robots_raw"] = True
            for r in rl:
                name = r["name"]; x, y = r.get("x"), r.get("y"); cur = r.get("order") or ""
                prev = S["robots"].get(name)
                moved = prev is None or prev["x"] is None or x is None or abs((x or 0) - (prev["x"] or 0)) + abs((y or 0) - (prev["y"] or 0)) > 0.05
                ost = ost_map.get(cur, "") if cur else ""
                S["robots"][name] = {"name": name, "x": x, "y": y, "station": r.get("station", ""), "order": cur,
                    "orderState": ost, "orderActive": bool(cur) and ost not in TERM,
                    "group": S["robot_group"].get(name) or r.get("group") or "",
                    "dispatchable": r.get("dispatchable"), "connected": r.get("connected"), "blocked": r.get("blocked"),
                    "battery": r.get("battery"), "angle": r.get("angle"), "moved": now if moved else prev["moved"]}
            # vehicle position/heading change also counts as order change
            byveh = {r["name"]: r for r in S["robots"].values()}
            for oid, o in S["orders"].items():
                if not is_active(o) or not o.get("vehicle") or not o.get("assigned"): S["opos"].pop(oid, None); continue
                rb2 = byveh.get(o["vehicle"])
                if not rb2 or rb2.get("x") is None or rb2.get("y") is None: continue
                if rb2.get("order") and rb2["order"] != oid: S["opos"].pop(oid, None); continue
                cur = (rb2["x"], rb2["y"], rb2.get("angle"))
                last = S["opos"].get(oid)
                if last is None or last[3] != o["vehicle"]: S["opos"][oid] = cur + (o["vehicle"],); continue
                d = math.hypot(cur[0] - last[0], cur[1] - last[1]); da = 0.0
                if cur[2] is not None and last[2] is not None:
                    da = abs((math.degrees(cur[2] - last[2]) + 180) % 360 - 180)
                if d > MOVE_EPS_M or da > MOVE_EPS_DEG:
                    o["changed"] = now; S["opos"][oid] = cur + (o["vehicle"],)
                    if now - S["omovelog"].get(oid, 0) >= MOVE_LOG_SEC:
                        S["omovelog"][oid] = now; log("order_move", id=oid, vehicle=o["vehicle"], x=cur[0], y=cur[1], angle=cur[2])

def poller():
    while True:
        try: poll_once()
        except Exception as e: log("poller_error", err=str(e))
        if time.time() - S.get("bf_t", 0) > 60:
            S["bf_t"] = time.time()
            try: backfill_times()
            except Exception as e: log("backfill_error", err=str(e))
        save_sent()
        time.sleep(float(S["cfg"].get("pollSec") or 2))
