# -*- coding: utf-8 -*-
"""Verbatim copy of build_order / Picker / make_draft from the legacy rds_tester.py (v1, last deployed
version) - used ONLY as the reference for the regression tests. Do not edit."""
import random, time, uuid
S = {"prepoints": {}}
DRAFT = "待下发"

def pre_point(end, cfg):
    ov = cfg.get("preOverrides") or {}
    if ov.get(end): return ov[end]
    return S["prepoints"].get(end, "")

# ---------- dispatcher ----------
def build_order(pair, cfg, oid=None):
    """[op@start, (Script@pre), op@end, (ForkHeight@pre)]; 前置点缺失时抛 ValueError"""
    oid = oid or "dl-" + uuid.uuid4().hex[:12]
    def blk(bid, loc, op, args):
        b = {"blockId": bid, "location": loc}
        if op and op != "none":
            b["operation"] = op
            b["operation_args"] = args if isinstance(args, dict) else {}
            if "recognize" in b["operation_args"]: b["recognize"] = b["operation_args"]["recognize"]
        return b
    sblk = blk(oid + "-s", pair[0], cfg.get("startOp"), cfg.get("startArgs"))
    eid = oid + "-e"
    blocks = [sblk]
    if cfg.get("pickPreOn"):  # 取货前先到取货前置点 Wait
        ppre = pre_point(pair[0], cfg)
        if not ppre: raise ValueError("起点 %s 无取货前置点(场景未推导出且无手动映射)" % pair[0])
        blocks.insert(0, {"blockId": oid + "-s_PRE", "location": ppre, "operation": "Wait", "operation_args": {}})
    pre = ""
    if cfg.get("scriptOn") or cfg.get("liftOn"):
        pre = pre_point(pair[1], cfg)
        if not pre: raise ValueError("终点 %s 无前置点(场景未推导出且无手动映射)" % pair[1])
    if cfg.get("scriptOn"):
        blocks.append({"blockId": eid + "_SCRIPT", "location": pre, "operation": "Script", "operation_args": {},
            "script_name": cfg.get("scriptName") or "userpy/rec_retry_versatile.py",
            "script_args": {"locName": pair[1], "operation": cfg.get("scriptOp") or "locDetectMid70D", "recFile": cfg.get("scriptRecFile") or ""}})
    blocks.append(blk(eid, pair[1], cfg.get("endOp"), cfg.get("endArgs")))
    if cfg.get("liftOn"):
        blocks.append(blk(eid + "_LIFT", pre, cfg.get("liftOp") or "ForkHeight", cfg.get("liftArgs") if isinstance(cfg.get("liftArgs"), dict) else {"end_height": 0.2}))
    roles = {oid + "-s_PRE": "pre", oid + "-s": "s", eid + "_SCRIPT": "script", eid: "e", eid + "_LIFT": "lift"}
    pb = cfg.get("vsPerBlock")
    if isinstance(pb, dict):  # 新版: 每段各自的 head/tail (只含启用的段)
        for b in blocks:
            v = pb.get(roles.get(b["blockId"]))
            if isinstance(v, dict) and v.get("head") is not None and v.get("tail") is not None:
                b["variableShape"] = {"head": float(v["head"]), "tail": float(v["tail"])}
    else:  # 旧版兼容: 全局一个值 + 勾选段
        vs = cfg.get("variableShape")
        vsb = cfg.get("vsBlocks") if isinstance(cfg.get("vsBlocks"), list) else ["e", "lift"]
        if vs:
            for b in blocks:
                if roles.get(b["blockId"]) in vsb: b["variableShape"] = vs
    o = {"id": oid, "complete": True, "priority": int(cfg.get("priority") or 1), "additionalProperties": {}, "blocks": blocks}
    if cfg.get("vehicle"): o["vehicle"] = cfg["vehicle"]
    if (cfg.get("group") or "").strip(): o["group"] = cfg["group"].strip()  # RDS setOrder 机器人组 (orderDetails 里同名字段 "group")
    if (cfg.get("label") or "").strip(): o["label"] = cfg["label"].strip()
    return o

class Picker:
    """每单从起点池/终点池各随机取一个; noReuse: 批内无放回抽样, 池用完后重新洗牌; noSelf: 起终点不同"""
    def __init__(self, starts, ends, no_self=True, no_reuse=True):
        self.s, self.e, self.no_self, self.no_reuse = list(starts), list(ends), no_self, no_reuse
        self.rs, self.re = [], []
    def _take(self, rem, full, excl=None):
        if not self.no_reuse:
            c = [x for x in full if x != excl] or full; return random.choice(c)
        if not [x for x in rem if x != excl]:  # 剩余不够: 补一轮
            rem.extend(random.sample(full, len(full)))
        c = [i for i, x in enumerate(rem) if x != excl]
        if not c: return random.choice(full)
        return rem.pop(random.choice(c))
    def next(self):
        a = self._take(self.rs, self.s)
        b = self._take(self.re, self.e, a if self.no_self else None)
        return [a, b]

def make_draft(pair, cfg, oid=None):
    """按当前设置构建一个待下发记录 (ValueError: 前置点缺失)"""
    body = build_order(pair, cfg, oid)
    pre = next((bk["location"] for bk in body["blocks"] if bk["blockId"].endswith(("_SCRIPT", "_LIFT"))), "") or pre_point(pair[1], cfg)
    RN = {"_PRE": "前置Wait", "-s": "取货", "_SCRIPT": "Script", "-e": "放货", "_LIFT": "升叉"}
    g = lambda x: "%g" % x if isinstance(x, (int, float)) else str(x)
    vsTag = ",".join(f'{n}{g(bk["variableShape"].get("head"))}/{g(bk["variableShape"].get("tail"))}'
                     for bk in body["blocks"] if isinstance(bk.get("variableShape"), dict) for suf, n in RN.items() if bk["blockId"].endswith(suf))
    now = time.time()
    return {"id": body["id"], "pair": list(pair), "pre": pre, "dropPre": pre, "pickPre": pre_point(pair[0], cfg),
        "vsTag": vsTag, "vehicle": body.get("vehicle", ""), "group": body.get("group", ""), "state": DRAFT,
        "sent": now, "changed": now, "created": now, "sig": "", "error": None, "body": body}

