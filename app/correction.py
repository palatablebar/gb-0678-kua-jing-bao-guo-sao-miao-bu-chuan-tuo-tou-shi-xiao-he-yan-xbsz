import csv,io,hashlib,json
from decimal import Decimal
from app.config import COLUMNS
from app.errors import DomainError
from app.values import money
from app import store
from app.pipeline import calculate
from app.modules.m1_scans.rules import evaluate as stage1
from app.modules.m1_scans.rules import decode

def _reconstruct_raw(origin):
    "从已冻结原批的M1采纳行与隔离行重建原始输入（语义等价，原批证据不被改写）"
    m1=origin["stages"][0]
    evidence=sorted(m1["rows"]+m1.get("cumulative_quarantine",[]),key=lambda r:r.get("_line",0))
    stream=io.StringIO(newline="")
    writer=csv.writer(stream)
    writer.writerow(COLUMNS)
    for row in evidence:
        cells=row.get("_raw")
        if cells: writer.writerow(cells)
    return ("﻿"+stream.getvalue()).encode()

def _supplement_rows(raw):
    "补传单独过M1规则；表头不符或产生隔离即拒绝，避免新证据被静默吞掉"
    probe=stage1(raw)
    if probe["quarantine"]:
        codes=";".join(sorted({q["reason"] for q in probe["quarantine"]}))
        raise DomainError("SUPPLEMENT_REJECTED",f"补传含 {len(probe['quarantine'])} 行不可采信（{codes}），原批保持不变")
    if not probe["rows"]:
        raise DomainError("SUPPLEMENT_EMPTY","补传无有效扫描，原批保持不变")
    return probe["rows"]

def _guard_duplicates(origin,supplement):
    "同一补传重试不能重复冲减：已被原批采纳的扫描号不得再次进入更正"
    known={r["scan_id"] for r in origin["stages"][0]["rows"]}
    overlap=sorted(known & {r["scan_id"] for r in supplement})
    if overlap:
        raise DomainError("SUPPLEMENT_DUPLICATE",f"补传扫描号 {', '.join(overlap[:5])} 已在原批采信，拒绝重复冲减")

def _rebuild(raw,params,expected_quarantine):
    "全量重跑同一规则版本流水线；失败直接抛错，由调用方保证不写入任何批次"
    new=calculate(raw,params)
    actual=len(new["stages"][-1].get("cumulative_quarantine",[]))
    if actual!=expected_quarantine:
        codes=";".join(sorted({q.get("reason","?") for q in new["stages"][-1].get("cumulative_quarantine",[])}))
        raise DomainError("SUPPLEMENT_MERGE_CONFLICT",f"合并重算新增隔离（{codes}），更正中止，原批保持不变")
    return new

def _pin_reported(origin,new):
    "已申报赔付不得被悄悄改掉：以原批M6逐包裹reported钉住更正批，并重算对账合计与差异"
    old_reported={r["parcel"]:str(r.get("reported","0")) for r in origin["stages"][5]["rows"]}
    pinned=[]
    for row in new["stages"][5]["rows"]:
        if row["parcel"] in old_reported:
            row={**row,"reported":old_reported[row["parcel"]]}
        pinned.append(row)
    new["stages"][5]["rows"]=pinned
    m=new["stages"][5]["metrics"]
    m["reported_total"]=money(sum((Decimal(r.get("reported","0")) for r in pinned),Decimal(0)))
    # 状态与逐行差额随钉住后的申报值重算
    for row in pinned:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        row["difference"]=money(expected-reported)
        row["status"]="通过" if expected==reported else "差异"
    m["differences"]=sum(r["status"]=="差异" for r in pinned)
    # M7归档行与摘要随钉住后的M6结果重建
    new["stages"][6]["rows"]=[{**r} for r in pinned]
    sealed=new["stages"][6]["metrics"]
    sealed["differences"]=m["differences"]
    encoded=json.dumps(pinned,ensure_ascii=False,sort_keys=True,default=str).encode()
    sealed["sha256"]=hashlib.sha256(encoded).hexdigest()
    return new

def _diff(origin,new,supplement_ids):
    old_rows={r["parcel"]:r for r in origin["stages"][5]["rows"]}
    new_rows={r["parcel"]:r for r in new["stages"][5]["rows"]}
    items=[]
    for parcel in sorted(set(old_rows)|set(new_rows)):
        old=old_rows.get(parcel);cur=new_rows.get(parcel)
        old_expected=Decimal(str(old.get("expected","0"))) if old else Decimal(0)
        new_expected=Decimal(str(cur.get("expected","0"))) if cur else Decimal(0)
        old_reported=Decimal(str(old.get("reported","0"))) if old else Decimal(0)
        new_reported=Decimal(str(cur.get("reported","0"))) if cur else Decimal(0)
        delta=new_expected-old_expected
        items.append({
            "parcel":parcel,
            "old_sla":old.get("sla") if old else None,
            "new_sla":cur.get("sla") if cur else None,
            "old_expected":money(old_expected),"new_expected":money(new_expected),
            "expected_delta":money(delta),
            "old_reported":money(old_reported),"new_reported":money(new_reported),
            "reported_unchanged":old_reported==new_reported,
            "changed":bool(delta or (old and cur and old.get("sla")!=cur.get("sla")) or old is None or cur is None),
        })
    old_total=Decimal(origin["stages"][5]["metrics"]["expected_total"])
    new_total=Decimal(new["stages"][5]["metrics"]["expected_total"])
    net=new_total-old_total
    summed=sum((Decimal(i["expected_delta"]) for i in items),Decimal(0))
    if summed!=net:
        raise DomainError("DIFF_UNBALANCED","逐包裹赔付差异之和与批次总额差异对不平，更正中止")
    return {
        "items":items,
        "metrics":{
            "old_expected_total":money(old_total),"new_expected_total":money(new_total),
            "net_compensation_delta":money(net),
            "old_late_parcels":origin["stages"][4]["metrics"]["late_parcels"],
            "new_late_parcels":new["stages"][4]["metrics"]["late_parcels"],
            "changed_parcels":sum(i["changed"] for i in items),
            "sla_flips":sum(1 for i in items if i["old_sla"]!=i["new_sla"]),
            "balanced":True,
        },
        "supplement_scan_ids":sorted(supplement_ids),
    }

def _strip_header(raw):
    "去掉补传文件自身表头，拼接后只保留重建输入的一个分段表头"
    text,_=decode(raw)
    first=text.find("\n")
    if first<0: raise DomainError("SUPPLEMENT_EMPTY","补传无有效扫描，原批保持不变")
    return text[first+1:].lstrip("\r\n").encode()

def create_correction(origin_id,supplement_raw):
    origin=store.get(origin_id)
    if origin.get("correction_of"):
        raise DomainError("CHAIN_UNSUPPORTED","更正批次不能再次更正，请基于最初原批发起")
    supplement_sha=hashlib.sha256(supplement_raw).hexdigest()
    # 幂等：同一原批+同一补传的重试直接返回既有更正批，不重复冲减
    existing=next((c for c in store.corrections_for(origin_id) if c["supplement_sha256"]==supplement_sha),None)
    if existing:
        return store.get(existing["correction_id"]),existing,True
    if origin["decision"]!="已复核":
        raise DomainError("ORIGIN_NOT_REVIEWED","原批尚未复核，不允许发起更正")
    pending=[c for c in store.corrections_for(origin_id) if c["status"]=="待核对"]
    if pending:
        raise DomainError("CORRECTION_PENDING","存在待核对的更正批次，请先完成核对或退回后再发起")
    supplement=_supplement_rows(supplement_raw)
    _guard_duplicates(origin,supplement)
    merged=_reconstruct_raw(origin)+_strip_header(supplement_raw)
    expected_quarantine=len(origin["stages"][-1].get("cumulative_quarantine",[]))
    # 先算后写：重算失败在此抛出，原批与证据均不被触碰
    new=_rebuild(merged,origin.get("parameters",{}),expected_quarantine)
    new=_pin_reported(origin,new)
    if new["run_id"]==origin_id:
        raise DomainError("NO_EFFECT","补传未改变任何裁决，无需更正")
    diff=_diff(origin,new,{r["scan_id"] for r in supplement})
    if any(not i["reported_unchanged"] for i in diff["items"] if i["parcel"] in {r["parcel"] for r in origin["stages"][5]["rows"]}):
        raise DomainError("REPORTED_DRIFT","更正批申报赔付与原批不一致，更正中止")
    new.update({
        "correction_of":origin_id,
        "supplement_sha256":supplement_sha,
        "origin_archive_sha256":origin["stages"][6]["metrics"]["sha256"],
        "diff":diff,
    })
    saved=store.save(new["run_id"],new)
    record=store.save_correction(new["run_id"],origin_id,supplement_sha,saved["version"])
    return saved,record,False
