# 深度登记 跨境包裹扫描补传与妥投时效核验

规模：中型。使用者：跨境集运客服质控员。核心规则：以事件发生时刻重建路径，补传不改变既有妥投时间；承诺时钟按目的地节假日停表。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 扫描采信 | 查看并运行扫描采信 | `/api/scans` | `app/modules/m1_scans/rules.py` | `tests/test_m1.py` |
| M2 节点映射 | 查看并运行节点映射 | `/api/nodes` | `app/modules/m2_nodes/rules.py` | `tests/test_m2.py` |
| M3 时区归整 | 查看并运行时区归整 | `/api/timezones` | `app/modules/m3_timezones/rules.py` | `tests/test_m3.py` |
| M4 路径裁决 | 查看并运行路径裁决 | `/api/paths` | `app/modules/m4_paths/rules.py` | `tests/test_m4.py` |
| M5 时效计算 | 查看并运行时效计算 | `/api/timeliness` | `app/modules/m5_timeliness/rules.py` | `tests/test_m5.py` |
| M6 赔付对账 | 查看并运行赔付对账 | `/api/compensation` | `app/modules/m6_compensation/rules.py` | `tests/test_m6.py` |
| M7 批次归档 | 查看并运行批次归档 | `/api/archives` | `app/modules/m7_archives/rules.py` | `tests/test_m7.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 默认解码失败 | 回退GB18030 | `app/modules/m1_scans/rules.py` | `tests/test_m1.py::test_legacy_encoding_real_sample` |
| TRAP-02 | BOM | 首列名多字符 | utf-8-sig | `app/modules/m1_scans/rules.py` | `tests/test_m1.py::test_bom_real_sample` |
| TRAP-03 | 带引号换行 | 拆成两条 | csv逻辑行 | `app/modules/m1_scans/rules.py` | `tests/test_m1.py::test_quoted_newline_is_one_record` |
| TRAP-05 | 列数不匹配 | 静默错列 | 隔离原行 | `app/modules/m1_scans/rules.py` | `tests/test_m1.py::test_bad_columns_real_sample` |
| TRAP-08 | 前导零ID | 编码变形 | 全程字符串 | `app/modules/m1_scans/rules.py` | `tests/test_m1.py::test_identifier_preserved_real_sample` |
| TRAP-14 | 重复键冲突 | 后写覆盖 | 保留首条并隔离冲突行 | `app/modules/m1_scans/rules.py` | `tests/test_m1.py::test_duplicate_conflict_real_sample` |
| TRAP-18 | 空态三态 | 一律成功 | 分别错误码 | `app/modules/m1_scans/rules.py` | `tests/test_m1.py::test_three_empty_states` |
| TRAP-26 | 旧版本提交 | 覆盖新结果 | 版本条件更新 | `app/store.py` | `tests/test_e2e.py::test_stale_review_409` |
| TRAP-06 | 全角时限 | 数字转换失败 | Decimal归一 | `app/values.py` | `tests/test_m3.py::test_numeric_normalization` |
| TRAP-07 | 时限哨兵 | 按零赔付 | 隔离缺失 | `app/values.py` | `tests/test_m3.py::test_real_sentinel_not_zero` |
| TRAP-11 | 目的地偏移 | 同刻多桶 | UTC比较 | `app/values.py` | `tests/test_m3.py::test_equivalent_timezone` |
| TRAP-12 | DST自然日 | 固定24小时 | 按当地午夜切片 | `app/modules/m5_timeliness/rules.py` | `tests/test_m5.py::test_dst_actual_elapsed_hours` |
| TRAP-13 | 迟到妥投补传 | 按上传时间赔付 | 发生时间重建 | `app/modules/m4_paths/rules.py` | `tests/test_m4.py::test_late_upload_event_time_decides` |
| TRAP-23 | 假日端点 | 误算全天 | 当地日半开切段 | `app/modules/m5_timeliness/rules.py` | `tests/test_m5.py::test_holiday_full_day_stops` |
| TRAP-27 | 复核后补传翻案 | 直接改原批结论与证据 | 原批冻结，重算另存更正批，独立核对通过才替换正式结果 | `app/correction.py` | `tests/test_correction.py::test_late_scan_flips_sla_and_compensation` |
| TRAP-28 | 同一补传重试 | 重复生成批次、重复冲减赔付 | 原批id+补传sha256唯一约束，幂等返回既有更正批 | `app/store.py` | `tests/test_correction.py::test_same_supplement_retry_is_idempotent` |
| TRAP-29 | 补传带新申报值 | 新妥投的reported静默覆盖已申报赔付 | 原批逐包裹reported钉住更正批并重算差额，漂移即中止 | `app/correction.py` | `tests/test_correction.py::test_declared_compensation_is_pinned_even_if_new_scan_carries_value` |
| TRAP-30 | 重算失败误删证据 | 先删后算导致原证据丢失 | 先算后写，隔离数变化/补传不可采信均在写入前拒绝 | `app/correction.py` | `tests/test_correction.py::test_quarantined_supplement_fails_without_touching_origin` |
| TRAP-31 | 补传表头拼接 | 第二张表头被当数据行隔离UNKNOWN_NODE | 拼接前剥离补传自身表头，仅保留重建输入的分段表头 | `app/correction.py` | `tests/test_correction.py::test_late_scan_flips_sla_and_compensation` |
| TRAP-32 | 新旧两套数字并存 | 原批与调整单各自结算 | 更正链+official裁决：已核对更正为唯一正式结果，原批仅留痕 | `app/store.py` | `tests/test_correction.py::test_official_waits_for_confirmation` |

## 对账规则

输入原始逻辑行=最终采纳来源行+隔离来源行+重复行+空白行+分段表头。派生记录用_sources保存完整来源，因此分组不丢行。业务预期合计与上游申报合计之差等于逐行差异之和。结果按输入摘要、规则版本及参数产生唯一批次，事务写入；同源重跑只复用已有批次。

## 已知不覆盖

4MB以上文件需预先按业务键分批；不模拟生产支付与外部回调。人工复核只变更批次状态，不改写原始记录。
