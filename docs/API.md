# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 复核后补传更正（原批冻结，重算另存新版）

原批一经复核即冻结：payload、version、decision与证据导出均不再变化。补传妥投不在原批上打补丁，而是重建原输入并全量重跑同一规则版本，生成带`correction_of`链的更正批次；更正批次独立复核通过前，原批仍是唯一正式结算结果。

| 方法与路径 | 作用 | 关键约束 |
|---|---|---|
| `POST /api/runs/<id>/corrections` | 提交补传扫描CSV（`{"csv":...}`），合并重算生成更正批 | 原批须`已复核`；补传须全部可采信且扫描号不与原批重复；同一原批+同一补传摘要重试幂等，返回`idempotent_reuse:true`，不重复冲减 |
| `GET /api/runs/<id>/corrections` | 列出原批的更正链 | 含补传摘要、状态（待核对/已核对/退回） |
| `POST /api/corrections/<id>/review` | 更正批核对（version+decision） | 版本条件更新，陈旧版本409；`已复核`后状态置`已核对`，该更正批成为唯一正式结果 |
| `GET /api/runs/<id>/official` | 返回原批当前唯一正式结算结果 | 无已核对更正时返回原批，否则返回最新已核对更正批 |

更正批payload含`diff`：逐包裹新旧时效结论、新旧赔付、赔付差异、申报是否保持；`metrics.net_compensation_delta`等于逐包裹差异之和。已申报赔付（reported）以原批为准钉住，补传自带的申报值不生效。更正批证据CSV在原有accepted/quarantine行之外追加`correction_meta`（更正依据、补传摘要、原批证据sha256、差异汇总）与`correction_diff`（逐包裹差异）行；原批证据导出形态不变，可随时追回。

失败语义：补传含隔离行（SUPPLEMENT_REJECTED）、合并重算新增隔离（SUPPLEMENT_MERGE_CONFLICT）、扫描号重复（SUPPLEMENT_DUPLICATE）、原批未复核（ORIGIN_NOT_REVIEWED）、更正批再次更正（CHAIN_UNSUPPORTED）均在写入前拒绝，原批与证据不被触碰。
