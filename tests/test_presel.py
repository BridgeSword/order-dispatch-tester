# -*- coding: utf-8 -*-
"""Pre-point selection strategies (nearest/index/name/dir/random), multi-value manual map, scene candidate info."""
import unittest
from helpers import C, fresh_core
from order_tester import templates as T
from order_tester.adapters import rds_scene

def P(cls, name, x, y): return {"className": cls, "instanceName": name, "pos": {"x": x, "y": y}}
def CV(a, b): return {"className": "StraightPath", "instanceName": a + "-" + b, "startPos": {"instanceName": a}, "endPos": {"instanceName": b}}

def scene():
    # AP1 at (0,0): drive-in from LM1 (1 m) and LM2 (3 m), drive-out to LM3 (2 m), drive-in from AP9 (not LM, 0.5 m)
    pts = [P("ActionPoint", "AP1", 0, 0), P("LocationMark", "LM1", 1, 0), P("LocationMark", "LM2", 3, 0), P("LocationMark", "LM3", 0, 2),
           P("ActionPoint", "AP9", 0.5, 0), P("ActionPoint", "AP2", 10, 0), P("LocationMark", "LM20", 10, 1)]
    cv = [CV("LM2", "AP1"), CV("LM1", "AP1"), CV("AP1", "LM3"), CV("AP9", "AP1"), CV("LM20", "AP2")]
    return {"scene": {"areas": [{"logicalMap": {"advancedPoints": pts, "advancedCurves": cv}}]}}

def tpl(select=None, sel_arg=None, args=None):
    pre = {"type": "pre", "step": "s"}
    if select: pre["select"] = select
    if sel_arg is not None: pre["selArg"] = sel_arg
    return {"name": "ps", "steps": [
        {"id": "w", "name": "前置", "location": pre, "operation": "Wait", "args": args or {}},
        {"id": "s", "name": "取货", "location": {"type": "pool", "pool": "start"}, "operation": "JackLoad", "args": {}}]}

class PreSelectTest(unittest.TestCase):
    def setUp(self):
        fresh_core(self)
        st = rds_scene.parse_scene(scene())
        self.by = {p["name"]: p for p in st}
        C.S["prepoints"] = {p["name"]: p["pre"] for p in st if p.get("pre")}; C.S["precands"] = C._precands(st)

    def build(self, t, st="AP1", cfg=None, rng=None):
        cfg = cfg or {}; self.assertEqual(T.validate(t), [])
        return T.build_order(t, {"start": st}, cfg, lambda n: C.pre_point(n, cfg), "o1", cands_of=lambda n: C.pre_cands(n, cfg), rng=rng)

    def test_scene_candidates_keep_dir_dist_lm(self):
        info = self.by["AP1"]["preInfo"]
        self.assertEqual([(c["name"], c["dir"], c["lm"]) for c in info],
                         [("LM1", "in", True), ("LM2", "in", True), ("LM3", "out", True), ("AP9", "in", False)])
        self.assertEqual(info[0]["dist"], 1.0); self.assertEqual(info[1]["dist"], 3.0)
        self.assertEqual(self.by["AP1"]["pre"], "LM1")  # default unchanged: nearest drive-in LM

    def test_strategies(self):
        loc = lambda o: o["steps"][0]["location"]
        self.assertEqual(loc(self.build(tpl())), "LM1")
        self.assertEqual(loc(self.build(tpl("index", "2"))), "LM2")
        self.assertEqual(loc(self.build(tpl("name", "LM3"))), "LM3")
        self.assertEqual(loc(self.build(tpl("name", "LM*"))), "LM1")
        self.assertEqual(loc(self.build(tpl("dir", "out"))), "LM3")
        self.assertEqual(loc(self.build(tpl("dir", "in"))), "LM1")
        import random
        seen = {loc(self.build(tpl("random"), rng=random.Random(i))) for i in range(40)}
        self.assertEqual(seen, {"LM1", "LM2", "LM3", "AP9"})

    def test_chosen_recorded_and_same_choice_inside_one_order(self):
        import random
        t = tpl("random", args={"again": "{preOf:s@random}", "out": "{preOf:s@out}", "n2": "{pre:start@#2}", "plain": "{preOf:s}"})
        o = self.build(t, rng=random.Random(3))
        a = o["steps"][0]["args"]; self.assertEqual(a["again"], o["steps"][0]["location"])  # memoised per order
        self.assertEqual((a["out"], a["n2"], a["plain"]), ("LM3", "LM2", "LM1"))
        ch = o["preChosen"]; self.assertEqual(ch[0]["where"], "前置"); self.assertEqual(ch[0]["station"], "AP1")
        self.assertIn({"where": "前置 args {preOf:s@out}", "station": "AP1", "pre": "LM3", "select": "dir=out"}, ch)
        self.assertEqual(self.build(tpl())["preChosen"], [{"where": "前置", "station": "AP1", "pre": "LM1", "select": "nearest"}])

    def test_no_match_error_names_step_and_station(self):
        for t in (tpl("dir", "out"), tpl("index", "3")):
            with self.assertRaises(ValueError) as cm: self.build(t, st="AP2")
            m = str(cm.exception); self.assertIn("前置", m); self.assertIn("AP2", m); self.assertIn("LM20(in)", m)
        with self.assertRaises(ValueError) as cm: self.build(tpl("name", "XX*"))
        self.assertIn("name=XX*", str(cm.exception))

    def test_validate_selector(self):
        for sel, arg in (("index", "0"), ("index", "x"), ("dir", "up"), ("name", ""), ("bogus", "")):
            self.assertTrue(T.validate(tpl(sel, arg)), (sel, arg))
        self.assertEqual(T.parse_sel("#2"), ("index", "2")); self.assertEqual(T.parse_sel("in"), ("dir", "in"))
        self.assertEqual(T.parse_sel("name=LM1*"), ("name", "LM1*")); self.assertEqual(T.parse_sel(""), ("nearest", ""))

    def test_manual_multi_value_map(self):
        m, e = C.parse_pre_text("AP1=LM2|LM7\nAP2 : LM20\n# comment\nAP3 LM5\nAP4,LM6\n\n")
        self.assertEqual(e, []); self.assertEqual(m, {"AP1": ["LM2", "LM7"], "AP2": ["LM20"], "AP3": ["LM5"], "AP4": ["LM6"]})
        for bad in ("AP1", "AP1=", "AP1=LM1, LM2", "AP1=LM1||LM2", "AP1=LM1 LM2", "=LM1"):
            self.assertEqual(len(C.parse_pre_text(bad)[1]), 1, bad)
        self.assertIn("AP1", C.parse_pre_text("AP1=LM1\nAP1=LM2")[1][0])
        cfg = {"preOverrides": m}
        o = self.build(tpl(), cfg=cfg); self.assertEqual(o["steps"][0]["location"], "LM2")  # manual first value = default
        o = self.build(tpl("index", "2"), cfg=cfg); self.assertEqual(o["steps"][0]["location"], "LM7")
        o = self.build(tpl("dir", "in"), cfg=cfg); self.assertEqual(o["steps"][0]["location"], "LM2")  # LM2 enriched with scene dir
        with self.assertRaises(ValueError): self.build(tpl("dir", "out"), cfg=cfg)  # manual list replaces scene list

    def test_generate_api_rejects_bad_map_and_records_choice(self):
        C.S["store"].put(tpl("index", "2"))
        b = {"templateName": "ps", "pools": {"start": ["AP1"]}, "preOverridesText": "AP1=LM1, LM2"}
        cfg, t, pools, warn, err = C.prepare_cfg(dict(b)); self.assertIn("1", err); self.assertIsNone(t)
        b["preOverridesText"] = ""
        cfg, t, pools, warn, err = C.prepare_cfg(dict(b)); self.assertEqual(err, "")
        rec = C.make_draft({"start": "AP1"}, t, cfg)
        self.assertEqual(rec["body"]["blocks"][0]["location"], "LM2"); self.assertEqual(rec["preChosen"][0]["select"], "index=2")

if __name__ == "__main__": unittest.main()
