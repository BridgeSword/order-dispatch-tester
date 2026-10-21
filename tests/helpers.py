import os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from order_tester import core as C

def fresh_core(test, base="http://127.0.0.1:9"):
    d = tempfile.mkdtemp(prefix="odt-test-"); test.addCleanup(shutil.rmtree, d, True)
    C.init(d, base=base)
    C.S.update(orders={}, prepoints={}, running=False, robots={}, opos={}, omovelog={}, odcache={}, groups=[], robot_group={}, geom=None, groups_try=0); C.S.pop("st_cache", None)
    return d

# placeholder scene: AP<n> stations, pre-point LM<n>
PREPOINTS = {"AP%d" % i: "LM%d" % i for i in range(1, 13)}
