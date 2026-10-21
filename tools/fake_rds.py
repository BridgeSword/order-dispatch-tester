# -*- coding: utf-8 -*-
"""Tiny fake RDS for local end-to-end testing (no real data). python tools/fake_rds.py [--port 18088]
Scene: AP1..AP12 with LM1..LM12 pre-points (curve LMn -> APn), robot group grpA (AMB-01, AMB-02).
Orders progress CREATED -> RUNNING -> FINISHED (order ids containing 'fail' go FAILED, then RUNNING again)."""
import argparse, io, json, threading, time, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

SCENE_DELAY, SCENE_FAIL = 0, False

def scene():
    pts = []; curves = []
    for i in range(1, 13):
        pts.append({"className": "ActionPoint", "instanceName": "AP%d" % i, "pos": {"x": i * 2.0, "y": 0.0}})
        pts.append({"className": "LocationMark", "instanceName": "LM%d" % i, "pos": {"x": i * 2.0, "y": 2.0}})
        curves.append({"className": "StraightPath", "instanceName": "LM%d-AP%d" % (i, i),
                       "startPos": {"instanceName": "LM%d" % i, "pos": {"x": i * 2.0, "y": 2.0}}, "endPos": {"instanceName": "AP%d" % i, "pos": {"x": i * 2.0, "y": 0.0}}})
    return {"scene": {"areas": [{"logicalMap": {"advancedPoints": pts, "advancedCurves": curves}}],
                      "robotGroup": [{"name": "grpA", "robot": [{"id": "AMB-01"}, {"id": "AMB-02"}]}]}}

ORDERS = {}; LOCK = threading.Lock(); RECEIVED = []

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
            time.sleep(SCENE_DELAY)
            if SCENE_FAIL == "badjson":
                b = b"<html>not json</html>"; self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
            if SCENE_FAIL: return self.js({"err": "fake scene failure"}, 500)
            return self.js(scene())
        if p == "/downloadScene": self.send_response(404); self.end_headers(); return
        if p.startswith("/orderDetails/"):
            oid = p.split("/", 2)[2]
            with LOCK: o = ORDERS.get(oid)
            if not o: return self.js({"code": 60000, "msg": "not found"})
            st = state_of(o)
            return self.js({"id": oid, "state": st, "vehicle": "AMB-01" if st != "CREATED" else "", "createTime": int(o["t"] * 1000),
                            "blocks": [{"blockId": b["blockId"], "state": "FINISHED" if st == "FINISHED" else ("RUNNING" if st == "RUNNING" else "CREATED")} for b in o["body"]["blocks"]],
                            "terminateTime": int(time.time() * 1000) if st in ("FINISHED", "STOPPED") else None})
        if p == "/robotsStatus":
            with LOCK: act = [o for o in ORDERS.values() if state_of(o) in ("RUNNING", "FAILED")]
            cur = act[0] if act else None; x = 1.0 + (time.time() % 10) * 0.5 if cur else 1.0
            return self.js({"report": [{"uuid": "AMB-01", "dispatchable": True, "connection_status": 1, "rbk_report": {"x": x, "y": 0.5, "angle": 0.0, "battery_level": 0.8, "current_station": "AP1", "blocked": False},
                                        "current_order": {"id": cur["id"], "state": state_of(cur)} if cur else {}},
                                       {"uuid": "AMB-02", "dispatchable": True, "connection_status": 1, "rbk_report": {"x": 5.0, "y": 0.5, "angle": 0.0, "battery_level": 0.6, "current_station": "AP3", "blocked": False}}]})
        if p == "/_received":
            with LOCK: return self.js(RECEIVED)
        self.js({"err": "nf"}, 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); b = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/setOrder":
            with LOCK: ORDERS[b["id"]] = {"id": b["id"], "t": time.time(), "body": b}; RECEIVED.append(b)
            return self.js({"code": 0})
        if self.path == "/terminate":
            with LOCK:
                if b.get("id") in ORDERS: ORDERS[b["id"]]["terminated"] = True
            return self.js({"code": 0})
        self.js({"err": "nf"}, 404)

def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=18088); ap.add_argument("--scene-delay", type=float, default=0); ap.add_argument("--scene-fail", action="store_true"); a = ap.parse_args()
    SCENE_DELAY, SCENE_FAIL = a.scene_delay, a.scene_fail
    print("fake RDS on http://127.0.0.1:%d" % a.port); serve(a.port).serve_forever()
