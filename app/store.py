import sqlite3,json
from pathlib import Path
from app.config import DATA_DIR
from app.errors import DomainError
def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS corrections (id TEXT PRIMARY KEY,origin_id TEXT NOT NULL,supplement_sha256 TEXT NOT NULL,status TEXT NOT NULL DEFAULT '待核对',created_version INTEGER NOT NULL,UNIQUE(origin_id,supplement_sha256))")
    return db
def save(run_id,payload):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))
    return get(run_id)
def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}
def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None
def history():
    with connect() as db: return [{"run_id":i,"version":v,"decision":d} for i,v,d in db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC")]
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)
def save_correction(correction_id,origin_id,supplement_sha256,created_version):
    "幂等登记更正链：同一原批+同一补传摘要只允许一条，重试返回既有登记"
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO corrections(id,origin_id,supplement_sha256,status,created_version) VALUES (?,?,?,'待核对',?)",(correction_id,origin_id,supplement_sha256,created_version))
        row=db.execute("SELECT id,origin_id,supplement_sha256,status,created_version FROM corrections WHERE origin_id=? AND supplement_sha256=?",(origin_id,supplement_sha256)).fetchone()
    return {"correction_id":row[0],"origin_id":row[1],"supplement_sha256":row[2],"status":row[3],"created_version":row[4]}
def get_correction(correction_id):
    with connect() as db: row=db.execute("SELECT id,origin_id,supplement_sha256,status,created_version FROM corrections WHERE id=?",(correction_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","更正批次不存在",404)
    return {"correction_id":row[0],"origin_id":row[1],"supplement_sha256":row[2],"status":row[3],"created_version":row[4]}
def corrections_for(origin_id):
    with connect() as db: rows=db.execute("SELECT id,origin_id,supplement_sha256,status,created_version FROM corrections WHERE origin_id=? ORDER BY rowid",(origin_id,)).fetchall()
    return [{"correction_id":r[0],"origin_id":r[1],"supplement_sha256":r[2],"status":r[3],"created_version":r[4]} for r in rows]
def confirm_correction(correction_id,version,decision):
    "更正确认走版本条件更新；未核对完成前原批次状态与正式结论不变"
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    record=get_correction(correction_id)
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,correction_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(correction_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        db.execute("UPDATE corrections SET status=? WHERE id=?",("已核对" if decision=="已复核" else "退回",correction_id))
    return get(correction_id),get_correction(correction_id)
def official(origin_id):
    "同一原批的唯一正式结算结果：已核对更正优先，否则原批"
    origin=get(origin_id)
    for record in corrections_for(origin_id):
        if record["status"]=="已核对":
            return get(record["correction_id"]),record
    return origin,None
