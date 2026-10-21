import json, os, re, unittest
D = os.path.join(os.path.dirname(__file__), "..", "order_tester")

class StationListReadOnlyTest(unittest.TestCase):
    def setUp(self):
        self.js = open(os.path.join(D, "static", "app.js"), encoding="utf-8").read()
    def body(self):
        i = self.js.index("function renderSt(")
        return self.js[i:self.js.index("let hlSt", i)]
    def test_no_add_buttons_and_lists_only_pooled(self):
        b = self.body()
        self.assertNotIn("pick(", b)          # per-row pool buttons removed
        self.assertIn("inSel", b)            # rows come from pool membership, not all scene stations
        self.assertNotIn("stations.filter(", b)
        self.assertIn("st.emptySel", b)
    def test_i18n_keys(self):
        for l in ("zh", "en"):
            d = json.load(open(os.path.join(D, "i18n", l + ".json"), encoding="utf-8"))
            for k in ("st.pick", "st.emptySel", "st.selOnly"): self.assertTrue(d.get(k), (l, k))
