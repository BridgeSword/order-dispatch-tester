# -*- coding: utf-8 -*-
"""settings.json / drafts.json / sent_orders.json from the legacy rds_tester.py are migrated transparently."""
import json, os, random, unittest
from helpers import C, fresh_core, PREPOINTS
import legacy_reference as L
from order_tester import templates as T

LEGACY_FIELDS = {  # what the v1 page stored in settings.json "fields" (placeholder stations)
    "base": "http://rds.example:8088", "poll": "2", "stuck": "90", "still": "60", "noself": True, "noreuse": True,
    "grp": "grpA", "veh": "", "pri": "2", "label": "", "pre_on": True,
    "st_op": "ForkLoad", "st_args": '{"disable_laser_id":3,"end_height":0.2,"rec_height":0.09,"rec_target_obs":true,"recfile":"plt/p0005.plt","recognize":true,"start_height":0.09}',
    "en_op": "ForkUnload", "en_args": '{"end_height":0.09,"rec_dir":0,"rec_target_obs":false,"recfile":"plt/p0005.plt","recognize":false,"start_height":0.2}',
    "scr_on": True, "scr_name": "userpy/rec_retry_versatile.py", "scr_op": "locDetectMid70D", "scr_rec": "palletobject/p0001.palletobject",
    "lift_on": True, "lift_op": "ForkHeight", "lift_args": '{"end_height":0.2}', "pre_ov": "AP5=LM55", "cnt": "4", "cnt_auto": "1", "tab": "ord", "iv": "5", "maxa": "5"}
LEGACY_SETTINGS = {"base": "http://rds.example:8088", "pollSec": 2, "fields": LEGACY_FIELDS, "pm": "S",
    "vsPerBlock": {"pre": {"on": False, "head": "1.2", "tail": "1.3"}, "s": {"on": True, "head": "1.4", "tail": "1.5"}, "script": {"on": False, "head": "1.539", "tail": "1.539"},
                   "e": {"on": True, "head": "1.539", "tail": "1.539"}, "lift": {"on": True, "head": "1.6", "tail": "1.539"}},
    "vsBlocks": ["s", "e", "lift"], "starts": ["AP1", "AP2", "AP3", "AP5"], "ends": ["AP6", "AP7", "AP8", "AP9"]}

def legacy_cfg_from_settings(st):
    """what the v1 page's orderCfg() sent for these settings"""
    f = st["fields"]; ov = {}
    for l in f["pre_ov"].split("\n"):
        a = [x for x in l.replace("=", " ").split() if x]
        if len(a) >= 2: ov[a[0]] = a[1]
    vs = {r: {"head": float(v["head"]), "tail": float(v["tail"])} for r, v in st["vsPerBlock"].items() if v["on"]}
    return {"vehicle": f["veh"], "group": f["grp"], "priority": int(f["pri"]), "label": f["label"], "startOp": f["st_op"], "startArgs": json.loads(f["st_args"]),
            "endOp": f["en_op"], "endArgs": json.loads(f["en_args"]), "pickPreOn": f["pre_on"], "scriptOn": f["scr_on"], "scriptName": f["scr_name"],
            "scriptOp": f["scr_op"], "scriptRecFile": f["scr_rec"], "liftOn": f["lift_on"], "liftOp": f["lift_op"], "liftArgs": json.loads(f["lift_args"]),
            "preOverrides": ov, "vsPerBlock": vs}

class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.d = fresh_core(self)

    def write(self, name, obj):
        with open(os.path.join(self.d, name), "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False)

    def test_settings_to_template_identical_output(self):
        self.write("settings.json", LEGACY_SETTINGS)
        notes = C.migrate_templates(); self.assertTrue(notes)
        st = C.load_settings()
        self.assertEqual(st["pools"], {"start": LEGACY_SETTINGS["starts"], "end": LEGACY_SETTINGS["ends"]})
        self.assertEqual(st["activeTemplate"], "default"); self.assertEqual(st["fields"], LEGACY_FIELDS)  # nothing lost
        self.assertTrue(os.path.exists(os.path.join(self.d, "settings.json.bak-v1")))
        t = C.S["store"].get("default")
        self.assertEqual(t["steps"][0]["variableShape"], {"head": 1.2, "tail": 1.3}); self.assertFalse(t["steps"][0]["vsOn"])  # remembered, disabled
        legacy = legacy_cfg_from_settings(LEGACY_SETTINGS)
        L.S["prepoints"] = dict(PREPOINTS); C.S["prepoints"] = dict(PREPOINTS)
        new_cfg = {"vehicle": "", "group": "grpA", "priority": 2, "label": "", "preOverrides": legacy["preOverrides"]}
        for seed in range(5):
            random.seed(seed); pk = L.Picker(LEGACY_SETTINGS["starts"], LEGACY_SETTINGS["ends"])
            a = [L.make_draft(pk.next(), legacy, "dl-%d" % i)["body"] for i in range(8)]
            random.seed(seed); pk2 = T.make_picker("random", [("start", LEGACY_SETTINGS["starts"]), ("end", LEGACY_SETTINGS["ends"])])
            b = [C.make_draft(pk2.next(), t, new_cfg, "dl-%d" % i)["body"] for i in range(8)]
            self.assertEqual(json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False))
        # idempotent
        self.assertEqual(C.migrate_templates(), [])

    def test_empty_install_gets_builtin(self):
        C.migrate_templates()
        self.assertEqual(json.dumps(C.S["store"].get("default")["steps"]), json.dumps(T.validate(T.builtin_default()) or T.builtin_default()["steps"]))


    def test_no_recreate_default_when_others_exist(self):
        # rename-away scenario: other templates exist, do not recreate default.json
        C.S["store"].put({"name": "AnyPallet", "title": "x", "version": 1, "pools": ["start", "end"],
            "steps": [{"id": "s", "name": "", "location": {"type": "pool", "pool": "start"}, "operation": "Wait", "args": {}}]})
        if "default" in C.S["store"].names():
            C.S["store"].delete("default")
        C.save_settings({"activeTemplate": "default"})  # stale pointer after rename
        notes = C.migrate_templates()
        self.assertNotIn("default", C.S["store"].names())
        self.assertTrue(all("default.json created" not in n for n in notes))
        self.assertEqual(C.load_settings().get("activeTemplate"), "AnyPallet")

    def test_drafts_and_sent_upgrade(self):
        now = 1.7e9
        legacy_draft = {"id": "dl-aaa", "pair": ["AP1", "AP6"], "pre": "LM6", "state": "待下发", "sent": now, "changed": now, "created": now, "sig": "", "error": None,
                        "body": {"id": "dl-aaa", "complete": True, "priority": 1, "additionalProperties": {}, "blocks": []}}
        legacy_sent = [{"id": "dl-bbb", "pair": ["AP2", "AP7"], "state": "FAILED", "ended": now + 50, "sent": now, "changed": now, "sig": "", "error": None, "body": {"group": "grpA"}},
                       {"id": "dl-ccc", "pair": ["AP3", "AP8"], "state": "FINISHED", "ended": now + 60, "sent": now + 1, "changed": now, "sig": "", "error": None, "body": {}}]
        self.write("drafts.json", [legacy_draft]); self.write("sent_orders.json", legacy_sent)
        self.assertEqual(C.load_drafts(), 1); self.assertEqual(C.load_sent(), 2)
        o = C.S["orders"]
        self.assertEqual(o["dl-aaa"]["picks"], {"start": "AP1", "end": "AP6"}); self.assertEqual(o["dl-aaa"]["template"], "default")
        self.assertNotIn("ended", o["dl-bbb"]); self.assertTrue(o["dl-bbb"]["_reopened"])  # FAILED is not terminal: re-monitored
        self.assertIn("ended", o["dl-ccc"])
        self.assertTrue(o["dl-bbb"]["batch"] and o["dl-ccc"]["batch"])  # legacy history batches assigned
        self.assertEqual(o["dl-bbb"]["batchMeta"]["kind"], "hist")
        C.save_drafts(); C.save_sent()
        with open(os.path.join(self.d, "drafts.json"), encoding="utf-8") as f: raw = json.load(f)
        drafts = (next(iter(raw["byServer"].values())) if isinstance(raw, dict) and isinstance(raw.get("byServer"), dict) else raw)
        self.assertEqual(drafts[0]["picks"]["end"], "AP6")

    def test_swap_legacy_draft(self):
        C.S["prepoints"] = dict(PREPOINTS); C.migrate_templates()
        rec = L.make_draft if False else None
        L.S["prepoints"] = dict(PREPOINTS)
        from test_regression import UI_DEFAULT
        d = L.make_draft(["AP1", "AP6"], dict(UI_DEFAULT, group="grpA"), "dl-sw"); self.write("drafts.json", [d]); C.load_drafts()
        r = C.swap_drafts(["dl-sw"], {}, C.S["store"].get("default"))
        self.assertEqual(r["n"], 1)
        expect = L.make_draft(["AP6", "AP1"], dict(UI_DEFAULT, group="grpA"), "dl-sw")["body"]
        self.assertEqual(json.dumps(C.S["orders"]["dl-sw"]["body"]), json.dumps(expect))
        self.assertEqual(C.S["orders"]["dl-sw"]["swapped"], 1)

if __name__ == "__main__": unittest.main()

class SwapOwnTemplateTest(unittest.TestCase):
    def test_swap_uses_draft_template(self):
        fresh_core(self); C.S["prepoints"] = dict(PREPOINTS); C.migrate_templates()
        t3 = {"name": "three", "steps": [{"id": "a", "location": {"type": "pool", "pool": "start"}, "operation": "Wait", "args": {}},
                                         {"id": "m", "location": {"type": "pool", "pool": "mid"}, "operation": "Wait", "args": {}},
                                         {"id": "b", "location": {"type": "pool", "pool": "end"}, "operation": "Wait", "args": {}}]}
        C.S["store"].put(t3)
        rec = C.make_draft({"start": "AP1", "mid": "AP2", "end": "AP3"}, C.S["store"].get("three"), {}, "dl-3"); C.S["orders"]["dl-3"] = rec
        r = C.swap_drafts(["dl-3"], {}, C.S["store"].get("default"))
        self.assertEqual(r["n"], 1); self.assertEqual(C.S["orders"]["dl-3"]["pair"], ["AP3", "AP2", "AP1"])
        self.assertEqual(C.S["orders"]["dl-3"]["template"], "three")
