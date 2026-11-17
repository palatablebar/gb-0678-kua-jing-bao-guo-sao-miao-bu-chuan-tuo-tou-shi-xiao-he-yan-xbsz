# 跨境包裹扫描补传与妥投时效核验

供跨境集运客服质控员核对原始记录、处理差异并封存证据。

## 启动

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

打开 http://localhost:18247 。首次进入自动运行仓内脏样例。工具条可重跑、切换样例或上传CSV。SQLite保存在命名卷records中，重建服务保留批次。

## 模块

- 1. 扫描采信：`/scans`，`/api/scans`。
- 2. 节点映射：`/nodes`，`/api/nodes`。
- 3. 时区归整：`/timezones`，`/api/timezones`。
- 4. 路径裁决：`/paths`，`/api/paths`。
- 5. 时效计算：`/timeliness`，`/api/timeliness`。
- 6. 赔付对账：`/compensation`，`/api/compensation`。
- 7. 批次归档：`/archives`，`/api/archives`。

## 核心规则

以事件发生时刻重建路径，补传不改变既有妥投时间；承诺时钟按目的地节假日停表。

## 演示

1. 打开首页，核对当次计算、差异和隔离原因。
2. 切换模块查看源行及裁决依据。
3. 重跑相同样例，批次号与行数保持一致。
4. 复核后导出一份证据CSV。版本已变化的复核提交返回409。

## 输入与输出

输入列见 `docs/DATA-DICTIONARY.md`。项目包含dirty.csv、clean.csv、legacy.csv，统一走实际导入路径。上传限制4MB，拒绝不带时区的时间。业务键按字符串保留，Decimal参与计算，空值不会当零。

`POST /api/runs` 接收sample或csv；`GET /api/runs`返回历史批次；`POST /api/runs/<id>/review`需要version与decision；`GET /api/runs/<id>/archive`返回唯一证据导出。

## 复核后补传更正

补传妥投常在复核后到达。系统裁决采用**重算原批并保留旧版**：原批复核后冻结不可变，补传与重建的原输入合并后全量重跑，生成带`correction_of`链的更正批次，页面展示更正依据与逐包裹新旧时效/赔付差异。更正批独立核对（待核对→已核对）通过前，旧批次保持唯一正式结算结果；核对通过后更正批成为唯一正式结果，原批证据仍可随时导出追回。

- 同一原批+同一补传（按sha256）重试只返回同一更正批，不重复冲减；
- 已申报赔付以原批为准钉住，补传携带的申报值不生效；
- 补传含隔离行、合并重算新增隔离、扫描号与原批重复均在写入前拒绝，重算失败不触碰原证据；
- 接口：`POST/GET /api/runs/<id>/corrections`、`POST /api/corrections/<id>/review`、`GET /api/runs/<id>/official`，详见`docs/API.md`。

## 范围

样例均为虚构。单机复核工具不连接生产系统；不提供登录、远端数据库或自动支付。内存计算按4MB输入上限控制，SQLite事务保证结果完整写入。

## 目录

app为服务与规则，sample_data为输入，tests为测试，docs为定义与深度登记。
