# -*- coding: utf-8 -*-
"""End to end over HTTP: tester server <-> fake RDS (tools/fake_rds.py)."""
import json, os, sys, threading, time, unittest, urllib.request
from http.server import ThreadingHTTPServer
from helpers import C, fresh_core, ROOT
sys.path.insert(0, os.path.join(ROOT, "tools"))
import fake_rds
from order_tester import server

def call(port, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(); return json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw

class E2ETest(unittest.TestCase):
    def setUp(self):
        self.rds = fake_rds.serve(0); rport = self.rds.server_address[1]
        fresh_core(self, base="http://127.0.0.1:%d" % rport); C.migrate_templates()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        C.S["cfg"]["pollSec"] = 0.3
        self.addCleanup(self.srv.shutdown); self.addCleanup(self.rds.shutdown)
        fake_rds.ORDERS.clear(); del fake_rds.RECEIVED[:]

    def test_scene_failure_is_error(self):
        self.addCleanup(setattr, fake_rds, "SCENE_FAIL", False)
        for mode, frag in ((True, "500"), ("badjson", "invalid JSON")):
            fake_rds.SCENE_FAIL = mode; C.S.pop("st_cache", None)
            r = call(self.port, "/api/stations?refresh=1")
            self.assertFalse(r["ok"], (mode, r)); self.assertIn(frag, r["err"])
            g = call(self.port, "/api/scene_geom?refresh=1"); self.assertIn(frag, g["sceneErr"]); self.assertEqual(g["stations"], [])
        fake_rds.SCENE_FAIL = False
        g = call(self.port, "/api/scene_geom?refresh=1"); self.assertEqual(g["sceneErr"], ""); self.assertEqual(len(g["stations"]), 24)
        self.assertEqual(len(call(self.port, "/api/scene_geom?cached=1")["stations"]), 24)
        r = call(self.port, "/api/stations?refresh=1"); self.assertTrue(r["ok"]); self.assertEqual(len(r["stations"]), 24)

    def test_scene_cache_persists_and_survives_failure(self):
        g = call(self.port, "/api/scene_geom?refresh=1"); self.assertEqual(g["sceneErr"], ""); self.assertTrue(g["loadedAt"])
        self.assertTrue(os.path.isfile(C.P["scene_cache"]))
        # a failed refresh keeps the last good scene
        self.addCleanup(setattr, fake_rds, "SCENE_FAIL", False); fake_rds.SCENE_FAIL = True
        self.assertTrue(call(self.port, "/api/scene_geom?refresh=1")["sceneErr"])
        c = call(self.port, "/api/scene_geom?cached=1"); self.assertEqual(len(c["stations"]), 24); self.assertEqual(c["loadedAt"], g["loadedAt"])
        # "restart": wipe memory, re-init on the same data dir; RDS still failing -> served from disk
        C.S.update(geom=None, prepoints={}, groups=[], robot_group={}); C.S.pop("st_cache", None)
        C.init(C.P["data"], base=C.AD().base)
        c = call(self.port, "/api/scene_geom?cached=1"); self.assertTrue(c["fromCache"]); self.assertEqual(c["loadedAt"], g["loadedAt"]); self.assertEqual(len(c["stations"]), 24)
        self.assertEqual(C.S["prepoints"].get("AP1"), "LM1")
        st = call(self.port, "/api/stations"); self.assertTrue(st["ok"]); self.assertEqual(len(st["stations"]), 24)

    def _run_job(self):
        self.addCleanup(setattr, fake_rds, "SCENE_DELAY", 0)
        jid = call(self.port, "/api/scene_geom?refresh=1&async=1")["job"]
        self.assertEqual(call(self.port, "/api/scene_geom?refresh=1&async=1")["job"], jid)  # concurrent callers share the job
        seen = []; t0 = time.time()
        while time.time() - t0 < 15:
            j = call(self.port, "/api/scene_job?id=" + jid); self.assertTrue(j["ok"])
            seen.append((j["stage"], j.get("done"), j.get("total")))
            if j["finished"]: return j, seen
            self.assertNotIn("result", j); time.sleep(0.05)
        self.fail("scene job did not finish")

    def test_scene_job_progress_slow_scene(self):
        fake_rds.SCENE_DELAY = 1.5
        j, seen = self._run_job()
        self.assertEqual(j["stage"], "done"); self.assertEqual(len(j["result"]["stations"]), 24); self.assertGreater(j["elapsed"], 1.0)
        stages = [x[0] for x in seen]; self.assertIn("download", stages)
        dl = [x for x in seen if x[0] == "download"]
        self.assertTrue(all(x[2] for x in dl), dl)  # Content-Length known
        done = [x[1] for x in dl]; self.assertEqual(done, sorted(done)); self.assertLess(done[0], dl[0][2])  # partial progress observed
        self.assertEqual(len(call(self.port, "/api/scene_geom?cached=1")["stations"]), 24)

    def test_scene_job_progress_no_length_and_failure(self):
        self.addCleanup(setattr, fake_rds, "SCENE_NOLEN", False); fake_rds.SCENE_NOLEN = True; fake_rds.SCENE_DELAY = 1.0
        j, seen = self._run_job()
        self.assertEqual(j["stage"], "done"); dl = [x for x in seen if x[0] == "download"]
        self.assertTrue(dl and all(x[2] is None for x in dl), dl); self.assertGreater(max(x[1] or 0 for x in dl), 0)
        self.addCleanup(setattr, fake_rds, "SCENE_FAIL", False); fake_rds.SCENE_FAIL = True; fake_rds.SCENE_DELAY = 0
        j, _ = self._run_job(); self.assertEqual(j["stage"], "failed"); self.assertIn("500", j["result"]["sceneErr"])
        self.assertFalse(call(self.port, "/api/scene_job?id=nope")["ok"])

    def test_geom_cached_only_and_no_cache_headers(self):
        self.assertFalse(call(self.port, "/api/scene_geom?cached=1")["ok"])
        with urllib.request.urlopen("http://127.0.0.1:%d/" % self.port) as r:
            self.assertEqual(r.headers["Cache-Control"], "no-store"); self.assertRegex(r.read().decode(), r'/static/app\.js\?v=\d+"')
        with urllib.request.urlopen("http://127.0.0.1:%d/static/app.js" % self.port) as r: self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_full_flow(self):
        p = self.port
        self.assertIn(b"app.js", call(p, "/")); self.assertIn(b"loadI18n", call(p, "/static/app.js"))
        self.assertEqual(call(p, "/api/i18n?lang=en")["t"]["tab.cfg"], "Config & Dispatch")
        st = call(p, "/api/stations"); self.assertTrue(st["ok"]); self.assertEqual(len(st["stations"]), 24)
        tl = call(p, "/api/templates"); self.assertEqual(tl["names"], ["default"])
        pv = call(p, "/api/preview", {"templateName": "default", "pools": {"start": ["AP1"], "end": ["AP2"]}})
        self.assertEqual([b["location"] for b in pv["payload"]["blocks"]], ["LM1", "AP1", "LM2", "AP2", "LM2"])
        g = call(p, "/api/generate", {"templateName": "default", "pools": {"start": ["AP1", "AP2", "AP3"], "end": ["AP4", "AP5"]}, "group": "grpA", "count": None})
        self.assertTrue(g["ok"], g); self.assertEqual(g["n"], 3)
        ids = g["ids"]
        sw = call(p, "/api/swap_drafts", {"templateName": "default", "ids": ids[:1]}); self.assertEqual(sw["n"], 1)
        self.assertEqual(call(p, "/api/delete_drafts", {"ids": ids[2:]})["n"], 1)
        call(p, "/api/send", {"ids": ids[:2], "interval": 0, "maxActive": 0})
        t0 = time.time()
        while time.time() - t0 < 5 and len(fake_rds.RECEIVED) < 2: time.sleep(0.1)
        self.assertEqual([o["id"] for o in fake_rds.RECEIVED], ids[:2])
        self.assertEqual(fake_rds.RECEIVED[0]["group"], "grpA")
        stop = threading.Event()
        def poll():
            while not stop.is_set():
                C.poll_once(); time.sleep(0.2)
        th = threading.Thread(target=poll, daemon=True); th.start(); self.addCleanup(stop.set)
        while time.time() - t0 < 15:
            s = call(p, "/api/state"); states = {o["id"]: o["state"] for o in s["orders"]}
            if all(states.get(i) == "FINISHED" for i in ids[:2]): break
            time.sleep(0.3)
        self.assertEqual({states[i] for i in ids[:2]}, {"FINISHED"})
        o = next(x for x in s["orders"] if x["id"] == ids[0])
        self.assertTrue(o.get("started") and o.get("ended") and o.get("batch")); self.assertTrue(s["robots"])
        self.assertEqual(s["groups"][0]["name"], "grpA")
        c = call(p, "/api/cancel", {"ids": ids[:1]}); self.assertTrue(c["ok"])

    def test_failed_not_terminal_and_template_crud(self):
        p = self.port
        t = {"name": "fail_tpl", "steps": [{"id": "s", "location": {"type": "pool", "pool": "start"}, "operation": "Wait", "args": {}}]}
        self.assertTrue(call(p, "/api/template_save", {"template": t})["ok"])
        self.assertFalse(call(p, "/api/template_save", {"template": t, "noOverwrite": True})["ok"])
        self.assertFalse(call(p, "/api/template_save", {"template": {"name": "bad", "steps": []}})["ok"])
        self.assertIn("fail_tpl", call(p, "/api/templates")["names"])
        g = call(p, "/api/generate", {"templateName": "fail_tpl", "pools": {"start": ["AP1"]}, "count": 1})
        oid = g["ids"][0]; C.S["orders"][oid]["body"]["id"] = oid
        # make the fake RDS report FAILED for this order
        call(p, "/api/send", {"ids": [oid], "interval": 0, "maxActive": 0}); time.sleep(0.5)
        fake_rds.ORDERS[oid]["id"] = oid + "fail"; fake_rds.ORDERS[oid]["t"] = time.time() - 3
        orig = fake_rds.state_of
        fake_rds.state_of = lambda o: "FAILED"
        try:
            C.poll_once()
            o = C.S["orders"][oid]; self.assertEqual(o["state"], "FAILED"); self.assertTrue(C.is_active(o)); self.assertNotIn("ended", o)
        finally: fake_rds.state_of = orig
        self.assertTrue(call(p, "/api/template_delete", {"name": "fail_tpl"})["ok"])
        self.assertFalse(call(p, "/api/template_delete", {"name": "default"})["ok"])  # last one

if __name__ == "__main__": unittest.main()
