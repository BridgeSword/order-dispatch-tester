# -*- coding: utf-8 -*-
"""Block-by-block dispatch (逐块下发) against tools/fake_rds.py: setOrder(complete=false) + addBlocks + markComplete."""
import json, os, sys, threading, time, unittest, urllib.request
from http.server import ThreadingHTTPServer
from helpers import C, fresh_core, ROOT, PREPOINTS
sys.path.insert(0, os.path.join(ROOT, "tools"))
import fake_rds
from order_tester import server, templates as T

def call(port, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=20) as r: return json.loads(r.read())

class IncTest(unittest.TestCase):
    def setUp(self):
        self.rds = fake_rds.serve(0); self.addCleanup(self.rds.shutdown)
        fresh_core(self, base="http://127.0.0.1:%d" % self.rds.server_address[1])
        C.S["prepoints"] = dict(PREPOINTS); C.S["cfg"] = {"pollSec": 0.3, "incPollSec": 0.1}
        fake_rds.ORDERS.clear(); del fake_rds.RECEIVED[:]; del fake_rds.INC_EVENTS[:]
        self.addCleanup(setattr, fake_rds, "BLOCK_DUR", fake_rds.BLOCK_DUR); fake_rds.BLOCK_DUR = 0.3
        self.t = T.builtin_default(); T.validate(self.t)

    def draft(self, oid, a="AP1", b="AP2"):
        rec = C.make_draft({"start": a, "end": b}, self.t, {}, oid)
        with C.lock: C.S["orders"][oid] = rec
        return rec

    def run_until(self, pred, limit=15):
        t0 = time.time()
        while time.time() - t0 < limit:
            C.inc_once()
            if pred(): return True
            time.sleep(0.1)
        return False

    def test_append_after_finished_then_mark_complete(self):
        ids = ["dl-inc%d" % i for i in range(3)]
        for i, oid in enumerate(ids): self.draft(oid, "AP%d" % (i + 1), "AP%d" % (i + 5))
        C.S["running"] = True; C.send_batch(ids, 0, 0, None, inc=True)
        for oid in ids:
            sent = [r for r in fake_rds.RECEIVED if r["id"] == oid][0]
            self.assertIs(sent["complete"], False); self.assertEqual(len(sent["blocks"]), 1)
            self.assertEqual(C.S["orders"][oid]["inc"]["status"], "appending")
        self.assertTrue(self.run_until(lambda: all(C.S["orders"][i]["inc"]["status"] == "done" for i in ids)))
        n = len(self.t["steps"])
        for oid in ids:
            ev = [e for e in fake_rds.INC_EVENTS if e["id"] == oid]
            self.assertEqual([e["path"] for e in ev], ["/addBlocks"] * (n - 1) + ["/markComplete"])
            self.assertTrue(all(e["prevState"] == "FINISHED" for e in ev[:-1]), ev)  # appended only after the previous block FINISHED
            self.assertEqual(ev[-1]["n"], n)  # markComplete right after the last block
            self.assertEqual([b["blockId"] for b in fake_rds.ORDERS[oid]["blocks"]], [b["blockId"] for b in C.S["orders"][oid]["body"]["blocks"]])
            self.assertEqual(C.S["orders"][oid]["inc"]["sent"], n)
        time.sleep(fake_rds.BLOCK_DUR + 0.1)
        self.assertEqual(C.AD().order_status(ids[0])["state"], "FINISHED")

    def test_stop_on_failed_block(self):
        self.draft("dl-bfail1"); C.S["running"] = True; C.send_batch(["dl-bfail1"], 0, 0, None, inc=True)
        o = C.S["orders"]["dl-bfail1"]
        self.assertTrue(self.run_until(lambda: o["inc"]["status"] == "stopped"))
        self.assertIn("FAILED", o["inc"]["reason"]); self.assertEqual(o["inc"]["sent"], 2)
        n0 = len(fake_rds.INC_EVENTS); time.sleep(0.5); C.inc_once()
        self.assertEqual(len(fake_rds.INC_EVENTS), n0)  # nothing appended after the failure
        self.assertFalse(any(e["path"] == "/markComplete" for e in fake_rds.INC_EVENTS))

    def test_stop_on_cancel(self):
        self.draft("dl-cx"); C.S["running"] = True; C.send_batch(["dl-cx"], 0, 0, None, inc=True)
        C.AD().cancel("dl-cx")
        o = C.S["orders"]["dl-cx"]
        self.assertTrue(self.run_until(lambda: o["inc"]["status"] == "stopped"))
        self.assertIn("STOPPED", o["inc"]["reason"]); self.assertEqual(fake_rds.INC_EVENTS, [])

    def test_resume_after_restart_no_duplicate(self):
        self.draft("dl-rs"); C.S["running"] = True; C.send_batch(["dl-rs"], 0, 0, None, inc=True)
        self.assertTrue(self.run_until(lambda: C.S["orders"]["dl-rs"]["inc"]["sent"] >= 2))
        C.save_sent()
        # simulate: block 3 was appended but the tool died before saving
        with open(C.P["sent"], encoding="utf-8") as f: saved = json.load(f)
        o = C.S["orders"]["dl-rs"]; nxt = o["body"]["blocks"][o["inc"]["sent"]]
        time.sleep(fake_rds.BLOCK_DUR * 2); C.AD().add_blocks("dl-rs", [nxt])
        C.S["orders"].clear(); C.load_sent()
        self.assertEqual(C.inc_pending(), ["dl-rs"])
        self.assertTrue(self.run_until(lambda: C.S["orders"]["dl-rs"]["inc"]["status"] == "done"))
        ids = [b["blockId"] for b in fake_rds.ORDERS["dl-rs"]["blocks"]]
        self.assertEqual(len(ids), len(set(ids))); self.assertEqual(len(ids), len(self.t["steps"]))

    def test_error_block_stops_manual_finished_continues(self):
        self.draft("dl-berr1"); self.draft("dl-bmanual1", "AP3", "AP4")
        C.S["running"] = True; C.send_batch(["dl-berr1", "dl-bmanual1"], 0, 0, None, inc=True)
        e, m = C.S["orders"]["dl-berr1"], C.S["orders"]["dl-bmanual1"]
        self.assertTrue(self.run_until(lambda: e["inc"]["status"] == "stopped" and m["inc"]["status"] == "done"))
        self.assertIn("Error", e["inc"]["reason"]); self.assertEqual(e["inc"]["sent"], 2)
        self.assertEqual(m["inc"]["sent"], len(self.t["steps"]))

    def test_block_failed_then_recovers(self):
        self.draft("dl-brecover1"); C.S["running"] = True; C.send_batch(["dl-brecover1"], 0, 0, None, inc=True)
        o = C.S["orders"]["dl-brecover1"]; seen = []
        def chk():
            if o["inc"].get("warn"): seen.append(o["inc"]["warn"])
            return o["inc"]["status"] != "appending"
        self.assertTrue(self.run_until(chk))
        self.assertEqual(o["inc"]["status"], "done", o["inc"]); self.assertEqual(o["inc"]["sent"], len(self.t["steps"]))
        self.assertTrue(seen and "FAILED" in seen[0], seen); self.assertNotIn("warn", o["inc"])
        ev = [e for e in fake_rds.INC_EVENTS if e["id"] == "dl-brecover1"]
        self.assertTrue(all(e["prevState"] in ("FINISHED", "MANUAL_FINISHED") for e in ev[:-1]), ev)

    def test_rds_doc_response_codes(self):
        rec = self.draft("dl-x-nocode")
        self.assertEqual(C.AD().submit(C.AD().incremental_payload(rec["body"], 1)), (True, None))  # code absent = success
        self.assertTrue(C.AD().mark_complete("dl-x-nocode")[0])
        ok, err = C.AD().add_blocks("dl-x-nocode", [rec["body"]["blocks"][1]])  # complete order -> 50003
        self.assertFalse(ok); self.assertIn("50003", err)
        ok, err = C.AD().add_blocks("dl-nope", [rec["body"]["blocks"][1]]); self.assertFalse(ok)

    def test_off_mode_unchanged(self):
        rec = self.draft("dl-off"); C.S["running"] = True; C.send_batch(["dl-off"], 0, 0, None)
        sent = fake_rds.RECEIVED[0]
        self.assertEqual(sent, rec["body"]); self.assertIs(sent["complete"], True); self.assertNotIn("inc", C.S["orders"]["dl-off"])
        self.assertEqual(C.inc_pending(), []); C.inc_once(); self.assertEqual(fake_rds.INC_EVENTS, [])

    def test_http_send_flag(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start(); self.addCleanup(srv.shutdown)
        self.draft("dl-h1"); self.draft("dl-h2", "AP3", "AP4")
        r = call(port, "/api/send", {"ids": ["dl-h1"], "interval": 0, "maxActive": 0, "blockByBlock": True, "incPollSec": 0.1}); self.assertTrue(r["ok"])
        t0 = time.time()
        while C.S["running"] and time.time() - t0 < 5: time.sleep(0.05)
        r = call(port, "/api/send", {"ids": ["dl-h2"], "interval": 0, "maxActive": 0, "blockByBlock": False}); self.assertTrue(r["ok"])
        while C.S["running"] and time.time() - t0 < 5: time.sleep(0.05)
        by = {x["id"]: x for x in fake_rds.RECEIVED}
        self.assertIs(by["dl-h1"]["complete"], False); self.assertIs(by["dl-h2"]["complete"], True)
        st = call(port, "/api/state"); self.assertEqual(st["incPending"], 1)
        self.assertEqual({o["id"]: (o.get("inc") or {}).get("status") for o in st["orders"]}, {"dl-h1": "appending", "dl-h2": None})

if __name__ == "__main__": unittest.main()
