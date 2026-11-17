import csv,io
import pytest
from decimal import Decimal
from app import store
from app.pipeline import execute
from app.correction import create_correction
from app.errors import DomainError
from app.config import COLUMNS

HEADER=",".join(COLUMNS)
ACCEPT_A=["1000","P100","收件","2026-11-02T00:00:00Z","2026-11-02T01:00:00Z","JP","24","200","0","集运"]
DEPART_A=["1001","P100","起运","2026-11-02T12:00:00Z","2026-11-02T13:00:00Z","JP","24","200","0","集运"]
ACCEPT_B=["2000","P200","收件","2026-11-02T00:00:00Z","2026-11-02T01:00:00Z","JP","24","200","0","集运"]
# 补传妥投：事件时刻在24承诺时内，上传时刻在复核之后（迟到补传）
LATE_DELIVERY=["1002","P100","妥投","2026-11-02T23:00:00Z","2026-11-16T08:00:00Z","JP","24","200","0","补传妥投"]
BAD_SCAN=["3000","P300","收件","2026-11-02T00:00:00Z","JP","24","200","0","列数不符"]

def _csv(rows):
    stream=io.StringIO(newline="");w=csv.writer(stream);w.writerow(COLUMNS);w.writerows(rows)
    return ("﻿"+stream.getvalue()).encode()

@pytest.fixture
def reviewed_origin():
    run=execute(_csv([ACCEPT_A,DEPART_A,ACCEPT_B]))
    store.review(run["run_id"],1,"已复核")
    return store.get(run["run_id"])

@pytest.fixture
def supplement(): return _csv([LATE_DELIVERY])

def _m5(run,parcel):
    return next(r for r in run["stages"][4]["rows"] if r["parcel"]==parcel)

def _diff_item(run,parcel):
    return next(i for i in run["diff"]["items"] if i["parcel"]==parcel)

def test_origin_must_be_reviewed(supplement):
    run=execute(_csv([ACCEPT_A,DEPART_A,ACCEPT_B]))
    with pytest.raises(DomainError) as e: create_correction(run["run_id"],supplement)
    assert e.value.code=="ORIGIN_NOT_REVIEWED"
    assert store.corrections_for(run["run_id"])==[]

def test_late_scan_flips_sla_and_compensation(reviewed_origin,supplement):
    old_p100=_m5(reviewed_origin,"P100")
    assert old_p100["sla"]=="超时" and Decimal(old_p100["expected"])>0
    new,record,reused=create_correction(reviewed_origin["run_id"],supplement)
    assert reused is False and record["status"]=="待核对"
    assert new["correction_of"]==reviewed_origin["run_id"]
    assert new["supplement_sha256"]==record["supplement_sha256"]
    assert _m5(new,"P100")["sla"]=="达标"
    assert Decimal(_m5(new,"P100")["expected"])==Decimal("0.00")
    # 未涉及补传的包裹结论保持
    assert _m5(new,"P200")["sla"]=="超时"

def test_original_batch_is_frozen_and_recoverable(reviewed_origin,supplement):
    before=store.get(reviewed_origin["run_id"])
    create_correction(reviewed_origin["run_id"],supplement)
    after=store.get(reviewed_origin["run_id"])
    assert after["version"]==before["version"] and after["decision"]=="已复核"
    assert after["stages"]==before["stages"]
    assert "diff" not in after and "correction_of" not in after

def test_diff_totals_balance_per_parcel(reviewed_origin,supplement):
    new,_,_=create_correction(reviewed_origin["run_id"],supplement)
    items=new["diff"]["items"]
    summed=sum((Decimal(i["expected_delta"]) for i in items),Decimal(0))
    m=new["diff"]["metrics"]
    assert summed==Decimal(m["net_compensation_delta"])
    assert Decimal(m["net_compensation_delta"])==Decimal(m["new_expected_total"])-Decimal(m["old_expected_total"])
    p100=_diff_item(new,"P100")
    assert p100["old_sla"]=="超时" and p100["new_sla"]=="达标"
    assert Decimal(p100["expected_delta"])==Decimal(p100["new_expected"])-Decimal(p100["old_expected"])
    assert Decimal(p100["expected_delta"])==-Decimal(p100["old_expected"])  # 旧赔付全额冲减
    assert p100["reported_unchanged"] is True  # 已申报赔付不得被改写
    assert m["sla_flips"]==1 and m["balanced"] is True

def test_same_supplement_retry_is_idempotent(reviewed_origin,supplement):
    first,record1,reuse1=create_correction(reviewed_origin["run_id"],supplement)
    second,record2,reuse2=create_correction(reviewed_origin["run_id"],supplement)
    assert reuse1 is False and reuse2 is True
    assert first["run_id"]==second["run_id"]==record1["correction_id"]==record2["correction_id"]
    assert len(store.corrections_for(reviewed_origin["run_id"]))==1

def test_official_waits_for_confirmation(reviewed_origin,supplement):
    new,record,_=create_correction(reviewed_origin["run_id"],supplement)
    official_run,_=store.official(reviewed_origin["run_id"])
    assert official_run["run_id"]==reviewed_origin["run_id"]  # 核对完成前旧批次仍是唯一正式结果
    confirmed,record=store.confirm_correction(new["run_id"],new["version"],"已复核")
    assert confirmed["decision"]=="已复核" and record["status"]=="已核对"
    official_run,applied=store.official(reviewed_origin["run_id"])
    assert official_run["run_id"]==new["run_id"] and applied["correction_id"]==new["run_id"]

def test_stale_correction_review_409_flow(reviewed_origin,supplement):
    new,_,_=create_correction(reviewed_origin["run_id"],supplement)
    store.confirm_correction(new["run_id"],1,"已复核")
    with pytest.raises(DomainError) as e: store.confirm_correction(new["run_id"],1,"退回复核")
    assert e.value.code=="STALE_VERSION"

def test_reject_correction_keeps_origin_official(reviewed_origin,supplement):
    new,_,_=create_correction(reviewed_origin["run_id"],supplement)
    _,record=store.confirm_correction(new["run_id"],1,"退回复核")
    assert record["status"]=="退回"
    official_run,applied=store.official(reviewed_origin["run_id"])
    assert official_run["run_id"]==reviewed_origin["run_id"] and applied is None

def test_quarantined_supplement_fails_without_touching_origin(reviewed_origin):
    before=store.get(reviewed_origin["run_id"])
    with pytest.raises(DomainError) as e: create_correction(reviewed_origin["run_id"],_csv([LATE_DELIVERY,BAD_SCAN]))
    assert e.value.code=="SUPPLEMENT_REJECTED"
    assert store.corrections_for(reviewed_origin["run_id"])==[]
    assert store.get(reviewed_origin["run_id"])["stages"]==before["stages"]

def test_empty_supplement_rejected(reviewed_origin):
    with pytest.raises(DomainError): create_correction(reviewed_origin["run_id"],_csv([]))
    assert store.corrections_for(reviewed_origin["run_id"])==[]

def test_supplement_failing_later_stage_aborts_cleanly(reviewed_origin):
    "M1可采信但M3隔离的补传（缺时区）在合并重算时被拦截，原批不动"
    bad_m3=["3001","P300","收件","2026-11-02T00:00:00","2026-11-02T01:00:00Z","JP","24","200","0","无偏移"]
    with pytest.raises(DomainError) as e: create_correction(reviewed_origin["run_id"],_csv([bad_m3]))
    assert e.value.code=="SUPPLEMENT_MERGE_CONFLICT"
    assert store.corrections_for(reviewed_origin["run_id"])==[]

def test_duplicate_existing_scan_has_no_effect(reviewed_origin):
    with pytest.raises(DomainError) as e: create_correction(reviewed_origin["run_id"],_csv([ACCEPT_A]))
    assert e.value.code=="SUPPLEMENT_DUPLICATE"
    assert store.corrections_for(reviewed_origin["run_id"])==[]

def test_correction_chain_not_allowed(reviewed_origin,supplement):
    new,_,_=create_correction(reviewed_origin["run_id"],supplement)
    with pytest.raises(DomainError) as e: create_correction(new["run_id"],supplement)
    assert e.value.code=="CHAIN_UNSUPPORTED"

def test_second_correction_blocked_while_pending(reviewed_origin):
    delivery=["1004","P100","妥投","2026-11-02T23:00:00Z","2026-11-16T08:00:00Z","JP","24","200","0","补传妥投"]
    create_correction(reviewed_origin["run_id"],_csv([delivery]))
    other=["1005","P200","妥投","2026-11-02T23:00:00Z","2026-11-16T08:00:00Z","JP","24","200","0","另一条补传"]
    with pytest.raises(DomainError) as e: create_correction(reviewed_origin["run_id"],_csv([other]))
    assert e.value.code=="CORRECTION_PENDING"
    # 退回后允许重新发起
    cid=store.corrections_for(reviewed_origin["run_id"])[0]["correction_id"]
    store.confirm_correction(cid,1,"退回复核")
    again,record,_=create_correction(reviewed_origin["run_id"],_csv([other]))
    assert record["status"]=="待核对" and again["correction_of"]==reviewed_origin["run_id"]

def test_declared_compensation_is_pinned_even_if_new_scan_carries_value():
    "补传妥投自带reported也不得改写已申报赔付；差额随钉住值重算且仍对平"
    accept_a=[*ACCEPT_A];accept_a[8]="7.00"
    accept_b=[*ACCEPT_B];accept_b[8]="3.00"
    origin=execute(_csv([accept_a,DEPART_A,accept_b]))
    store.review(origin["run_id"],1,"已复核")
    delivery=["1003","P100","妥投","2026-11-02T23:00:00Z","2026-11-16T08:00:00Z","JP","24","200","99.00","补传携带不同申报"]
    new,_,_=create_correction(origin["run_id"],_csv([delivery]))
    p100=next(r for r in new["stages"][5]["rows"] if r["parcel"]=="P100")
    assert p100["reported"]=="7.00"  # 原批申报值，不是99.00
    assert Decimal(p100["difference"])==Decimal(p100["expected"])-Decimal("7.00")
    item=next(i for i in new["diff"]["items"] if i["parcel"]=="P100")
    assert item["reported_unchanged"] is True
    assert Decimal(new["stages"][5]["metrics"]["reported_total"])==Decimal("10.00")
    # M6对账恒等式：合计差=逐行差之和
    m=new["stages"][5]["metrics"]
    assert sum((Decimal(r["difference"]) for r in new["stages"][5]["rows"]),Decimal(0))==Decimal(m["expected_total"])-Decimal(m["reported_total"])

def test_evidence_export_contains_basis_and_diff(client,reviewed_origin,supplement):
    new,record,_=create_correction(reviewed_origin["run_id"],supplement)
    r=client.get("/api/runs/"+new["run_id"]+"/archive")
    text=r.data.decode("utf-8-sig")
    assert "correction_meta" in text and "correction_diff" in text
    assert reviewed_origin["run_id"] in text and record["supplement_sha256"] in text
    # 原批证据导出不含更正段，保持冻结形态
    origin_export=client.get("/api/runs/"+reviewed_origin["run_id"]+"/archive").data.decode("utf-8-sig")
    assert "correction_meta" not in origin_export

def test_api_full_correction_flow(client):
    r=client.post("/api/runs",json={"csv":_csv([ACCEPT_A,DEPART_A,ACCEPT_B]).decode()})
    origin_id=r.get_json()["run_id"]
    assert client.post(f"/api/runs/{origin_id}/review",json={"version":1,"decision":"已复核"}).status_code==200
    cr=client.post(f"/api/runs/{origin_id}/corrections",json={"csv":_csv([LATE_DELIVERY]).decode()})
    assert cr.status_code==200
    body=cr.get_json();corr_id=body["run"]["run_id"]
    assert body["idempotent_reuse"] is False
    assert client.get(f"/api/runs/{origin_id}/official").get_json()["official_id"]==origin_id
    again=client.post(f"/api/runs/{origin_id}/corrections",json={"csv":_csv([LATE_DELIVERY]).decode()})
    assert again.get_json()["idempotent_reuse"] is True
    rr=client.post(f"/api/corrections/{corr_id}/review",json={"version":1,"decision":"已复核"})
    assert rr.status_code==200 and rr.get_json()["correction"]["status"]=="已核对"
    assert client.get(f"/api/runs/{origin_id}/official").get_json()["official_id"]==corr_id
    listed=client.get(f"/api/runs/{origin_id}/corrections").get_json()["corrections"]
    assert [c["correction_id"] for c in listed]==[corr_id]

def test_api_bad_supplement_body_422_or_domain(client,reviewed_origin):
    r=client.post(f"/api/runs/{reviewed_origin['run_id']}/corrections",json={"nope":1})
    assert r.status_code==422
