# -*- coding: utf-8 -*-
"""The built-in default template must generate JSON byte-identical to the legacy rds_tester.py."""
import json, random, unittest
from helpers import C, fresh_core, PREPOINTS
import legacy_reference as L
from order_tester import templates as T

UI_DEFAULT = {  # what the v1 page sent with its default inputs
    "vehicle": "", "group": "", "priority": 1, "label": "",
    "startOp": "ForkLoad", "startArgs": dict(T.DEFAULT_ARGS_START), "endOp": "ForkUnload", "endArgs": dict(T.DEFAULT_ARGS_END),
    "pickPreOn": True, "scriptOn": True, "scriptName": "userpy/rec_retry_versatile.py", "scriptOp": "locDetectMid70D",
    "scriptRecFile": "palletobject/p0001.palletobject", "liftOn": True, "liftOp": "ForkHeight", "liftArgs": {"end_height": 0.2},
    "preOverrides": {}, "vsPerBlock": {"e": {"head": 1.539, "tail": 1.539}, "lift": {"head": 1.539, "tail": 1.539}}}

STARTS = ["AP1", "AP2", "AP3", "AP4", "AP5"]
ENDS = ["AP6", "AP7", "AP8", "AP3", "AP9"]

def ids(n): return ["dl-%012x" % (0xabc000 + i) for i in range(n)]

def legacy_run(cfg, starts, ends, seed, n, no_self=True, no_reuse=True):
    L.S["prepoints"] = dict(PREPOINTS); random.seed(seed)
    pk = L.Picker(starts, ends, no_self, no_reuse); out = []
    for oid in ids(n):
        pair = pk.next()
        try: out.append(L.make_draft(pair, cfg, oid))
        except ValueError: out.append(None)
    return out

def new_run(t, cfg, starts, ends, seed, n, no_self=True, no_reuse=True):
    C.S["prepoints"] = dict(PREPOINTS); C.S["orders"] = {}; random.seed(seed)
    it = iter(ids(n)); out = []
    pk = T.make_picker("random", [("start", starts), ("end", ends)], no_self, no_reuse)
    for oid in ids(n):
        picks = pk.next()
        try: out.append(C.make_draft(picks, t, cfg, oid))
        except ValueError: out.append(None)
    return out

def dumps(x): return json.dumps(x, ensure_ascii=False)  # NOT sort_keys: key order must match too

class RegressionTest(unittest.TestCase):
    def setUp(self): fresh_core(self)

    def check(self, t, cfg, starts=STARTS, ends=ENDS, seeds=range(6), n=12, **kw):
        for seed in seeds:
            a = legacy_run(cfg, starts, ends, seed, n, **kw); b = new_run(t, cfg, starts, ends, seed, n, **kw)
            self.assertEqual(len(a), len(b))
            for x, y in zip(a, b):
                self.assertEqual(x is None, y is None)
                if x is None: continue
                self.assertEqual(dumps(x["body"]), dumps(y["body"]))
                for k in ("id", "pair", "pre", "dropPre", "pickPre", "vsTag", "vehicle", "group", "state"):
                    self.assertEqual(x[k], y[k], k)

    def test_builtin_default_equals_legacy_defaults(self):
        self.check(T.builtin_default(), UI_DEFAULT)

    def test_builtin_default_body_shape(self):
        C.S["prepoints"] = dict(PREPOINTS)
        b = C.make_draft({"start": "AP1", "end": "AP6"}, T.builtin_default(), {}, "dl-x")["body"]
        self.assertEqual([k["blockId"] for k in b["blocks"]], ["dl-x-s_PRE", "dl-x-s", "dl-x-e_SCRIPT", "dl-x-e", "dl-x-e_LIFT"])
        self.assertEqual([k["location"] for k in b["blocks"]], ["LM1", "AP1", "LM6", "AP6", "LM6"])
        self.assertNotIn("rec_dir", b["blocks"][1]["operation_args"]); self.assertEqual(b["blocks"][3]["operation_args"]["rec_dir"], 0)
        self.assertEqual(b["blocks"][2]["script_args"], {"locName": "AP6", "operation": "locDetectMid70D", "recFile": "palletobject/p0001.palletobject"})
        self.assertEqual(b["blocks"][4]["operation_args"], {"end_height": 0.2})
        self.assertEqual([("variableShape" in k) for k in b["blocks"]], [False, False, False, True, True])

    def test_variants_via_legacy_cfg(self):
        variants = [
            dict(pickPreOn=False), dict(scriptOn=False), dict(liftOn=False), dict(scriptOn=False, liftOn=False, pickPreOn=False),
            dict(vehicle="AMB-01", group="grpA ", label="empty-pallet", priority=3),
            dict(startOp="none"), dict(endOp="Wait", endArgs={}), dict(scriptRecFile="", scriptOp="", scriptName=""),
            dict(vsPerBlock={"pre": {"head": 1, "tail": 2}, "s": {"head": 0.5, "tail": 0.7}, "script": {"head": 1.2, "tail": 1.3}}),
            dict(vsPerBlock={}), dict(liftArgs={"end_height": 0.35}, liftOp="ForkHeight2"),
            dict(preOverrides={"AP6": "LMX6", "AP1": "LMX1"}),
        ]
        for v in variants:
            cfg = dict(UI_DEFAULT, **v)
            with self.subTest(v=v): self.check(T.from_legacy_cfg(cfg), cfg, seeds=range(3))

    def test_no_self_no_reuse_flags(self):
        for ns in (True, False):
            for nr in (True, False):
                with self.subTest(no_self=ns, no_reuse=nr):
                    self.check(T.builtin_default(), UI_DEFAULT, starts=["AP1", "AP2"], ends=["AP2", "AP1", "AP3"], no_self=ns, no_reuse=nr, n=9)

    def test_missing_prepoint_skips_like_legacy(self):
        self.check(T.builtin_default(), UI_DEFAULT, starts=["AP1", "AP99"], ends=["AP6", "AP98"], n=8)

    def test_generate_drafts_count_and_seed(self):
        """full server-side path (prepare_cfg + generate_drafts) with the seed: same as legacy generate_drafts."""
        C.S["prepoints"] = dict(PREPOINTS)
        b, t, pools, warn, err = C.prepare_cfg({"templateName": "default", "pools": {"start": STARTS, "end": ENDS}})
        self.assertEqual(err, "")
        random.seed(42); it = iter(ids(5))
        res = C.generate_drafts(dict(b, count=None), t, pools, id_factory=lambda: next(it))
        self.assertEqual(res["n"], len(STARTS))  # default count = size of first pool
        legacy = legacy_run(UI_DEFAULT, STARTS, ENDS, 42, 5)
        for x in legacy: self.assertEqual(dumps(x["body"]), dumps(C.S["orders"][x["id"]]["body"]))

if __name__ == "__main__": unittest.main()
