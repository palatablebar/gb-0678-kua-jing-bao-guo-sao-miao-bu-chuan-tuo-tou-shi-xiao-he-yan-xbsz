import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    diff=run.get("diff")
    if diff:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"correction_meta",json.dumps({
            "correction_of":run["correction_of"],
            "supplement_sha256":run["supplement_sha256"],
            "origin_archive_sha256":run["origin_archive_sha256"],
            "metrics":diff["metrics"],
            "supplement_scan_ids":diff["supplement_scan_ids"],
        }),"CORRECTION","更正依据与新旧差异"])
        for item in diff["items"]:
            if item["changed"]:
                writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"correction_diff",json.dumps(item),"DIFF",json.dumps(item,ensure_ascii=False)])
    return "﻿"+stream.getvalue()
