# -*- coding: utf-8 -*-
"""Tiny fake RDS for local end-to-end testing (no real data). python tools/fake_rds.py [--port 18088]
Scene: AP1..AP12 with LM1..LM12 pre-points (curve LMn -> APn), robot group grpA (AMB-01, AMB-02).
Orders progress CREATED -> RUNNING -> FINISHED (order ids containing 'fail' go FAILED, then RUNNING again).
Incremental orders (setOrder complete=false, then /addBlocks + /markComplete): blocks run one after another,
BLOCK_DUR s each (a block starts when it exists and its predecessor is FINISHED). All blocks done but not complete
-> order WAITING; complete -> FINISHED. Order ids containing 'bfail' fail their 2nd block for a while
(block + order FAILED, like the real RDS), then it recovers and FINISHES; 'berr' -> same with block + order Error; 'bmanual' -> 2nd block MANUAL_FINISHED (counts as done). setOrder ids ending in
'brecover' -> 2nd block FAILED for a while (order stays RUNNING), then the block recovers and FINISHES. ids ending in
'-nocode' get a success response without 'code' (the doc says code 0 or absent = success). Error codes follow the doc (50003).
INC_EVENTS records every addBlocks/markComplete with the predecessor block state at that moment."""
import argparse, io, json, threading, time, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

SCENE_DELAY, SCENE_FAIL, SCENE_NOLEN = 0, False, False
DOWNLOAD_SCENE = b""  # zip bytes served by /downloadScene (tests); empty -> 404

def scene():
    pts = []; curves = []
    for i in range(1, 13):
        ap = {"className": "ActionPoint", "instanceName": "AP%d" % i, "pos": {"x": i * 2.0, "y": 0.0}}
        if i % 2: ap["dir"] = 1.5707963  # odd APs carry a heading (radians, like RDS)
        pts.append(ap)
        pts.append({"className": "LocationMark", "instanceName": "LM%d" % i, "pos": {"x": i * 2.0, "y": 2.0}})
        curves.append({"className": "StraightPath", "instanceName": "LM%d-AP%d" % (i, i),
                       "startPos": {"instanceName": "LM%d" % i, "pos": {"x": i * 2.0, "y": 2.0}}, "endPos": {"instanceName": "AP%d" % i, "pos": {"x": i * 2.0, "y": 0.0}}})
    return {"scene": {"areas": [{"logicalMap": {"advancedPoints": pts, "advancedCurves": curves}}],
                      "robotGroup": [{"name": "grpA", "robot": [{"id": "AMB-01"}, {"id": "AMB-02"}]}]}}

ORDERS = {}; LOCK = threading.Lock(); RECEIVED = []
BLOCK_DUR = 0.4; INC_EVENTS = []

def inc_blocks(o, now=None):
    """[(block, state)] for an incremental order (a terminated order freezes at its terminate time, RUNNING -> STOPPED)"""
    term = o.get("termT"); now = term or now or time.time(); cur = o["t"]; out = []; dead = False
    for i, b in enumerate(o["blocks"]):
        if dead: out.append((b, "CREATED")); continue
        start = max(cur, b["_added"]); rec = i == 1 and any(k in o["id"] for k in ("brecover", "bfail", "berr"))
        fin = start + BLOCK_DUR * (4 if rec else 1)
        if now < start: st = "CREATED"
        elif rec and start + BLOCK_DUR / 2 <= now < fin - BLOCK_DUR / 2: st = "Error" if "berr" in o["id"] else "FAILED"
        elif i == 1 and "bmanual" in o["id"] and now >= start + BLOCK_DUR / 2: st = "MANUAL_FINISHED"
        elif now >= fin: st = "FINISHED"
        else: st = "STOPPED" if term else "RUNNING"
        out.append((b, st)); cur = fin
        if st not in ("FINISHED", "MANUAL_FINISHED"): dead = True
    return out

def inc_state(o):
    bs = [s for _, s in inc_blocks(o)]
    if o.get("terminated"): return "STOPPED"
    if "FAILED" in bs and "brecover" not in o["id"]: return "FAILED"
    if "Error" in bs: return "Error"
    if bs and all(s in ("FINISHED", "MANUAL_FINISHED") for s in bs): return "FINISHED" if o.get("complete") else "WAITING"
    if any(s in ("RUNNING", "FINISHED", "FAILED") for s in bs): return "RUNNING"
    return "CREATED"

def state_of(o):
    age = time.time() - o["t"]
    if o.get("terminated"): return "STOPPED"
    if "fail" in o["id"] and 2 < age < 5: return "FAILED"
    if age < 1: return "CREATED"
    if age < float(o.get("dur", 6)): return "RUNNING"
    return "FINISHED"

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def js(self, o, code=200):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path
        if p == "/scene":
            if SCENE_DELAY and not SCENE_FAIL:  # slow streamed body, so download progress can be observed
                b = json.dumps(scene()).encode(); n = 10; self.send_response(200); self.send_header("Content-Type", "application/json")
                if not SCENE_NOLEN: self.send_header("Content-Length", str(len(b)))
                else: self.close_connection = True
                self.end_headers(); time.sleep(SCENE_DELAY / (n + 1))
                for i in range(n):
                    self.wfile.write(b[i * len(b) // n:(i + 1) * len(b) // n]); self.wfile.flush(); time.sleep(SCENE_DELAY / (n + 1))
                return
            time.sleep(SCENE_DELAY)
            if SCENE_FAIL == "badjson":
                b = b"<html>not json</html>"; self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
            if SCENE_FAIL: return self.js({"err": "fake scene failure"}, 500)
            return self.js(scene())
        if p == "/downloadScene":
            if not DOWNLOAD_SCENE: self.send_response(404); self.end_headers(); return
            b = DOWNLOAD_SCENE; self.send_response(200); self.send_header("Content-Type", "application/zip"); self.send_header("Content-Length", str(len(b))); self.end_headers()
            n = 8
            for i in range(n): self.wfile.write(b[i * len(b) // n:(i + 1) * len(b) // n]); self.wfile.flush(); time.sleep(0.05)
            return
        if p.startswith("/orderDetails/"):
            oid = p.split("/", 2)[2]
            with LOCK: o = ORDERS.get(oid)
            if not o: return self.js({"code": 60000, "msg": "not found"})
            if o.get("inc"):
                with LOCK: bl = inc_blocks(o); st = inc_state(o)
                return self.js({"id": oid, "state": st, "complete": bool(o.get("complete")), "vehicle": "AMB-01" if st != "CREATED" else "", "createTime": int(o["t"] * 1000),
                                "blocks": [{"blockId": b["blockId"], "state": s} for b, s in bl],
                                "terminateTime": int(time.time() * 1000) if st in ("FINISHED", "STOPPED") else None})
            st = state_of(o)
            return self.js({"id": oid, "state": st, "vehicle": "AMB-01" if st != "CREATED" else "", "createTime": int(o["t"] * 1000),
                            "blocks": [{"blockId": b["blockId"], "state": "FINISHED" if st == "FINISHED" else ("RUNNING" if st == "RUNNING" else "CREATED")} for b in o["body"]["blocks"]],
                            "terminateTime": int(time.time() * 1000) if st in ("FINISHED", "STOPPED") else None})
        if p == "/robotsStatus":
            with LOCK: act = [o for o in ORDERS.values() if (inc_state(o) if o.get("inc") else state_of(o)) in ("RUNNING", "FAILED")]
            cur = act[0] if act else None; x = 1.0 + (time.time() % 10) * 0.5 if cur else 1.0
            return self.js({"report": [{"uuid": "AMB-01", "dispatchable": True, "connection_status": 1, "rbk_report": {"x": x, "y": 0.5, "angle": 0.0, "battery_level": 0.8, "current_station": "AP1", "blocked": False},
                                        "current_order": {"id": cur["id"], "state": inc_state(cur) if cur.get("inc") else state_of(cur)} if cur else {}},
                                       {"uuid": "AMB-02", "dispatchable": True, "connection_status": 1, "rbk_report": {"x": 5.0, "y": 0.5, "angle": 0.0, "battery_level": 0.6, "current_station": "AP3", "blocked": False}}]})
        if p == "/_received":
            with LOCK: return self.js(RECEIVED)
        self.js({"err": "nf"}, 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); b = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/setOrder":
            with LOCK:
                now = time.time(); ORDERS[b["id"]] = o = {"id": b["id"], "t": now, "body": b}; RECEIVED.append(b)
                if b.get("complete") is False:
                    o.update(inc=True, complete=False, blocks=[dict(x, _added=now) for x in b.get("blocks") or []])
            return self.js({"msg": "ok", "create_on": "2022-02-10T18:21:25.073Z"} if b.get("id", "").endswith("-nocode") else {"code": 0, "msg": "ok"})
        if self.path in ("/addBlocks", "/markComplete"):
            with LOCK:
                o = ORDERS.get(b.get("id"))
                if not o or not o.get("inc"): return self.js({"code": 50003, "msg": "order doesn't exist"}, 400)
                if o.get("complete"): return self.js({"code": 50003, "msg": "order is complete"}, 400)
                bl = inc_blocks(o); prev = bl[-1][1] if bl else None
                INC_EVENTS.append({"id": o["id"], "path": self.path, "t": time.time(), "prevState": prev, "blocks": [x.get("blockId") for x in b.get("blocks") or []], "n": len(o["blocks"])})
                if self.path == "/addBlocks":
                    now = time.time(); o["blocks"] += [dict(x, _added=now) for x in b.get("blocks") or []]
                    if b.get("complete"): o["complete"] = True
                else: o["complete"] = True
            return self.js({"code": 0})
        if self.path == "/terminate":
            with LOCK:
                if b.get("id") in ORDERS: ORDERS[b["id"]]["terminated"] = True; ORDERS[b["id"]].setdefault("termT", time.time())
            return self.js({"code": 0})
        self.js({"err": "nf"}, 404)

def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=18088); ap.add_argument("--scene-delay", type=float, default=0); ap.add_argument("--scene-fail", action="store_true"); ap.add_argument("--scene-nolen", action="store_true"); ap.add_argument("--download-scene", help="zip file served by /downloadScene"); a = ap.parse_args()
    SCENE_DELAY, SCENE_FAIL, SCENE_NOLEN = a.scene_delay, a.scene_fail, a.scene_nolen
    if a.download_scene:
        with open(a.download_scene, "rb") as f: DOWNLOAD_SCENE = f.read()
    print("fake RDS on http://127.0.0.1:%d" % a.port); serve(a.port).serve_forever()
