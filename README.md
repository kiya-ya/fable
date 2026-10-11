# 培训师系统

> 基于「姐妹团看板系统」的爬虫/数据层搭建的操作型系统：培训师档案、妹妹档案、绑定关系管理、UID 数据速查。
> **外部系统的认证/接口/表结构/坑见 `爬虫系统上下文.md`**。

## 已有资产（从姐妹团看板系统拷贝）

- `crawler/` — 全套爬虫：自动登录（OCR）、Cookie 保活、UID 查询、bigdata 抓取、周流水/保护期/毕业追踪
- `data/login_credentials.json` — server1 账号凭据（勿提交）
- `data/cookie.json` / `data/cookie_bigdata.json` — 当前有效 Cookie
- `data/schema.sql` + `data/stats.db` — 表结构 + 历史数据（20MB，含 team_detail 全量快照）

## 环境搭建

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
```

注意：`requirements.txt` 必须保持 ASCII（GBK 环境的 pip 读不了中文注释）。

## 启动

```bash
.venv/Scripts/python.exe -X utf8 backend/app.py
# 打开 http://127.0.0.1:5000
```

启动时自动：建培训师相关 3 张表 → 60 秒后挂 Cookie 保活后台线程（30 分钟/轮，失效自动 OCR 重登）。

## 系统结构

```
backend/
├── app.py            # Flask：API + 静态文件 + 保活线程（端口 5000）
├── trainer_db.py     # trainers / trainees / bindings / trainee_level_monthly / reward_grants 五表 DDL（建在 data/stats.db）
├── smoke_test.py     # API 冒烟测试（35 项，自清理测试数据）
└── static/           # 前端单页（原生 HTML/JS，无框架）
    ├── index.html    # 四个 Tab：UID 速查（首页）/ 绑定关系 / 培训师管理 / 妹妹管理
    ├── app.js
    └── style.css
```

## 功能说明

- **UID 速查（首页）**：输入 UID 实时查 server1（本周 vs 上周对比：等级/排档/任务/流水/排名），并按 UID 身份自动带出判定面板：
  - 查**培训师** → **名额面板**：基础名额 + 各学员当月等级贡献 = 总名额（上限 5），显示已用/是否超额；「刷新全部学员数据」逐个实时查询学员当周等级（0.6s 间隔）
  - 查**妹妹** → **奖励面板**：绑定窗口（28 天）倒计时 + 五档奖励状态（未达标/待发放/已发放），可手动标记已发/撤销
  - Cookie 过期时自动 OCR 重登后重试一次（server1 会话 TTL 极短）
- **绑定关系**：绑定/解绑/换绑（同一妹妹同时仅一条生效绑定，重复绑定会 409 提示确认换绑）；历史记录保留
- **培训师/妹妹管理**：增删改查 + 搜索；新增时可用「自动回填」从 UID 查询系统拉昵称/大厅；有生效绑定时禁止删除；培训师档案含「基础名额」（默认 2）
- **妹妹导入**：从 `team_detail` 最新快照批量导入妹妹档案

## 名额与奖励政策口径（代码实现位置 `backend/app.py` 顶部常量区）

**名额规则**
- 通过培训师考试 → 基础 2 个名额（档案 `base_slots`，默认 2 可改）
- 学员当月**当周等级**达标叠加：初银（初级银牌）+1 / 银牌+1 / 金牌+1（金牌学员一人 +3，即直升 5），总上限 5
- 实现方式：每次速查/刷新把学员当周等级 upsert 进 `trainee_level_monthly`（取当月最高），名额按当月最高等级计算 → 当月达标即解锁，次月未再达标则自然重置
- 与姐妹团名额/奖励相互独立（本系统只记培训师绑定）

**奖励规则**（绑定起 28 天内有效，金额为单人份，实际 ×2 由培训师和新人各得一份，礼物形式赠送）
- 周任务≥6次 + 铜牌及以上：12.8×2
- 晋升初银：12.8×2 / 晋升银牌：23.3×2 / 晋升金牌：52×2 / 晋升王牌：131.4×2
- 达标自动生成 `reward_grants` 待发放记录（UNIQUE(binding_id, reward_key) 防重），人工标记已发

注意：学员「刷新全部学员数据」的批量查询固定用 `game`（新队长-游戏）类型；其他类型的学员请在速查页手动选类型单查。

数据口径：绑定关系只存在本系统（`data/stats.db` 的 bindings 表），不提交外部系统。

## 快速验证爬虫可用

```bash
cd crawler
../.venv/Scripts/python.exe -X utf8 auto_login.py       # 测自动登录
../.venv/Scripts/python.exe -X utf8 cookie_keepalive.py # 测保活
```

## TODO

- [x] 需求确认：操作型系统（档案 + 绑定 + 速查），非看板
- [x] 基于 crawler/ 复用认证与抓取，新增培训师相关表
- [ ] 后续按需：培训师维度统计（带教人数/学员毕业率等）
