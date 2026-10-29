# -*- coding: utf-8 -*-
"""Per-dispatcher-server settings: migration, load/save isolation, select."""
import json, os, unittest
from helpers import C, fresh_core

FLAT = {
    "base": "http://rds-a.example:8088",
    "pollSec": 3,
    "adapter": "rds",
    "lang": "en",
    "fields": {"stuck": "90", "still": "60", "poll": "3", "bbb": True},
    "pools": {"start": ["AP1", "AP2"], "end": ["AP9"]},
    "activeTemplate": "default",
    "strategy": "cartesian",
    "pm": "start",
    "m4": {"active": "lab", "profiles": {
        "lab": {"base": "http://m4-lab.example:8080", "appId": "id1", "appKey": "SECRETKEY", "sceneId": "sc1"},
        "prod": {"base": "http://m4-prod.example:8080", "appId": "id2", "appKey": "OTHERSECRET", "sceneId": "sc2"},
    }},
}

class ServerSettingsTest(unittest.TestCase):
    def setUp(self):
        self.d = fresh_core(self)

    def write(self, name, obj):
        with open(os.path.join(self.d, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def read(self, name):
        with open(os.path.join(self.d, name), encoding="utf-8") as f:
            return json.load(f)

    def test_migrate_flat_to_servers(self):
        self.write("settings.json", FLAT)
        notes = C.migrate_servers()
        self.assertTrue(any("migrated flat" in n for n in notes))
        bak = os.path.join(self.d, "settings.pre_server.json")
        self.assertTrue(os.path.isfile(bak))
        self.assertEqual(self.read("settings.pre_server.json")["base"], FLAT["base"])
        raw = self.read("settings.json")
        self.assertEqual(raw["version"], 2)
        self.assertEqual(raw["lang"], "en")
        self.assertGreaterEqual(len(raw["servers"]), 2)  # primary + extra m4 profile
        # flat view keeps previous values under old base
        st = C.load_settings()
        self.assertEqual(st["base"], "http://rds-a.example:8088")
        self.assertEqual(st["pools"]["start"], ["AP1", "AP2"])
        self.assertEqual(st["activeTemplate"], "default")
        self.assertEqual(st["strategy"], "cartesian")
        self.assertEqual(st["lang"], "en")
        self.assertIn("currentServerId", st)
        # secrets not in servers summary
        for s in st["servers"]:
            self.assertNotIn("appKey", s)
            self.assertNotIn("password", s)
        # idempotent
        self.assertEqual(C.migrate_servers(), [])

    def test_two_servers_pools_isolated(self):
        C.migrate_servers()
        C.save_settings({"base": "http://a.example:1", "pools": {"start": ["A1"], "end": ["A9"]}, "activeTemplate": "tA", "name": "Alpha"})
        # rename current for clarity
        sid_a = C.load_settings()["currentServerId"]
        C.rename_server(sid_a, "Alpha")
        sid_b = C.add_server("Beta", "http://b.example:2", "rds", activate=False)
        C.select_server(sid_b)
        C.save_settings({"pools": {"start": ["B1", "B2"], "end": ["B9"]}, "activeTemplate": "tB"})
        st_b = C.load_settings()
        self.assertEqual(st_b["pools"]["start"], ["B1", "B2"])
        self.assertEqual(st_b["activeTemplate"], "tB")
        self.assertEqual(st_b["base"], "http://b.example:2")
        C.select_server(sid_a)
        st_a = C.load_settings()
        self.assertEqual(st_a["pools"]["start"], ["A1"])
        self.assertEqual(st_a["activeTemplate"], "tA")
        self.assertEqual(st_a["base"], "http://a.example:1")
        # lang stays global
        C.save_settings({"lang": "zh"})
        C.select_server(sid_b)
        self.assertEqual(C.load_settings()["lang"], "zh")

    def test_new_url_gets_empty_defaults(self):
        C.migrate_servers()
        C.save_settings({"pools": {"start": ["X"], "end": ["Y"]}})
        sid = C.add_server("New", "http://new.example:9", "rds", activate=False)
        C.select_server(sid)
        st = C.load_settings()
        self.assertEqual(st["pools"], {"start": [], "end": []})
        self.assertEqual(st["base"], "http://new.example:9")
        self.assertEqual(st["name"], "New")

    def test_add_server_without_base_is_blank(self):
        """UI must not clone the current form URL; blank base until user fills."""
        C.migrate_servers()
        C.save_settings({"base": "http://a.example:5800", "pools": {"start": ["X"], "end": ["Y"]}})
        sid = C.add_server("Blank", None, "rds", activate=False)
        C.select_server(sid)
        st = C.load_settings()
        self.assertEqual(st["currentServerId"], sid)
        self.assertEqual(st["base"], "")
        self.assertEqual(st["name"], "Blank")
        self.assertEqual(st["pools"], {"start": [], "end": []})
        self.assertEqual(C.S["orders"], {})

    def test_add_server_requires_name(self):
        C.migrate_servers()
        self.assertIsNone(C.add_server(None, "http://x.example", "rds"))
        self.assertIsNone(C.add_server("", "http://x.example", "rds"))
        self.assertIsNone(C.add_server("   ", None, "rds"))
        n_before = len(C.load_settings()["servers"])
        sid = C.add_server("MustHave", None, "rds", activate=False)
        self.assertTrue(sid)
        self.assertEqual(len(C.load_settings()["servers"]), n_before + 1)

    def test_delete_last_refused_and_confirm_path(self):
        C.migrate_servers()
        sid = C.load_settings()["currentServerId"]
        ok, err = C.delete_server(sid)
        self.assertFalse(ok); self.assertEqual(err, "last")
        other = C.add_server("Other", "http://o.example:1", activate=False)
        ok, cur = C.delete_server(sid)
        self.assertTrue(ok); self.assertEqual(cur, other)
        self.assertEqual(C.load_settings()["currentServerId"], other)

    def test_normalize_base_trailing_slash(self):
        self.assertEqual(C.normalize_base("http://x.example:8088/"), "http://x.example:8088")
        self.assertEqual(C.normalize_base("  http://x.example:8088/  "), "http://x.example:8088")
        C.migrate_servers()
        C.save_settings({"base": "http://slash.example:8/"})
        self.assertEqual(C.load_settings()["base"], "http://slash.example:8")

    def test_drafts_and_scene_scoped(self):
        C.migrate_servers()
        sid_a = C.load_settings()["currentServerId"]
        C.S["orders"]["dl-a"] = {"id": "dl-a", "state": C.DRAFT, "pair": ["AP1", "AP2"], "picks": {"start": "AP1", "end": "AP2"}, "template": "default", "adapter": "rds", "sent": 1, "changed": 1}
        C.save_drafts()
        C.save_scene_cache({"ok": True, "stations": [{"name": "AP1", "pre": "LM1"}], "loadedAt": 1.0})
        sid_b = C.add_server("B", "http://b.example:2", activate=False)
        C.select_server(sid_b)
        self.assertNotIn("dl-a", C.S["orders"])
        self.assertFalse(C.S.get("geom") and C.S["geom"].get("stations"))
        C.S["orders"]["dl-b"] = {"id": "dl-b", "state": C.DRAFT, "pair": ["BP1", "BP2"], "picks": {"start": "BP1", "end": "BP2"}, "template": "default", "adapter": "rds", "sent": 1, "changed": 1}
        C.save_drafts()
        C.select_server(sid_a)
        self.assertIn("dl-a", C.S["orders"])
        self.assertNotIn("dl-b", C.S["orders"])
        self.assertEqual(C.S["geom"]["stations"][0]["name"], "AP1")
        # nested files
        sc = self.read("scene_cache.json")
        self.assertIn("byServer", sc)
        self.assertIn(sid_a, sc["byServer"])
        dr = self.read("drafts.json")
        self.assertIn("byServer", dr)
        self.assertTrue(any(o["id"] == "dl-a" for o in dr["byServer"][sid_a]))

    def test_sent_orders_isolated_per_server(self):
        """Server A sent orders must not appear on B; saving B must not wipe A."""
        C.migrate_servers()
        sid_a = C.load_settings()["currentServerId"]
        now = 1.7e9
        C.S["orders"]["dl-a1"] = {"id": "dl-a1", "state": "RUNNING", "pair": ["AP1", "AP2"], "picks": {"start": "AP1", "end": "AP2"},
                                  "template": "default", "adapter": "rds", "sent": now, "changed": now, "sig": "", "error": None, "vehicle": ""}
        C.save_sent()
        # flat -> nested under current, with backup
        raw = self.read("sent_orders.json")
        self.assertIn("byServer", raw)
        self.assertIn(sid_a, raw["byServer"])
        bak = os.path.join(self.d, "sent_orders.pre_server.json")
        # backup only created when migrating a pre-existing flat file; ensure nesting works either way
        sid_b = C.add_server("Beta", "", "rds", activate=False)
        C.select_server(sid_b)
        self.assertNotIn("dl-a1", C.S["orders"])
        self.assertEqual([o for o in C.S["orders"].values() if o.get("state") != C.DRAFT], [])
        # B gets its own sent order
        C.S["orders"]["dl-b1"] = {"id": "dl-b1", "state": "FINISHED", "pair": ["BP1", "BP2"], "picks": {"start": "BP1", "end": "BP2"},
                                  "template": "default", "adapter": "rds", "sent": now, "changed": now, "ended": now + 1, "sig": "", "error": None, "vehicle": ""}
        C.save_sent()
        raw = self.read("sent_orders.json")
        self.assertTrue(any(o["id"] == "dl-a1" for o in raw["byServer"][sid_a]))
        self.assertTrue(any(o["id"] == "dl-b1" for o in raw["byServer"][sid_b]))
        # switch back: A's orders return, B's gone from memory
        C.select_server(sid_a)
        self.assertIn("dl-a1", C.S["orders"])
        self.assertNotIn("dl-b1", C.S["orders"])
        # add another empty server then select (API path): no A's/B's sent
        sid_c = C.add_server("Gamma", None, activate=False)
        self.assertIsNotNone(sid_c)
        C.select_server(sid_c)
        self.assertNotIn("dl-a1", C.S["orders"])
        self.assertNotIn("dl-b1", C.S["orders"])
        # saving empty C does not wipe A/B buckets
        C.save_sent()
        raw = self.read("sent_orders.json")
        self.assertTrue(any(o["id"] == "dl-a1" for o in raw["byServer"][sid_a]))
        self.assertTrue(any(o["id"] == "dl-b1" for o in raw["byServer"][sid_b]))

    def test_migrate_flat_sent_under_current(self):
        C.migrate_servers()
        sid = C.load_settings()["currentServerId"]
        flat = [{"id": "dl-legacy", "state": "FINISHED", "pair": ["A", "B"], "sent": 1.0, "changed": 1.0, "ended": 2.0, "sig": "", "error": None}]
        self.write("sent_orders.json", flat)
        C._migrate_sent_nesting()
        raw = self.read("sent_orders.json")
        self.assertIn("byServer", raw)
        self.assertIn(sid, raw["byServer"])
        self.assertEqual(raw["byServer"][sid][0]["id"], "dl-legacy")
        bak = os.path.join(self.d, "sent_orders.pre_server.json")
        self.assertTrue(os.path.isfile(bak))
        self.assertEqual(self.read("sent_orders.pre_server.json")[0]["id"], "dl-legacy")
        # idempotent
        C._migrate_sent_nesting()
        raw2 = self.read("sent_orders.json")
        self.assertEqual(raw2, raw)
        # load only current bucket
        C.S["orders"].clear()
        self.assertEqual(C.load_sent(), 1)
        self.assertIn("dl-legacy", C.S["orders"])

    def test_new_server_adapter_always_rds(self):
        """New server must be RDS even when current server is M4 (never inherit)."""
        C.migrate_servers()
        C.save_settings({"adapter": "m4"})
        C.set_adapter("m4")
        self.assertEqual(C.AD().name, "m4")
        sid = C.add_server("RdsFresh", None, "m4", activate=False)  # even if caller passes m4
        self.assertTrue(sid)
        raw = self.read("settings.json")
        srv = next(s for s in raw["servers"] if s["id"] == sid)
        self.assertEqual(srv["adapter"], "rds")
        C.select_server(sid)
        self.assertEqual(C.AD().name, "rds")
        self.assertEqual(C.load_settings()["adapter"], "rds")

    def test_switch_clears_geom_then_loads_own_cache(self):
        """No leftover LM/point cloud when switching to a new/empty server."""
        C.migrate_servers()
        sid_a = C.load_settings()["currentServerId"]
        C.save_scene_cache({"ok": True, "stations": [{"name": "LM99", "pre": "", "x": 1, "y": 2}],
                            "curves": [], "points": [0, 0, 1, 1], "npoints": 2, "loadedAt": 1.0, "bounds": {}})
        C.restore_scene_cache()
        self.assertTrue(C.S.get("geom") and C.S["geom"]["stations"][0]["name"] == "LM99")
        sid_b = C.add_server("EmptyMap", None, activate=False)
        C.select_server(sid_b)
        self.assertFalse(C.S.get("geom"))
        self.assertEqual(C.S.get("prepoints") or {}, {})
        self.assertIsNone(C.S.get("st_cache"))
        # A's cache untouched
        sc = self.read("scene_cache.json")
        self.assertEqual(sc["byServer"][sid_a]["stations"][0]["name"], "LM99")
        self.assertTrue(sid_b not in sc.get("byServer", {}) or not (sc["byServer"].get(sid_b) or {}).get("stations"))

    def test_templates_per_server_isolated(self):
        """Shared templates/ migrate into current server; new server gets builtin default."""
        C.migrate_servers()
        sid_a = C.load_settings()["currentServerId"]
        # simulate legacy shared templates at top level
        root = C.P["templates"]
        import os, json
        os.makedirs(root, exist_ok=True)
        # ensure flat file (bind may already be nested — write flat then remigrate)
        flat = os.path.join(root, "shared_tpl.json")
        with open(flat, "w", encoding="utf-8") as f:
            json.dump({"name": "shared_tpl", "title": "x", "version": 1, "pools": ["start"],
                       "steps": [{"id": "s", "location": {"type": "pool", "pool": "start"}, "operation": "Wait", "args": {}}]}, f)
        notes = C.migrate_templates()
        self.assertTrue(any("migrated" in n and "template" in n for n in notes) or "shared_tpl" in C.S["store"].names())
        self.assertIn("shared_tpl", C.S["store"].names())
        self.assertTrue(os.path.isfile(os.path.join(root, sid_a, "shared_tpl.json")))
        self.assertFalse(os.path.isfile(flat))
        sid_b = C.add_server("NoTpl", None, activate=False)
        C.select_server(sid_b)
        self.assertEqual(C.S["store"].names(), ["default"])
        self.assertEqual(C.load_settings().get("activeTemplate"), "default")
        self.assertTrue(os.path.isfile(os.path.join(root, sid_b, "default.json")))
        # A still has its template (not the new default)
        C.select_server(sid_a)
        self.assertIn("shared_tpl", C.S["store"].names())
        self.assertNotIn("default", C.S["store"].names())  # A was not re-seeded

    def test_add_server_seeds_default_template(self):
        """add_server writes builtin default into templates/<id>/ and sets activeTemplate."""
        C.migrate_servers()
        sid = C.add_server("WithDefault", None, activate=False)
        self.assertTrue(sid)
        import os
        path = os.path.join(C.P["templates"], sid, "default.json")
        self.assertTrue(os.path.isfile(path))
        raw = self.read("settings.json")
        srv = next(s for s in raw["servers"] if s["id"] == sid)
        self.assertEqual(srv.get("activeTemplate"), "default")
        C.select_server(sid)
        self.assertEqual(C.S["store"].names(), ["default"])
        self.assertEqual(C.load_settings().get("activeTemplate"), "default")
        t = C.S["store"].get("default")
        self.assertEqual(t["name"], "default")
        self.assertTrue(t.get("steps"))
        # deleting all templates is intentional — select again must NOT re-seed
        C.S["store"].delete("default")
        C.save_settings({"activeTemplate": ""})
        self.assertEqual(C.S["store"].names(), [])
        sid_a = next(s["id"] for s in C.load_settings()["servers"] if s["id"] != sid)
        C.select_server(sid_a)
        C.select_server(sid)
        self.assertEqual(C.S["store"].names(), [])
        self.assertEqual(C.load_settings().get("activeTemplate") or "", "")

    def test_switch_server_clears_robots(self):
        """Previous server's robots must not linger after select; poll replaces not merges."""
        import unittest.mock as mock
        C.migrate_servers()
        sid_a = C.load_settings()["currentServerId"]
        now = 1.7e9
        C.S["robots"]["RIL-AP-1"] = {"name": "RIL-AP-1", "x": 1.0, "y": 2.0, "station": "", "order": "",
                                     "orderState": "", "orderActive": False, "group": "", "dispatchable": True,
                                     "connected": False, "blocked": False, "battery": None, "angle": 0, "moved": now}
        C.S["opos"]["dl-x"] = (1.0, 2.0, 0.0, "RIL-AP-1")
        C.S["robots_raw"] = True
        sid_b = C.add_server("LocalM4", None, "m4", activate=False)
        C.select_server(sid_b)
        self.assertEqual(C.S["robots"], {})
        self.assertEqual(C.S["opos"], {})
        self.assertIsNone(C.S["robots_raw"])
        # poll replace: seed stale robot then rebuild from adapter list without it
        C.S["robots"]["STALE"] = {"name": "STALE", "x": None, "y": None, "station": "", "order": "",
                                  "orderState": "", "orderActive": False, "group": "", "dispatchable": None,
                                  "connected": False, "blocked": False, "battery": None, "angle": None, "moved": now}
        ad = C.AD()
        keep = {"name": "AMB-01", "x": 3.0, "y": 4.0, "station": "AP1", "order": "", "group": "g1",
                "dispatchable": True, "connected": True, "blocked": False, "battery": 0.9, "angle": 0.1}
        C.S["orders"].clear()
        with mock.patch.object(ad, "robots", return_value=[keep]):
            C.poll_once()
        self.assertNotIn("STALE", C.S["robots"])
        self.assertIn("AMB-01", C.S["robots"])
        self.assertEqual(C.S["robots"]["AMB-01"]["x"], 3.0)
        # empty list clears all
        with mock.patch.object(ad, "robots", return_value=[]):
            C.poll_once()
        self.assertEqual(C.S["robots"], {})
        # None leaves empty (does not resurrect)
        with mock.patch.object(ad, "robots", return_value=None):
            C.poll_once()
        self.assertEqual(C.S["robots"], {})
        C.select_server(sid_a)
        self.assertEqual(C.S["robots"], {})


    def test_m4_save_syncs_server_base_and_summary_fallback(self):
        """m4_save writes server.base; summary falls back to profile base if server.base blank."""
        C.migrate_servers()
        C.save_settings({"adapter": "m4", "base": ""})  # mimic saveCfg clearing base for M4
        C.m4_save("default", {"base": "http://127.0.0.1:5800/", "appId": "i", "appKey": "k", "sceneId": "sc"})
        st = C.load_settings()
        self.assertEqual(st["base"], "http://127.0.0.1:5800")  # trailing slash normalized
        summary = {s["id"]: s for s in st["servers"]}
        cur = summary[st["currentServerId"]]
        self.assertEqual(cur["base"], "http://127.0.0.1:5800")
        self.assertEqual(cur["adapter"], "m4")
        # old settings: only profile base, empty server.base — summary still shows URL
        raw = self.read("settings.json")
        for s in raw["servers"]:
            if s.get("id") == st["currentServerId"]:
                s["base"] = ""
                s["adapter"] = "m4"
                s["m4"] = {"active": "default", "profiles": {"default": {"base": "http://127.0.0.1:5800", "appId": "i", "appKey": "k"}}}
        self.write("settings.json", raw)
        lst = C.servers_list()
        hit = next(s for s in lst["servers"] if s["id"] == st["currentServerId"])
        self.assertEqual(hit["base"], "http://127.0.0.1:5800")

    def test_masked_settings_no_secrets(self):
        C.migrate_servers()
        C.m4_save("mock", {"base": "http://m4.example", "appId": "i", "appKey": "TOPSECRET", "password": "PWD"})
        blob = json.dumps(C.masked_settings())
        self.assertNotIn("TOPSECRET", blob)
        self.assertNotIn("PWD", blob)

if __name__ == "__main__":
    unittest.main()
