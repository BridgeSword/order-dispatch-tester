# -*- coding: utf-8 -*-
"""HTTP server (stdlib). python -m order_tester [--port 5088] [--rds URL] [--data DIR] [--adapter rds]"""
import argparse, json, os, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import core as C, templates as T, i18n
from .core import S, lock, DRAFT

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, ctype="application/json; charset=utf-8", extra=None):
        b = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")
    def q(self):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))

    def do_GET(self):
        p = self.path; path = urllib.parse.urlparse(p).path
        if path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as f: html = f.read()
            v = str(int(max(os.path.getmtime(os.path.join(STATIC, n)) for n in os.listdir(STATIC))))
            html = html.replace(b'/static/app.js"', b'/static/app.js?v=' + v.encode() + b'"')
            return self.send(html, ctype="text/html; charset=utf-8", extra={"Cache-Control": "no-store"})
        if path == "/favicon.ico": return self.send(b"", 204, ctype="image/x-icon")
        if path.startswith("/static/"):
            fn = os.path.basename(path)
            fp = os.path.join(STATIC, fn)
            if fn and os.path.isfile(fp):
                ct = {"js": "application/javascript", "css": "text/css", "html": "text/html"}.get(fn.rsplit(".", 1)[-1], "application/octet-stream")
                with open(fp, "rb") as f: return self.send(f.read(), ctype=ct + "; charset=utf-8", extra={"Cache-Control": "no-store"})
            return self.send({"err": "not found"}, 404)
        if path == "/api/i18n":
            lang = self.q().get("lang") or C.load_settings().get("lang") or "zh"
            return self.send({"lang": lang if lang in i18n.LANGS else "zh", "langs": list(i18n.LANGS), "t": i18n.table(lang)})
        if path == "/api/stations":
            c = S.get("st_cache")
            if c and "refresh=1" not in p: return self.send({"ok": True, "stations": c[1], "cached": True})
            stations, err = C.load_scene_stations()
            if stations is None: return self.send({"ok": False, "err": C.msg("srv.sceneFail", err=err)})
            return self.send({"ok": True, "stations": stations})
        if path == "/api/scene_job": return self.send(C.scene_job_status(self.q().get("id", "")))
        if path == "/api/scene_geom":
            if "cached=1" in p: return self.send(S.get("geom") or {"ok": False, "none": True})
            if "async=1" in p: return self.send({"ok": True, "job": C.start_scene_job(refresh="refresh=1" in p)})
            if "refresh=1" in p or not S.get("geom"):
                try: return self.send(C.build_geom(refresh="refresh=1" in p))
                except Exception as e: return self.send({"ok": False, "err": str(e)})
            return self.send(S["geom"])
        if path == "/api/order":
            o = S["orders"].get(self.q().get("id", ""))
            return self.send({"ok": bool(o), "body": o and o.get("body")})
        if path == "/api/settings": return self.send(C.masked_settings())  # M4 secrets masked
        if path == "/api/m4": return self.send(dict(C.m4_masked(), adapter=C.AD().name, adapters=sorted(C.ADAPTERS)))
        if path == "/api/templates":
            st = S["store"]
            return self.send({"ok": True, "names": st.names(), "active": C.load_settings().get("activeTemplate") or "default",
                              "templates": {n: st.get(n) for n in st.names()}, "builtin": T.builtin_default(),
                              "strategies": list(T.STRATEGIES), "adapter": C.AD().name})
        if path == "/api/state":
            now = time.time()
            with lock:
                return self.send({"now": now, "base": C.AD().base, "adapter": C.AD().name, "running": S["running"], "sent": S["sent"], "msg": S["msg"], "log": C.P["log"], "incPending": len(C.inc_pending()),
                    "orders": [dict({k: v for k, v in o.items() if k != "body"}, age=now - o["sent"], idle=now - o["changed"]) for o in S["orders"].values()],
                    "robots": [dict(r, idle=now - r["moved"]) for r in S["robots"].values()], "groups": S["groups"]})
        if path == "/api/get":  # read-only proxy for debugging
            st, js, txt = C.AD().raw_get(self.q().get("path", "/"))
            return self.send({"status": st, "body": js if js is not None else txt[:5000]})
        self.send({"err": "not found"}, 404)

    def do_POST(self):
        p = self.path; path = urllib.parse.urlparse(p).path
        if path == "/api/smap_upload":
            n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n)
            name = os.path.basename(self.q().get("name") or "upload.smap") or "upload.smap"
            if not name.lower().endswith(".smap"): name += ".smap"
            os.makedirs(C.P["maps"], exist_ok=True); dst = os.path.join(C.P["maps"], name)
            try: ok = bool(C.AD().decode_map(raw))
            except Exception: ok = False
            if not ok: return self.send({"ok": False, "err": C.msg("srv.badSmap")})
            with open(dst, "wb") as f: f.write(raw)
            C.save_settings({"smapPath": dst}); S["geom"] = None
            return self.send(C.build_geom())
        b = self.body()
        if path == "/api/smap_path":
            fp = (b.get("path") or "").strip().strip('"')
            if fp and not os.path.isfile(fp): return self.send({"ok": False, "err": C.msg("srv.noFile", path=fp)})
            C.save_settings({"smapPath": fp}); S["geom"] = None
            return self.send(C.build_geom())
        if path == "/api/adapter":  # {"adapter": "rds"|"m4"}
            name = b.get("adapter") or "rds"
            if name not in C.ADAPTERS: return self.send({"ok": False, "err": "unknown adapter: %s" % name})
            C.save_settings({"adapter": name}); ad = C.set_adapter(name)
            C.log("adapter", name=name, base=ad.base); return self.send({"ok": True, "adapter": ad.name, "base": ad.base})
        if path == "/api/m4":  # {"name", "profile": {...}, "activate": true, "delete": false}; secrets may be sent as ******
            act = C.m4_save(b.get("name"), b.get("profile") or {}, b.get("activate", True), bool(b.get("delete")))
            if C.AD().name == "m4": C.set_adapter("m4")
            C.log("m4_profile", name=b.get("name"), active=act, delete=bool(b.get("delete")))
            return self.send(dict(C.m4_masked(), ok=True))
        if path == "/api/m4_test":  # read-only: GET /api/ping + /api/fleet/scenes/list with the given (unsaved) profile
            from .adapters.m4 import M4Adapter, MASK
            prof = C.m4_profile(b.get("name")); prof.update({k: v for k, v in (b.get("profile") or {}).items() if v != MASK})
            if not prof.get("base"): return self.send({"ok": False, "err": C.msg("srv.m4NoBase")})
            ad = M4Adapter(prof["base"], C.log, prof)
            ok, info = ad.ping(); sc = ad.scenes() if ok else None
            return self.send({"ok": ok, "auth": ad.auth_mode(), "ping": info if ok else str(info)[:200], "scenes": sc})
        if path == "/api/config":
            C.set_base(b.get("base")); S["cfg"]["pollSec"] = b.get("pollSec", S["cfg"].get("pollSec", 2))
            part = dict(b.get("settings") or {})
            part.pop("m4", None); part.pop("adapter", None)  # only via /api/m4 and /api/adapter (never overwrite secrets with masks)
            if b.get("base"): part["base"] = b["base"]
            if b.get("pollSec"): part["pollSec"] = b["pollSec"]
            if b.get("lang") in i18n.LANGS: part["lang"] = b["lang"]
            C.save_settings(part); return self.send({"ok": True})
        # ---- templates
        if path == "/api/template_save":
            t = b.get("template")
            if not isinstance(t, dict): return self.send({"ok": False, "err": "template missing"})
            if b.get("noOverwrite") and t.get("name") in S["store"].names(): return self.send({"ok": False, "err": C.msg("srv.tplExists", name=t.get("name"))})
            try: S["store"].put(t)
            except ValueError as e: return self.send({"ok": False, "err": str(e)})
            if b.get("activate"): C.save_settings({"activeTemplate": t["name"]})
            C.log("template_save", name=t["name"]); return self.send({"ok": True, "template": t})
        if path == "/api/template_delete":
            try: S["store"].delete(b.get("name") or "")
            except (ValueError, OSError) as e: return self.send({"ok": False, "err": str(e)})
            st = C.load_settings()
            if st.get("activeTemplate") == b.get("name"): C.save_settings({"activeTemplate": S["store"].names()[0]})
            C.log("template_delete", name=b.get("name")); return self.send({"ok": True})
        if path == "/api/template_validate":
            t = b.get("template"); errs = T.validate(t) if isinstance(t, dict) else ["not an object"]
            return self.send({"ok": not errs, "errors": errs, "template": t})
        if path == "/api/preview":
            try: return self.send(C.preview(b))
            except ValueError as e: return self.send({"ok": False, "err": str(e)})
        # ---- orders
        if path == "/api/start":
            if S["running"]: return self.send({"ok": False, "err": C.msg("srv.running")})
            if b.get("settings"): C.save_settings(b["settings"])
            b.pop("settings", None)
            b, t, pools, warn, err = C.prepare_cfg(b)
            if err: return self.send({"ok": False, "err": err})
            if b.get("count") in (None, ""): b["count"] = T.make_picker(b.get("strategy"), [(r, pools[r]) for r in T.pool_roles(t)], b.get("noSelf", True)).default_count()
            b.setdefault("incPollSec", S["cfg"].get("incPollSec", 1)); b.setdefault("blockByBlock", S["cfg"].get("blockByBlock", False)); S["cfg"] = b; S["sent"] = 0; S["running"] = True; S["msg"] = "auto" + (" | " + warn if warn else "")
            S["dbatch"] = C.new_batch([], b.get("interval"), b.get("maxActive"), "auto", b.get("group") or ""); S["dbatch"]["n"] = int(b.get("count") or 0)
            C.log("start", cfg=b); threading.Thread(target=C.dispatcher, args=(t, pools), daemon=True).start(); return self.send({"ok": True, "warn": warn})
        if path == "/api/stop":
            S["running"] = False; C.log("stop"); return self.send({"ok": True})
        if path == "/api/cancel":
            with lock: ids = [k for k, o in S["orders"].items() if C.is_active(o)] if b.get("all") else [i for i in b.get("ids", []) if i in S["orders"] and S["orders"][i]["state"] != DRAFT]
            return self.send({"ok": True, "res": {oid: C.AD().cancel(oid) for oid in ids}})
        if path == "/api/clear":
            with lock:
                for k in [k for k, o in S["orders"].items() if o["state"] != DRAFT]: S["orders"].pop(k)
            return self.send({"ok": True})
        if path == "/api/generate":
            if b.get("settings"): C.save_settings(b["settings"])
            b.pop("settings", None)
            b, t, pools, warn, err = C.prepare_cfg(b)
            if err: return self.send({"ok": False, "err": err})
            res = C.generate_drafts(b, t, pools)
            if res.get("noPickPre"): warn = (warn + "\n" if warn else "") + C.msg("srv.noPickPreHint", list=", ".join(res["noPickPre"]))
            return self.send(dict(res, ok=True, warn=warn))
        if path == "/api/send":
            if S["running"]: return self.send({"ok": False, "err": C.msg("srv.running")})
            with lock: ids = [i for i in b.get("ids", []) if i in S["orders"] and S["orders"][i]["state"] == DRAFT]
            if not ids: return self.send({"ok": False, "err": C.msg("srv.noDraftSel")})
            C.set_base(b.get("base"))
            if "blockByBlock" in b: S["cfg"]["blockByBlock"] = bool(b.get("blockByBlock"))
            if b.get("incPollSec"): S["cfg"]["incPollSec"] = float(b["incPollSec"])
            inc = C.inc_enabled()
            S["running"] = True; S["sent"] = 0; S["msg"] = "0/%d" % len(ids); S["batch"] = set(ids)
            with lock: grp = ",".join(sorted({(S["orders"][i].get("body") or {}).get("group", "") for i in ids} - {""}))
            meta = C.new_batch(ids, float(b.get("interval") or 0), int(b.get("maxActive") or 0), "send", grp)
            C.log("send_batch", ids=ids, interval=b.get("interval"), maxActive=b.get("maxActive"), base=C.AD().base, batch=meta, blockByBlock=inc)
            threading.Thread(target=C.send_batch, args=(ids, float(b.get("interval") or 0), int(b.get("maxActive") or 0), meta, inc), daemon=True).start()
            return self.send({"ok": True, "n": len(ids)})
        if path == "/api/swap_drafts":
            if b.get("settings"): C.save_settings(b["settings"])
            b.pop("settings", None); ids = b.pop("ids", []) or []
            C.set_base(b.get("base"))
            if not ids: return self.send({"ok": False, "err": C.msg("srv.noDraftSel")})
            try: t = C.resolve_template(b)
            except ValueError as e: return self.send({"ok": False, "err": str(e)})
            return self.send(dict(C.swap_drafts(ids, b, t), ok=True))
        if path == "/api/delete_drafts":
            with lock:
                ids = [i for i in b.get("ids", []) if i in S["orders"] and S["orders"][i]["state"] == DRAFT]
                for i in ids: S["orders"].pop(i)
            C.save_drafts(); C.log("delete_drafts", ids=ids); return self.send({"ok": True, "n": len(ids)})
        self.send({"err": "not found"}, 404)

def main(argv=None):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Order dispatch tester")
    ap.add_argument("--port", type=int, default=5088); ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--rds", "--base", dest="base", default=None, help="dispatcher base URL, e.g. http://<rds-host>:8088")
    ap.add_argument("--data", default=os.environ.get("ORDER_TESTER_DATA") or here, help="data dir (settings.json, drafts.json, templates/, logs/)")
    ap.add_argument("--adapter", default=None, help="dispatcher adapter (default: settings 'adapter' or rds)")
    a = ap.parse_args(argv)
    C.init(a.data)
    if sys.stdout is None or sys.stderr is None:  # pythonw: no console
        sys.stdout = sys.stderr = open(os.path.join(C.P["logs"], "server_console.log"), "a", encoding="utf-8", buffering=1)
    try:
        if C.migrate_vs_settings(): print("settings: migrated variableShape to vsPerBlock", flush=True)
        for n in C.migrate_templates(): print("migration:", n, flush=True)
    except Exception as e: print("migration error:", e, flush=True)
    st0 = C.load_settings()
    adapter = a.adapter or st0.get("adapter") or "rds"
    C.set_base(st0.get("base")); C.set_base(a.base)
    if adapter != C.AD().name or adapter == "m4": C.set_adapter(adapter)
    if st0.get("pollSec"): S["cfg"]["pollSec"] = st0["pollSec"]
    f0 = st0.get("fields") if isinstance(st0.get("fields"), dict) else {}
    S["cfg"]["blockByBlock"] = bool(f0.get("bbb"))
    try: S["cfg"]["incPollSec"] = float(f0.get("bbb_poll") or 1)
    except (TypeError, ValueError): S["cfg"]["incPollSec"] = 1.0
    nd = C.load_drafts(); ns = C.load_sent()
    pend = C.inc_pending()
    if pend:  # open block-by-block orders from before the restart: resumed (already-appended blocks are detected via orderDetails)
        C.log("inc_resume", ids=pend); print("block-by-block orders resumed after restart: %d (%s)" % (len(pend), ", ".join(pend[:10])), flush=True)
        with C.lock:
            for i in pend: S["orders"][i]["inc"]["resumed"] = time.time()
    threading.Thread(target=C.poller, daemon=True).start()
    threading.Thread(target=C.inc_worker, daemon=True).start()
    print("drafts restored: %d, sent restored: %d" % (nd, ns), flush=True)
    print("Order dispatch tester: http://%s:%d  dispatcher(%s): %s  data: %s  log: %s" % (a.host, a.port, C.AD().name, C.AD().base, C.P["data"], C.P["log"]), flush=True)
    try: srv = ThreadingHTTPServer((a.host, a.port), H)
    except OSError as e:
        print("port %d unavailable (already running?): %s" % (a.port, e), flush=True); sys.exit(1)
    srv.serve_forever()
