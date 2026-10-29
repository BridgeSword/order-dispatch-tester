# -*- coding: utf-8 -*-
"""Tiny fake M4 fleet server for local testing (mock data only). python tools/fake_m4.py [--port 18090] [--no-auth]
Auth: headers xyy-app-id/xyy-app-key = APP_ID/APP_KEY, or POST /api/sign-in {username, password} = USER/PASSWORD
(sets a session cookie). Unauthenticated requests -> 401; wrong sign-in -> 400 {code, message}.
Scene "scene-1" ("Mock scene"): points AP1..AP12 + LM1..LM12, paths LMn->APn, bins BIN-n on APn, robot group grpA
(AMB-01, AMB-02), groupsMap mapFile for /api/fleet/scenes/{id}/download/{mapFile}. Unknown fields are sprinkled in on purpose
(the parser must ignore them). SCHEMA_CLOUD=False omits normalPosList so tests can exercise map download.
Orders: steps run one after another, STEP_DUR s each (a step starts when it exists and its predecessor is Done).
Status: ToBeAllocated -> Executing -> Pending (all steps done, not sealed: stepFixed=false) -> Done (sealed).
Like the doc example, stepIndex is returned as a string and rbkArgs as JSON text.
Order ids containing 'fault' -> while the 2nd step runs the order reports fault:true + faultReason for a while (status
stays Executing), then recovers and continues. 'qerr' -> query-order-detail answers 500 for a while after the 1st step.
'xcancel' -> the order is cancelled in M4 (as if by an operator) once its 1st step is Done.
POST cancel -> Cancelling for CANCEL_DUR s, then Cancelled. add-steps / complete-order on a sealed or terminal order ->
400. EVENTS records every add-steps/complete-order with the predecessor step status at that moment."""
import argparse, json, threading, time, urllib.parse, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

APP_ID, APP_KEY, USER, PASSWORD = "mock-app", "mock-key", "mockuser", "mockpass"
AUTH = True
SCENE_ID = "scene-1"
STEP_DUR = 0.4; CANCEL_DUR = 0.3
SCHEMA_CLOUD = True  # False: omit normalPosList so core must use map download
MAP_FILE = "robot-maps/mock.smap"
MAP_NAME = "mock.smap"
DOWNLOAD_MAP = b""  # bytes served by /api/fleet/scenes/{id}/download/{mapFile}; empty -> 404
ORDERS = {}; LOCK = threading.Lock(); RECEIVED = []; EVENTS = []; SESSIONS = set()

def schema():
    pts = []; paths = []; bins = []
    for i in range(1, 13):
        pts.append({"name": "AP%d" % i, "type": "ActionPoint", "x": i * 2.0, "y": 0.0, "dir": 1.5707963 if i % 2 else None, "mysteryField": {"a": 1}})
        pts.append({"name": "LM%d" % i, "type": "LocationMark", "x": i * 2.0, "y": 2.0, "zz": [1, 2]})
        if i <= 2:
            # Bezier with control point — tessellation must produce more than 2 vertices
            paths.append({"fromPointName": "LM%d" % i, "toPointName": "AP%d" % i, "curveType": "BezierPath",
                          "controlPos1": {"x": i * 2.0 + 1.0, "y": 1.0}, "unknown": True})
        elif i == 3:
            # RDS-shaped path embedded in mergedMap.paths (className + startPos/endPos/controlPos)
            paths.append({"className": "DegenerateBezierPath", "instanceName": "LM3-AP3",
                          "startPos": {"instanceName": "LM3", "pos": {"x": 6.0, "y": 2.0}},
                          "endPos": {"instanceName": "AP3", "pos": {"x": 6.0, "y": 0.0}},
                          "controlPos1": {"x": 7.0, "y": 1.0}})
        else:
            paths.append({"fromPointName": "LM%d" % i, "toPointName": "AP%d" % i, "curveType": "Straight", "unknown": True})
        bins.append({"name": "BIN-%d" % i, "pointName": "AP%d" % i, "layer": 0})
    # Point cloud like RDS normalPosList (must not be confused with map station points)
    cloud = [{"x": (i % 20) * 0.25, "y": (i // 20) * 0.25} for i in range(200)]
    mm = {"points": pts, "paths": paths, "bins": bins, "zones": [], "newThing": {}, "sourceMaps": [MAP_NAME]}
    if SCHEMA_CLOUD: mm["normalPosList"] = cloud
    area0 = {"id": 0, "name": "Area-1", "mergedMap": mm,
             "groupsMap": {"0": {"mapName": MAP_NAME, "mapFile": MAP_FILE, "mapMd5": "deadbeef"}}}
    return {"id": SCENE_ID, "basic": {"id": SCENE_ID, "name": "Mock scene", "version": 3},
            "structure": {"robotGroups": [{"id": 0, "name": "grpA", "fork": True, "futureField": "x"}],
                          "robots": [{"robotName": "AMB-01", "groupId": 0}, {"robotName": "AMB-02", "groupId": 0}],
                          "areas": [area0,
                                    {"id": 1, "name": "Disabled", "disabled": True, "mergedMap": {"points": [{"name": "AP99", "x": 0, "y": 0}]}}],
                          "lifts": [], "somethingNew": 42}}

def steps_of(o, now=None):
    """[(step, status, startOn)]; a cancelled order freezes at its cancel time"""
    now = o.get("cancelT") or now or time.time(); cur = o["t"]; out = []; dead = False
    for i, s in enumerate(o["steps"]):
        if dead: out.append((s, "Executable", None)); continue
        start = max(cur, s["_added"]); fin = start + STEP_DUR * (4 if i == 1 and "fault" in o["id"] else 1)
        if now < start: st = "Executable"
        elif now >= fin: st = "Done"
        else: st = "Cancelled" if o.get("cancelT") else "Executing"
        out.append((s, st, start if now >= start else None)); cur = fin
        if st != "Done": dead = True
    return out

def fault_of(o, now=None):
    if "fault" not in o["id"] or o.get("cancelT"): return False
    sl = steps_of(o, now)
    if len(sl) < 2 or sl[1][1] != "Executing": return False
    st = sl[1][2]; t = now or time.time()
    return st + STEP_DUR * 0.5 <= t < st + STEP_DUR * 3

def status_of(o):
    now = time.time()
    if o.get("cancelT"): return "Cancelled" if now >= o["cancelT"] + CANCEL_DUR else "Cancelling"
    sl = steps_of(o, now)
    if "xcancel" in o["id"] and sl and sl[0][1] == "Done":
        o["cancelT"] = now; return "Cancelling"
    if sl and all(s == "Done" for _, s, _ in sl): return "Done" if o["stepFixed"] else "Pending"
    if any(s == "Executing" for _, s, _ in sl): return "Executing"
    return "ToBeAllocated"

def detail(o):
    st = status_of(o); sl = steps_of(o)
    return {"id": o["id"], "sceneId": o["sceneId"], "status": st, "fault": fault_of(o), "faultReason": "mock fault: robot blocked" if fault_of(o) else None,
            "stepFixed": o["stepFixed"], "stepNum": len(sl), "actualRobotName": "AMB-01" if st != "ToBeAllocated" else None,
            "createdOn": int(o["t"] * 1000), "doneOn": int(time.time() * 1000) if st in ("Done", "Cancelled") else None,
            "currentStepIndex": next((i for i, (_, s, _) in enumerate(sl) if s != "Done"), len(sl)),
            "steps": [{"id": s["id"], "stepIndex": str(i), "status": ss, "location": s["location"], "rbkArgs": json.dumps(s.get("rbkArgs") or {}),
                       "startOn": int(t0 * 1000) if t0 else None} for i, (s, ss, t0) in enumerate(sl)]}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def js(self, o, code=200, cookie=None):
        b = json.dumps(o).encode() if o is not None else b""
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers(); self.wfile.write(b)
    def err(self, msg, code=400): return self.js({"code": 400 if code == 400 else code, "message": msg}, code)
    def authed(self):
        if not AUTH: return True
        if self.headers.get("xyy-app-id") == APP_ID and self.headers.get("xyy-app-key") == APP_KEY: return True
        ck = self.headers.get("Cookie") or ""
        return any(p.strip().startswith("xzz-qyx=") and p.strip()[8:] in SESSIONS for p in ck.split(";"))
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query)); p = u.path
        if p == "/_received":
            with LOCK: return self.js(RECEIVED)
        if not self.authed(): return self.js(None, 401)
        if p == "/api/ping": return self.js({"id": "mock", "username": USER})
        if p == "/api/fleet/scenes/list": return self.js([{"id": SCENE_ID, "name": "Mock scene", "disabled": False, "version": 3}, {"id": "scene-2", "name": "Other", "disabled": True}])
        if p.startswith("/api/fleet/scenes/schema/"):
            if p.rsplit("/", 1)[1] != SCENE_ID: return self.err("scene not found")
            return self.js(schema())
        if p == "/api/fleet/orders/query-order-detail":
            with LOCK:
                o = ORDERS.get(q.get("orderId", ""))
                if not o: return self.err("order not found: %s" % q.get("orderId"))
                sl = steps_of(o)
                if "qerr" in o["id"] and sl and sl[0][1] == "Done" and not o.get("qerrDone"):
                    o.setdefault("qerrT", time.time())
                    if time.time() - o["qerrT"] < STEP_DUR * 2: return self.js({"error": "mock internal error"}, 500)
                    o["qerrDone"] = True
                return self.js(detail(o))
        if p == "/api/fleet/robots/all-all":
            if q.get("sceneId") != SCENE_ID: return self.err("scene not found")
            with LOCK: act = [o for o in ORDERS.values() if status_of(o) == "Executing"]
            cur = act[0]["id"] if act else None
            return self.js({"AMB-01": {"name": "AMB-01", "online": True, "disabled": False, "offDuty": False, "x": 1.0, "y": 0.5, "d": 0.0, "p": "AP1", "battery": 0.8,
                                       "blocked": False, "groupName": "grpA", "orders": [cur] if cur else [], "cmdStatus": "Moving" if cur else "Idle", "raw": {"x": 1}},
                            "AMB-02": {"name": "AMB-02", "online": True, "disabled": False, "offDuty": True, "x": 5.0, "y": 0.5, "d": 1.0, "p": "AP3", "battery": 0.6,
                                       "blocked": False, "groupName": "grpA", "orders": [], "cmdStatus": "Idle"}})
        # Same URL shape as M4 UI: /api/fleet/scenes/{sceneId}/download/{mapFile}
        pref = "/api/fleet/scenes/"
        if p.startswith(pref) and "/download/" in p:
            rest = p[len(pref):]; sid, _, mpath = rest.partition("/download/")
            if sid != SCENE_ID: return self.err("scene not found")
            if not DOWNLOAD_MAP: self.send_response(404); self.end_headers(); return
            b = DOWNLOAD_MAP
            self.send_response(200); self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        self.err("not found", 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: b = json.loads(self.rfile.read(n) or b"{}")
        except ValueError: return self.err("bad json")
        p = self.path
        if p == "/api/sign-in":
            if b.get("username") == USER and b.get("password") == PASSWORD:
                tok = uuid.uuid4().hex; SESSIONS.add(tok)
                return self.js({"userId": USER, "userToken": tok}, cookie="xzz-qyx=%s; Path=/" % tok)
            return self.err("wrong username or password")
        if not self.authed(): return self.js(None, 401)
        with LOCK:
            if p == "/api/fleet/orders/create":
                if not b.get("sceneId"): return self.err("sceneId required")
                oid = b.get("id") or "TO-%s" % uuid.uuid4().hex[:8]
                if oid in ORDERS: return self.err("order id exists: %s" % oid)
                now = time.time(); RECEIVED.append(b)
                ORDERS[oid] = {"id": oid, "sceneId": b["sceneId"], "t": now, "stepFixed": bool(b.get("stepFixed", True)), "body": b,
                               "steps": [dict(s, id=s.get("id") or "%s-Step%d" % (oid, i), _added=now) for i, s in enumerate(b.get("steps") or [])]}
                return self.js({"orderId": oid, "externalId": b.get("externalId")})
            if p in ("/api/fleet/orders/add-steps", "/api/fleet/orders/complete-order"):
                o = ORDERS.get(b.get("orderId"))
                if not o: return self.err("order not found")
                if o["stepFixed"] or status_of(o) in ("Done", "Cancelled", "Cancelling"): return self.err("order is sealed or finished")
                sl = steps_of(o)
                EVENTS.append({"id": o["id"], "path": p.rsplit("/", 1)[1], "t": time.time(), "prevState": sl[-1][1] if sl else None,
                               "steps": [s.get("id") for s in b.get("steps") or []], "n": len(o["steps"]), "fault": fault_of(o)})
                if p.endswith("add-steps"):
                    now = time.time(); k = len(o["steps"])
                    o["steps"] += [dict(s, id=s.get("id") or "%s-Step%d" % (o["id"], k + i), _added=now) for i, s in enumerate(b.get("steps") or [])]
                else: o["stepFixed"] = True
                return self.js(None)
            if p == "/api/fleet/orders/cancel":
                o = ORDERS.get(b.get("orderId"))
                if o and not o.get("cancelT") and status_of(o) != "Done": o["cancelT"] = time.time()
                return self.js(None)
        self.err("not found", 404)

def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=18090); ap.add_argument("--no-auth", action="store_true"); a = ap.parse_args()
    AUTH = not a.no_auth
    print("fake M4 on http://127.0.0.1:%d  scene %s  app-id/key %s/%s  login %s/%s" % (a.port, SCENE_ID, APP_ID, APP_KEY, USER, PASSWORD)); serve(a.port).serve_forever()
