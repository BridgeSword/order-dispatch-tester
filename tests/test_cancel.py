import json, time, unittest
from unittest import mock
from helpers import C, fresh_core
from order_tester.adapters import rds

class Resp:
    def __init__(self, code, body): self.status = code; self.b = body.encode()
    def read(self): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): pass

class CancelledInRdsTest(unittest.TestCase):
    def rec(self, oid="dl-x"):
        now = time.time()
        C.S["orders"][oid] = {"id": oid, "state": "FAILED", "vehicle": "V1", "sent": now - 900, "started": now - 890, "changed": now - 800,
                              "sig": "FAILED|V1|FAILED,CREATED", "blocks": "FAILED,CREATED", "error": None, "pair": ["AP1", "AP2"]}
        return C.S["orders"][oid]
    def test_adapter_maps_50002_to_missing(self):
        fresh_core(self); ad = C.AD()
        err = rds.urllib.error.HTTPError("u", 400, "x", {}, None)
        err.read = lambda: json.dumps({"code": 50002, "msg": "order details is empty"}).encode()
        with mock.patch.object(rds.urllib.request, "urlopen", side_effect=err):
            self.assertEqual(ad.order_status("dl-x"), {"missing": True, "msg": "order details is empty"})
        with mock.patch.object(rds.urllib.request, "urlopen", side_effect=OSError("timeout")):
            self.assertIsNone(ad.order_status("dl-x"))  # network error is not 'missing'
    def test_failed_then_gone_becomes_cancelled_terminal(self):
        fresh_core(self); o = self.rec(); ad = C.AD()
        with mock.patch.object(ad, "order_status", return_value={"missing": True, "msg": "order details is empty"}), mock.patch.object(ad, "robots", return_value=None):
            for _ in range(C.MISS_LIMIT - 1): C.poll_once()
            self.assertEqual(o["state"], "FAILED")            # transient misses do not flip it yet
            C.poll_once()
        self.assertEqual(o["state"], "CANCELED"); self.assertTrue(o["gone"]); self.assertFalse(C.is_active(o))
        self.assertEqual(o["endedSrc"], "rds-missing"); self.assertLessEqual(o["ended"], time.time())
        with mock.patch.object(ad, "order_status", side_effect=AssertionError("must not poll terminal")), mock.patch.object(ad, "robots", return_value=None):
            C.poll_once()
    def test_found_again_resets_miss_and_stopped_is_terminal(self):
        fresh_core(self); o = self.rec(); ad = C.AD()
        with mock.patch.object(ad, "robots", return_value=None):
            with mock.patch.object(ad, "order_status", return_value={"missing": True, "msg": "x"}): C.poll_once()
            with mock.patch.object(ad, "order_status", return_value={"state": "STOPPED", "vehicle": "V1", "blockStates": ["FAILED", "STOPPED"]}): C.poll_once()
        self.assertNotIn("_miss", o); self.assertEqual(o["state"], "STOPPED"); self.assertIn("ended", o); self.assertFalse(C.is_active(o))
        for s in ("CANCELED", "WITHDRAWN", "STOPPED"): self.assertIn(s, C.TERMINAL())
