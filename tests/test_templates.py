# -*- coding: utf-8 -*-
import json, random, unittest
from helpers import C, fresh_core, PREPOINTS
from order_tester import templates as T
from order_tester.adapters import ADAPTERS, DispatcherAdapter, get_adapter

def three_stage():
    return {"name": "three", "steps": [
        {"id": "a", "name": "A", "location": {"type": "pool", "pool": "start"}, "operation": "ForkLoad", "args": {"x": "{start}"}},
        {"id": "m", "name": "M", "location": {"type": "pool", "pool": "mid"}, "operation": "Wait", "args": {"from": "{stationOf:step1}", "pre": "{pre:mid}"}},
        {"id": "p", "name": "P", "location": {"type": "pre", "step": "b"}, "operation": "Script",
         "args": {"script_name": "s.py", "script_args": {"loc": "{end}", "o": "{orderId}", "dp": "{dropPre}", "pp": "{pickPre}", "pm": "{preOf:m}"}}},
        {"id": "b", "name": "B", "location": {"type": "pool", "pool": "end"}, "operation": "ForkUnload", "args": {}, "vsOn": True, "variableShape": {"head": 1, "tail": 2}},
        {"id": "f", "name": "F", "location": {"type": "fixed", "station": "LM99"}, "operation": "none", "args": {}},
        {"id": "off", "name": "OFF", "enabled": False, "location": {"type": "pre", "step": "a"}, "operation": "Wait", "args": {}},
    ]}

class TemplateTest(unittest.TestCase):
    def setUp(self): fresh_core(self); C.S["prepoints"] = dict(PREPOINTS)

    def test_validate_and_roles(self):
        t = three_stage(); self.assertEqual(T.validate(t), [])
        self.assertEqual(T.pool_roles(t), ["start", "mid", "end"])
        self.assertEqual(T.needed_pre_roles(t), {"end"})
        bad = {"name": "x y", "steps": [{"id": "a", "location": {"type": "pre", "step": "zz"}}, {"id": "a", "location": {"type": "nope"}}]}
        errs = T.validate(bad); self.assertTrue(any("name" in e for e in errs)); self.assertTrue(any("duplicate" in e for e in errs))
        self.assertTrue(any("not found" in e for e in errs)); self.assertTrue(any("pool/pre/fixed" in e for e in errs))

    def test_substitution_and_payload(self):
        t = three_stage(); T.validate(t)
        rec = C.make_draft({"start": "AP1", "mid": "AP2", "end": "AP3"}, t, {"group": "g1"}, "dl-t")
        b = rec["body"]; bl = b["blocks"]
        self.assertEqual([x["blockId"] for x in bl], ["dl-t-a", "dl-t-m", "dl-t-p", "dl-t-b", "dl-t-f"])
        self.assertEqual([x["location"] for x in bl], ["AP1", "AP2", "LM3", "AP3", "LM99"])
        self.assertEqual(bl[0]["operation_args"], {"x": "AP1"})
        self.assertEqual(bl[1]["operation_args"], {"from": "AP1", "pre": "LM2"})
        self.assertEqual(bl[2]["script_args"], {"loc": "AP3", "o": "dl-t", "dp": "LM3", "pp": "LM1", "pm": "LM2"})
        self.assertEqual(bl[2]["operation_args"], {}); self.assertNotIn("operation", bl[4])
        self.assertEqual(bl[3]["variableShape"], {"head": 1.0, "tail": 2.0})
        self.assertEqual(rec["pair"], ["AP1", "AP2", "AP3"]); self.assertEqual(rec["vsTag"], "B1/2"); self.assertEqual(b["group"], "g1")

    def test_unknown_variable_and_missing_pre(self):
        t = three_stage(); t["steps"][0]["args"] = {"x": "{nope}"}; T.validate(t)
        with self.assertRaises(ValueError): C.make_draft({"start": "AP1", "mid": "AP2", "end": "AP3"}, t, {}, "x")
        t = three_stage(); T.validate(t)
        with self.assertRaises(ValueError): C.make_draft({"start": "AP1", "mid": "AP2", "end": "AP77"}, t, {}, "x")

    def test_strategies(self):
        pools = [("start", ["A", "B", "C"]), ("end", ["A", "B"])]
        rr = T.make_picker("round_robin", pools)
        self.assertEqual([rr.next() for _ in range(4)], [{"start": "A", "end": "B"}, {"start": "B", "end": "A"}, {"start": "C", "end": "A"}, {"start": "A", "end": "B"}])
        self.assertEqual(rr.default_count(), 3)
        cp = T.make_picker("cartesian", pools)
        combos = [cp.next() for _ in range(cp.default_count())]
        self.assertEqual(len(combos), 4); self.assertEqual(len({json.dumps(c, sort_keys=True) for c in combos}), 4)
        self.assertTrue(all(c["start"] != c["end"] for c in combos))
        self.assertEqual(T.make_picker("cartesian", pools, no_self=False).default_count(), 6)
        rp = T.make_picker("random", [("start", ["A", "B", "C", "D"]), ("end", ["E", "F", "G", "H"])], rng=random.Random(1))
        first4 = [rp.next() for _ in range(4)]
        self.assertEqual(sorted(p["start"] for p in first4), ["A", "B", "C", "D"])  # no reuse inside one round
        self.assertEqual(sorted(p["end"] for p in first4), ["E", "F", "G", "H"])
        with self.assertRaises(ValueError): T.make_picker("nope", pools)

    def test_store_roundtrip(self):
        st = C.S["store"]; t = three_stage(); st.put(t)
        self.assertIn("three", st.names()); self.assertEqual(st.get("three")["steps"][1]["id"], "m")
        st.put(T.builtin_default()); st.delete("three"); self.assertEqual(st.names(), ["default"])
        st.delete("default"); self.assertEqual(st.names(), [])  # empty store allowed (per-server)
        with self.assertRaises(ValueError): st.delete("default")  # missing
        with self.assertRaises(ValueError): st.put({"name": "../evil", "steps": []})

    def test_empty_step_name_ok(self):
        t = three_stage(); t["steps"][0]["name"] = ""
        self.assertEqual(T.validate(t), [])
        self.assertEqual(t["steps"][0]["name"], "")

    def test_store_rename(self):
        st = C.S["store"]; st.put(T.builtin_default()); t = three_stage(); st.put(t)
        r = st.rename("three", "three_renamed")
        self.assertEqual(r["name"], "three_renamed")
        self.assertIn("three_renamed", st.names()); self.assertNotIn("three", st.names())
        with self.assertRaises(ValueError): st.rename("three_renamed", "default")  # exists, no overwrite
        r = st.rename("three_renamed", "default", overwrite=True)
        self.assertEqual(r["name"], "default"); self.assertEqual(st.names(), ["default"])
        with self.assertRaises(ValueError): st.rename("default", "bad name")

    def test_example_templates_valid(self):
        import glob, os
        files = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "templates", "*.json"))
        self.assertTrue(files)
        # two candidates per station (drive-in LMn, drive-out LMnb) so selector examples can resolve
        C.S["precands"] = {k: [{"name": v, "dir": "in", "dist": 1.0, "lm": True}, {"name": v + "b", "dir": "out", "dist": 2.0, "lm": True}] for k, v in PREPOINTS.items()}
        for fp in files:
            with open(fp, encoding="utf-8") as f: t = json.load(f)
            self.assertEqual(T.validate(t), [], fp)
            C.make_draft({r: "AP%d" % (i + 1) for i, r in enumerate(T.pool_roles(t))}, t, {}, "dl-ex")

class AdapterInterfaceTest(unittest.TestCase):
    def test_registry_and_interface(self):
        self.assertIn("rds", ADAPTERS)
        a = get_adapter("rds", "http://x")
        self.assertIsInstance(a, DispatcherAdapter)
        self.assertNotIn("FAILED", a.terminal_states)
        for m in ("build_payload", "submit", "order_status", "cancel", "robots", "scene", "parse_stations", "parse_groups", "extract_geom", "download_maps", "decode_map"):
            self.assertTrue(callable(getattr(a, m)))
        with self.assertRaises(NotImplementedError): DispatcherAdapter("x").build_payload({})
        with self.assertRaises(ValueError): get_adapter("vda5050", "x")


class OpModePayloadTest(unittest.TestCase):
    """Per-step binTask|operation for RDS (and migration of legacy m4Mode)."""
    def setUp(self): fresh_core(self); C.S["prepoints"] = dict(PREPOINTS)

    def test_rds_bintask_omits_args_operation_keeps_args(self):
        from order_tester.adapters.rds import RdsAdapter
        ad = RdsAdapter("http://x")
        order = {"id": "dl-om", "priority": 1, "steps": [
            {"id": "a", "suffix": "-a", "location": "AP1", "operation": "ForkLoad", "opMode": "binTask",
             "args": {"end_height": 0.1, "recognize": True}},
            {"id": "b", "suffix": "-b", "location": "AP2", "operation": "ForkUnload", "opMode": "operation",
             "args": {"end_height": 0.09}},
            {"id": "c", "suffix": "-c", "location": "LM2", "operation": "Wait", "args": {"x": 1}},  # no opMode -> operation
        ]}
        bl = ad.build_payload(order)["blocks"]
        self.assertEqual(bl[0]["operation"], "ForkLoad"); self.assertNotIn("operation_args", bl[0]); self.assertNotIn("recognize", bl[0])
        self.assertEqual(bl[1]["operation_args"], {"end_height": 0.09})
        self.assertEqual(bl[2]["operation_args"], {"x": 1})

    def test_mixed_opmode_draft_and_m4mode_migrate(self):
        t = {"name": "mixom", "steps": [
            {"id": "a", "location": {"type": "pool", "pool": "start"}, "operation": "ForkLoad", "opMode": "binTask",
             "args": {"end_height": 0.1}},
            {"id": "b", "location": {"type": "pool", "pool": "end"}, "operation": "ForkUnload", "opMode": "operation",
             "args": {"end_height": 0.09}},
            {"id": "c", "location": {"type": "fixed", "station": "LM99"}, "operation": "Wait",
             "args": {"m4Mode": "binTask", "ignored": 1}},
        ]}
        self.assertEqual(T.validate(t), [])
        self.assertEqual(t["steps"][2]["opMode"], "binTask")
        self.assertNotIn("m4Mode", t["steps"][2]["args"])
        rec = C.make_draft({"start": "AP1", "end": "AP3"}, t, {}, "dl-mix")
        bl = rec["body"]["blocks"]
        self.assertEqual(bl[0]["operation"], "ForkLoad"); self.assertNotIn("operation_args", bl[0])
        self.assertEqual(bl[1]["operation_args"], {"end_height": 0.09})
        self.assertEqual(bl[2]["operation"], "Wait"); self.assertNotIn("operation_args", bl[2])

if __name__ == "__main__": unittest.main()

class CustomPoolTemplateTest(unittest.TestCase):
    """Template with two fixed-station steps + one step on a custom pool."""
    def test_fixed_plus_custom_pool(self):
        fresh_core(self); C.S["prepoints"] = dict(PREPOINTS)
        t = {"name": "custom-pool-demo", "steps": [
            {"id": "s", "location": {"type": "fixed", "station": "AP5"}, "operation": "JackLoad", "args": {}},
            {"id": "e", "location": {"type": "fixed", "station": "LM6"}, "operation": "JackUnload", "args": {}},
            {"id": "step1", "location": {"type": "pool", "pool": "STP"}, "operation": "Wait", "args": {}}]}
        C.S["store"].put(t); t = C.S["store"].get("custom-pool-demo")
        self.assertEqual(t["pools"], ["STP"])
        b, tt, pools, warn, err = C.prepare_cfg({"templateName": "custom-pool-demo", "pools": {"start": [], "end": [], "STP": ["AP7", "AP8"]}})
        self.assertEqual(err, ""); self.assertEqual(pools, {"STP": ["AP7", "AP8"]})
        res = C.generate_drafts(dict(b, count=None), tt, pools)
        self.assertEqual(res["n"], 2)  # default count = size of the template's first pool (STP)
        locs = sorted(C.S["orders"][i]["body"]["blocks"][2]["location"] for i in res["ids"])
        self.assertEqual(locs, ["AP7", "AP8"])
        b2, _, _, _, err2 = C.prepare_cfg({"templateName": "custom-pool-demo", "pools": {"start": ["AP1"]}})
        self.assertIn("STP", err2)  # empty template pool is reported even if start is filled


def end_only_default():
    """Default-template variant: pick (start) steps disabled, only the drop side enabled; stored pools still list start."""
    t = T.builtin_default(); t["pools"] = ["start", "end"]
    for s in t["steps"]:
        if s["id"] in ("pre", "s", "script"): s["enabled"] = False
    return t

class EndOnlyTemplateTest(unittest.TestCase):
    def setUp(self): fresh_core(self); C.S["prepoints"] = dict(PREPOINTS)

    def test_roles_ignore_disabled_pool_steps(self):
        t = end_only_default(); self.assertEqual(T.validate(t), [])
        self.assertEqual(T.pool_roles(t), ["end"]); self.assertEqual(t["pools"], ["end"])
        # an enabled pre step deriving from a disabled pool step still needs that pool
        t2 = end_only_default(); t2["steps"][0]["enabled"] = True; T.validate(t2)
        self.assertEqual(T.pool_roles(t2), ["start", "end"])

    def test_generate_without_start_pool(self):
        t = end_only_default(); T.validate(t)
        b = {"template": t, "pools": {"start": [], "end": ["AP3", "AP4"]}, "strategy": "random", "count": 2}
        cfg, tt, pools, warn, err = C.prepare_cfg(b)
        self.assertEqual(err, ""); self.assertEqual(list(pools), ["end"])
        r = C.generate_drafts(cfg, tt, pools)
        self.assertEqual(r["n"], 2); self.assertEqual(r["skipped"], [])
        rec = C.S["orders"][r["ids"][0]]
        self.assertEqual(len(rec["pair"]), 1); self.assertEqual(rec["pickPre"], "")
        self.assertIn(rec["pair"][0], [x["location"] for x in rec["body"]["blocks"]])
        # empty end pool is still rejected
        cfg, tt, pools, warn, err = C.prepare_cfg({"template": end_only_default(), "pools": {"start": ["AP1"], "end": []}})
        self.assertIn("end", err); self.assertNotIn("start", err)
