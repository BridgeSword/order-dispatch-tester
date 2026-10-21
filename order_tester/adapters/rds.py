# -*- coding: utf-8 -*-
"""SEER RDS adapter: neutral order -> RDS setOrder JSON, plus the RDS HTTP endpoints
(/scene, /downloadScene, /setOrder, /orderDetails/<id>, /robotsStatus, /terminate)."""
import json, time, urllib.request, urllib.error
from .base import DispatcherAdapter
from . import rds_scene

class RdsAdapter(DispatcherAdapter):
    name = "rds"
    # FAILED is deliberately NOT terminal: an RDS order can be resumed after FAILED, keep polling it.
    terminal_states = frozenset({"FINISHED", "STOPPED", "MANUAL_FINISHED", "CANCELED", "CANCELLED", "SKIPPED"})

    # ------------------------------------------------------------ payload
    def build_payload(self, order):
        oid = order["id"]; blocks = []
        for st in order["steps"]:
            b = {"blockId": oid + st["suffix"], "location": st["location"]}
            op = st.get("operation")
            args = st.get("args") if isinstance(st.get("args"), dict) else {}
            if op == "Script":
                rest = {k: v for k, v in args.items() if k not in ("script_name", "script_args")}
                b["operation"] = "Script"; b["operation_args"] = rest
                b["script_name"] = args.get("script_name", "")
                b["script_args"] = args.get("script_args", {})
            elif op and op != "none":
                b["operation"] = op; b["operation_args"] = args
                if "recognize" in args: b["recognize"] = args["recognize"]
            blocks.append((b, st))
        for b, st in blocks:
            if isinstance(st.get("variableShape"), dict): b["variableShape"] = st["variableShape"]
        o = {"id": oid, "complete": True, "priority": int(order.get("priority") or 1), "additionalProperties": {}, "blocks": [b for b, _ in blocks]}
        if order.get("vehicle"): o["vehicle"] = order["vehicle"]
        if (order.get("group") or "").strip(): o["group"] = order["group"].strip()  # RDS robot group
        if (order.get("label") or "").strip(): o["label"] = order["label"].strip()
        return o

    # ------------------------------------------------------------ http
    def request(self, method, path, body=None, timeout=8, quiet=False):
        url = self.base.rstrip("/") + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        t0 = time.time(); status = None; txt = ""
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r: status = r.status; txt = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e: status = e.code; txt = e.read().decode("utf-8", "replace")
        except Exception as e: txt = "ERR " + str(e)
        try: js = json.loads(txt)
        except Exception: js = None
        if not quiet or method != "GET":
            self.log("http", method=method, url=url, req=body, status=status, ms=int((time.time() - t0) * 1000), resp=js if js is not None else txt[:2000])
        return status, js, txt

    def submit(self, payload):
        st, js, txt = self.request("POST", "/setOrder", payload)
        ok = st == 200 and isinstance(js, dict) and js.get("code") == 0
        return ok, None if ok else txt[:200]

    def order_status(self, order_id, quiet=True, timeout=8):
        st, js, _ = self.request("GET", "/orderDetails/" + order_id, timeout=timeout, quiet=quiet)
        if not (isinstance(js, dict) and (js.get("id") or "state" in js)): return None
        bl = [b for b in (js.get("blocks") or []) if isinstance(b, dict)]
        return {"state": js.get("state"), "vehicle": js.get("vehicle") or "",
                "blockStates": [b.get("state") for b in bl],
                "blockStartTimes": [t for t in (ts(b.get("startTime")) for b in bl) if t],
                "createTime": ts(js.get("createTime")), "receiveTime": ts(js.get("receiveTime")),
                "terminateTime": ts(js.get("terminateTime")) or ts(js.get("terminalTime")), "finishTime": ts(js.get("finishTime"))}

    def cancel(self, order_id):
        st, js, txt = self.request("POST", "/terminate", {"id": order_id})
        return js if js is not None else txt[:200]

    def robots(self):
        st, js, _ = self.request("GET", "/robotsStatus", quiet=True)
        if not isinstance(js, dict): return None
        out = []
        for r in js.get("report", []) or []:
            rb = r.get("rbk_report") or {}
            co = r.get("current_order") if isinstance(r.get("current_order"), dict) else {}
            bi = r.get("basic_info") if isinstance(r.get("basic_info"), dict) else {}
            out.append({"name": r.get("uuid") or r.get("vehicle_id") or "?", "x": rb.get("x"), "y": rb.get("y"), "angle": rb.get("angle"),
                        "station": rb.get("current_station", ""), "order": co.get("id", "") or "", "orderState": co.get("state") or None,
                        "group": bi.get("current_group") or "", "dispatchable": r.get("dispatchable"), "connected": r.get("connection_status"),
                        "blocked": rb.get("blocked"), "battery": rb.get("battery_level")})
        return out

    # ------------------------------------------------------------ scene
    def scene(self, progress=None):
        """(status, json-or-None, text). Non-2xx, network errors and non-object JSON count as failure (json None).
        Streams the body so progress("download", bytes, content_length_or_None) can be reported."""
        prog = progress or (lambda *a, **k: None)
        url = self.base.rstrip("/") + "/scene"; t0 = time.time(); st = None; txt = ""
        prog("request")
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                st = r.status
                try: total = int(r.headers.get("Content-Length") or 0) or None
                except ValueError: total = None
                buf = bytearray(); prog("download", 0, total)
                while True:
                    c = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                    if not c: break
                    buf += c; prog("download", len(buf), total)
                txt = buf.decode("utf-8", "replace")
        except urllib.error.HTTPError as e: st = e.code; txt = e.read().decode("utf-8", "replace")
        except Exception as e: txt = "ERR " + str(e)
        try: js = json.loads(txt)
        except Exception: js = None
        if st is None or not 200 <= st < 300:
            self.log("http", method="GET", url=url, status=st, ms=int((time.time() - t0) * 1000), resp=txt[:2000]); return st, None, txt
        if not isinstance(js, dict): return st, None, "invalid JSON: " + txt[:200]
        return st, js, txt
    def parse_stations(self, scene): return rds_scene.parse_scene(scene)
    def parse_groups(self, scene): return rds_scene.parse_groups(scene)
    def extract_geom(self, scene): return rds_scene.extract_geom(scene)
    def decode_map(self, raw): return rds_scene.decode_smap(raw)
    def download_maps(self, timeout=120):
        try:
            with urllib.request.urlopen(self.base.rstrip("/") + "/downloadScene", timeout=timeout) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, b""
        except Exception as e: return None, str(e).encode()
    def raw_get(self, path): return self.request("GET", path, quiet=True)

def ts(v):
    """RDS timestamp (s or ms) -> epoch seconds or None"""
    try: v = float(v)
    except Exception: return None
    if v > 1e12: v /= 1000.0
    return v if v > 1e9 else None
