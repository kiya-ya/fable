-- 姐妹团数据统计报表 - SQLite 数据库结构
-- 创建于 2026-07-27

-- 1. 统计数据表 (每日/每周聚合指标，来自 sisters/tj)
CREATE TABLE IF NOT EXISTS stats_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle TEXT NOT NULL,                    -- 统计日期，如 "07-26星期日"
    date_str TEXT,                          -- 完整日期 YYYY-MM-DD，用于计算 "07-26星期日"
    hall_name TEXT NOT NULL,                -- 大厅名称
    new_team_count INTEGER DEFAULT 0,       -- 新成团数
    active_team_count INTEGER DEFAULT 0,    -- 进行中姐妹团数
    dissolved_count INTEGER DEFAULT 0,      -- 团解散数
    active_dissolved_count INTEGER DEFAULT 0, -- 主动解散数
    system_dissolved_count INTEGER DEFAULT 0, -- 系统解散数
    drive_task_count INTEGER DEFAULT 0,     -- 开车任务完成次数
    accompany_task_count INTEGER DEFAULT 0, -- 陪档任务完成次数
    gift_task_count INTEGER DEFAULT 0,      -- 收送礼任务完成次数
    level_achievement_count INTEGER DEFAULT 0,  -- 等级成就达成数
    revenue_achievement_count INTEGER DEFAULT 0, -- 流水成就达成数
    reward_amount REAL DEFAULT 0.0,         -- 发放礼物奖励金额
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date_str, hall_name)
);

-- 2. 基础数据明细表 (来自 sisters/detail/)
CREATE TABLE IF NOT EXISTS team_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,               -- 姐妹团ID
    form_date TEXT,                         -- 成团日期
    hall_name TEXT,                         -- 大厅名称
    sister_uid INTEGER,                     -- 姐姐UID
    sister_nickname TEXT,                   -- 姐姐昵称
    sister_level TEXT,                      -- 姐姐当前等级
    sister_uid2 INTEGER,                    -- 妹妹UID
    sister_nickname2 TEXT,                  -- 妹妹昵称
    sister_level2 TEXT,                     -- 妹妹当前等级
    sister_max_level2 TEXT,                 -- 妹妹最高等级
    sister_revenue REAL DEFAULT 0.0,        -- 妹妹累计流水
    drive_task_count INTEGER DEFAULT 0,
    accompany_task_count INTEGER DEFAULT 0,
    gift_task_count INTEGER DEFAULT 0,
    level_achievement_count INTEGER DEFAULT 0,
    revenue_achievement_count INTEGER DEFAULT 0,
    silver_box_achievement INTEGER DEFAULT 0, -- 银箱子成就
    days_since_formed INTEGER DEFAULT 0,    -- 已成团天数
    reward_amount REAL DEFAULT 0.0,         -- 累计奖励
    dissolve_date TEXT,                     -- 解散日期
    dissolve_reason TEXT,                   -- 解散原因
    snapshot_date TEXT,                     -- 快照日期(抓取当天)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. 折线图趋势数据缓存 (来自 getlineData API)
CREATE TABLE IF NOT EXISTS trend_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,              -- 指标名: new_team_count / active_team / dissolved / reward
    hall_name TEXT NOT NULL,                -- all 或具体大厅
    date_type INTEGER NOT NULL,             -- 1=日, 2=周, 3=月
    date_label TEXT NOT NULL,               -- 日期标签 "2026-07-20" 或 "2026-07-20~2026-07-26"
    value REAL DEFAULT 0.0,                 -- 数值
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(metric_name, hall_name, date_type, date_label)
);

-- 4. 周报指标汇总表 (由 stats_daily 聚合计算生成)
CREATE TABLE IF NOT EXISTS weekly_report (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_label TEXT NOT NULL,               -- 如 "W30(07-21~07-27)"
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    hall_name TEXT NOT NULL,                -- all 或具体大厅
    new_team_count INTEGER DEFAULT 0,       -- 周新成团数
    active_team_count_end INTEGER DEFAULT 0, -- 周末进行中数
    active_team_count_start INTEGER DEFAULT 0, -- 周初进行中数
    dissolved_count INTEGER DEFAULT 0,      -- 周解散数
    active_dissolved_count INTEGER DEFAULT 0,
    system_dissolved_count INTEGER DEFAULT 0,
    retention_rate REAL DEFAULT 0.0,        -- 周留存率
    dissolution_rate REAL DEFAULT 0.0,      -- 周解散率
    total_reward REAL DEFAULT 0.0,          -- 周总流水
    avg_reward_per_team REAL DEFAULT 0.0,   -- 单团平均流水
    total_drive_tasks INTEGER DEFAULT 0,
    total_accompany_tasks INTEGER DEFAULT 0,
    total_gift_tasks INTEGER DEFAULT 0,
    activity_index REAL DEFAULT 0.0,        -- 综合活跃度
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(week_start, week_end, hall_name)
);

-- 5. 预警记录表
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,               -- 预警类型
    severity TEXT NOT NULL,                 -- high / medium / low
    title TEXT NOT NULL,
    description TEXT,
    metric_name TEXT,
    metric_value REAL,
    threshold REAL,
    week_label TEXT,
    is_resolved INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. 抓取日志表
CREATE TABLE IF NOT EXISTS crawl_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,                   -- success / failed
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. 大厅统计数据表 (从 team_detail 聚合生成)
CREATE TABLE IF NOT EXISTS hall_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,            -- 快照日期
    hall_name TEXT NOT NULL,                -- 大厅名称
    team_count INTEGER DEFAULT 0,           -- 姐妹团总数
    active_count INTEGER DEFAULT 0,         -- 进行中团数
    dissolved_count INTEGER DEFAULT 0,      -- 解散团数
    total_revenue REAL DEFAULT 0.0,         -- 总流水
    total_reward REAL DEFAULT 0.0,          -- 总奖励
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, hall_name)
);

-- 8. 姐妹团周流水表（姐姐+妹妹当周礼物总流水合计，来自 server1 UID 批量查询）
CREATE TABLE IF NOT EXISTS team_sister_revenue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    hall_name TEXT,
    sister_uid TEXT,
    sister_revenue REAL DEFAULT 0.0,        -- 姐姐当周礼物总流水
    sister_uid2 TEXT,
    sister2_revenue REAL DEFAULT 0.0,       -- 妹妹当周礼物总流水
    total_revenue REAL DEFAULT 0.0,         -- 合计
    queried_at TEXT,
    UNIQUE(team_id, week_start)
);

-- 索引优化
CREATE TABLE IF NOT EXISTS crawl_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,                   -- success / failed
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引优化
CREATE INDEX IF NOT EXISTS idx_stats_date ON stats_daily(cycle);
CREATE INDEX IF NOT EXISTS idx_stats_hall ON stats_daily(hall_name);
CREATE INDEX IF NOT EXISTS idx_detail_team ON team_detail(team_id);
CREATE INDEX IF NOT EXISTS idx_detail_snapshot ON team_detail(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_detail_form ON team_detail(form_date);
CREATE INDEX IF NOT EXISTS idx_detail_dissolve ON team_detail(dissolve_date);
CREATE INDEX IF NOT EXISTS idx_detail_hall ON team_detail(hall_name);
CREATE INDEX IF NOT EXISTS idx_trend_metric ON trend_data(metric_name, date_type);
CREATE INDEX IF NOT EXISTS idx_report_week ON weekly_report(week_start, week_end);

-- 6. 管理员用户表（UID白名单登录）
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    nickname TEXT,
    role TEXT DEFAULT 'admin',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 默认插入一个管理员（后续可手动添加更多）
-- INSERT OR IGNORE INTO users (uid, nickname) VALUES ('123456', '管理员');
