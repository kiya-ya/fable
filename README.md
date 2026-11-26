# 培训师系统 v1.0.0

> 面向游戏社交平台带教场景的运营管理系统：培训师/姐妹团绑定管理、名额与奖励判定、UID 数据速查、周奖励导出、用户自助绑定。
> **外部系统的认证/接口/表结构/坑见 `爬虫系统上下文.md`**。

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
docker compose up -d --build
```

- 管理员后台：`http://127.0.0.1:5000/`（admin / 见 `data/admin_config.json`）
- 培训师用户端：`http://127.0.0.1:5000/portal`（UID + UID 后 5 位初始密码）

## 运行架构

```
浏览器（管理员/培训师）
   │ ngrok 隧道（公网）
   ▼
Docker 容器（Flask :5000）
   ├─ 管理员端（绑定/档案/统计/导出）
   ├─ 用户端（自助绑定/查看/解散/改密码）
   ├─ 后台线程：Cookie 保活（30分钟/轮）
   ├─ 后台线程：每周一 09:00 自动刷新学员等级
   └─ SQLite（data/stats.db，WAL）
```

## 功能总览

### 管理员端
- **绑定关系**（首页）：新建绑定（培训师 / 姐妹团三胎），UID 查询自动带出昵称/大厅；档案弹窗管理（搜索/批量导入/补全信息/编辑/删除/历史导入）；绑定列表（生效/历史/操作日志），含结束日期、剩余奖励、保护期、留存标记
- **结果统计**：单人 UID 速查（本周 vs 上周），自动带出名侧面板（培训师）或奖励面板（妹妹）；周奖励批量导出 XLSX；「奖励已发放」一键标记
- **生态分**：同步队长生态管理的生态等级、生态分和活跃/获客/维护等分项；支持按身份/等级筛选、20 人分页、异步批量刷新、最近 4 周趋势及加减分详情；可导出妹妹四周进步 XLSX
- **数据看板**：近 8 周绑定/解散趋势、解散原因分布（全部历史/选中周）、4 周留存率/解散率、当前生效/待发放统计、生态分概览/等级分布/高分与下降提醒
- **资质审核**：处理考试申请；支持按 UID 回填昵称/大厅、核验点点姐妹团和培训师平台资质，并由管理员手动累加开通
- **海报管理**：自定义首页海报上传、替换、标题摘要、排序、启停和大图查看；上传文件持久化并纳入备份
- **操作日志**：谁在何时绑定/解绑/恢复了谁

### 培训师用户端
- **登录**：UID + 密码（初始密码 = UID 后 5 位，可自改；管理员可设置/重置）
- **我的名额**：基础/额外/总名额、扩充截止日期、学员列表（可折叠），学员卡片含等级/贡献/剩余奖励/数据展开（含解散）
- **绑定新妹妹**：输入妹妹 UID，自助绑定（保护期 + 姐姐冲突校验）
- **已发放奖励**：按妹妹分组展示已发放记录（档位/金额/时间）
- **自助解散**：解散自己的绑定，名额贡献随绑定结束自动减除

## 绑定与校验规则

- **培训师绑定**：名额上限 5；同一妹妹同时最多一条生效培训师绑定
- **姐妹团三胎**：一个姐姐同时只能绑一个妹妹（一对一）
- 同一妹妹可同时有一条培训师绑定 + 一条姐妹团绑定（两套独立计算）
- **绑定前校验**：
  1. 保护期（UID 查询）：妹妹须在保护期内、未查到/查询失败拒绝
  2. 姐姐冲突（bigdata 快照，绑定时现场刷新）：妹妹若已绑定其他姐姐（不同 UID）则拒绝；同 UID 或无记录放行
- 解绑不删记录，历史保留，可恢复；用户端可自行解散

## 名额与奖励口径

- **名额**：基础 2 + 学员当月排档周最高等级贡献（初银+1/银牌+1/金牌+1，需当周排档天数>0），上限 5；月初无记录用上月兜底，跨月重算
- **奖励窗口**：绑定次周周一 00:00 起整 4 周；「奖励已发放」使窗口内绑定剩余周数 -1
- **奖励档位**：周任务≥6次+铜牌及以上 12.8×2；晋升初银 12.8×2 / 银牌 23.3×2 / 金牌 52×2 / 王牌 131.4×2（单人份，实际 ×2 双人）
- 达标自动生成待发放记录，人工标记已发/可撤销

## 部署

### 本地/Docker（内网）
```bash
docker compose up -d --build   # 打开 http://127.0.0.1:5000
```
- 运行机器需能访问内网（server1.tuwan.com / bigdata.tuwan.com）
- `data/`（数据库、Cookie、凭据）通过卷挂载，不进镜像

### ngrok 公网穿透
```bash
tools/ngrok.exe http 5000
```
- 域名变化检测：`tools/ngrok_watch.py 60`（变化时记录并自动打开新链接）

## 安全与运维

- 管理员密码存于 `data/admin_config.json`（gitignore），不写死在代码
- 培训师密码哈希存储（werkzeug），不可反查
- 登录失败会清除旧登录态；管理 API 未登录 401
- SQLite WAL + 长查询串行锁，减少互踢 Cookie 和写冲突
- 静态资源缓存协商（304）+ 文本 gzip，优化移动端加载

## 测试

```bash
.venv/Scripts/python.exe -X utf8 backend/smoke_test.py   # 116 项 API 冒烟测试
```

## 数据与凭据

以下文件均在 `data/` 且已 gitignore，不进版本库：
- `login_credentials.json` / `cookie.json` / `cookie_bigdata.json` — 外部系统凭据与 Cookie
- `admin_config.json` / `flask_secret.txt` — 管理员与 Session 配置
- `stats.db` — 主数据库（含历史快照）
- `weekly_refresh_status.json` / `ngrok_state.json` / `ngrok_changes.log`

## 备份与恢复

`tools/backup_manager.py` 使用 SQLite 在线安全备份，包含两个数据库、LUNA 上传图片、自托管课件和必要配置。备份文件及恢复目录均不进入 Git。

```bash
# 必须换成独立的强密码，不要写入仓库
export BACKUP_PASSWORD='替换为独立强密码'
.venv/Scripts/python.exe -X utf8 tools/backup_manager.py backup

# 在独立空目录验证恢复，不覆盖正式数据
.venv/Scripts/python.exe -X utf8 tools/backup_manager.py restore backups/local/备份文件.zip.enc --dest backups/restore-check
```

恢复结果必须同时显示 `trainer/data/stats.db` 和 `luna/data.db` 的 `integrity_check=ok`。每日备份可通过 Windows 任务计划程序调用同一命令。

异地上传使用 rclone，并强制要求加密：

```bash
export BACKUP_REMOTE='远程名称:trainer-backups'
.venv/Scripts/python.exe -X utf8 tools/backup_manager.py backup
```

未配置 `BACKUP_REMOTE` 时只生成本地备份，输出 `offsite: pending`。公司云存储或 R2/B2 的凭据配置在 rclone 中，不写入项目。本地保留最近 7 份日备份、4 份周备份和 3 份月备份；远程版本清理策略另行配置。

内部测试场景与通过标准见 `INTERNAL_TEST.md`。

## 版本历史

- **v1.0.0** — 正式版：绑定管理、名额奖励、用户端账号体系、姐姐冲突检查、操作日志、ngrok 穿透与域名检测
