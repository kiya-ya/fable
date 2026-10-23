#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""培训师系统数据库：trainers / trainees / bindings 三表，建在 data/stats.db"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'crawler'))
from db import get_db  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS trainers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    nickname TEXT NOT NULL,
    hall_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trainees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    nickname TEXT NOT NULL,
    hall_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trainer_id INTEGER NOT NULL REFERENCES trainers(id),
    trainee_id INTEGER NOT NULL REFERENCES trainees(id),
    bind_type TEXT NOT NULL DEFAULT 'trainer',   -- trainer(培训师) / sister(姐妹团三胎)
    bound_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    unbound_at TIMESTAMP,
    note TEXT
);

-- 生效绑定的唯一索引在 _migrate 中建（兼容老库先补 bind_type 列）

CREATE INDEX IF NOT EXISTS idx_bindings_trainer ON bindings(trainer_id, unbound_at);

-- 学员当月等级记录：速查时 upsert，支撑「当月解锁名额、次月掉级重置」
CREATE TABLE IF NOT EXISTS trainee_level_monthly (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trainee_uid TEXT NOT NULL,
    month TEXT NOT NULL,                 -- YYYY-MM
    best_level TEXT,                     -- 当月查到的最高周等级
    best_rank INTEGER DEFAULT 0,
    last_week_level TEXT,                -- 最近一次查到的当周等级
    last_daily_task_count INTEGER,       -- 最近一次查到的每日任务完成次数
    last_queried_at TEXT,
    UNIQUE(trainee_uid, month)
);

-- 奖励发放记录：达标自动生成 pending，人工标记 granted，UNIQUE 防重
CREATE TABLE IF NOT EXISTS reward_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    binding_id INTEGER NOT NULL REFERENCES bindings(id),
    trainee_uid TEXT NOT NULL,
    trainer_id INTEGER NOT NULL,
    reward_key TEXT NOT NULL,
    reward_label TEXT,
    amount REAL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / granted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_at TIMESTAMP,
    UNIQUE(binding_id, reward_key)
);
"""


def _migrate(conn):
    """老库补列/改索引"""
    cols = {r[1] for r in conn.execute('PRAGMA table_info(trainers)').fetchall()}
    if 'base_slots' not in cols:
        conn.execute('ALTER TABLE trainers ADD COLUMN base_slots INTEGER NOT NULL DEFAULT 2')
    if 'role' not in cols:
        # role: trainer(培训师) / sister(姐妹团姐姐)
        conn.execute("ALTER TABLE trainers ADD COLUMN role TEXT NOT NULL DEFAULT 'trainer'")
    if 'password_hash' not in cols:
        # 用户端账号密码（哈希存储，不可逆；管理员设置/重置，用户可自改）
        conn.execute('ALTER TABLE trainers ADD COLUMN password_hash TEXT')
    # 操作日志：谁（admin/portal/system）在何时对谁做了什么
    conn.execute('''CREATE TABLE IF NOT EXISTS operation_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_type TEXT NOT NULL,
        actor_uid TEXT,
        action TEXT NOT NULL,
        bind_type TEXT,
        trainer_uid TEXT,
        trainee_uid TEXT,
        detail TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    bcols = {r[1] for r in conn.execute('PRAGMA table_info(bindings)').fetchall()}
    if 'bind_type' not in bcols:
        conn.execute("ALTER TABLE bindings ADD COLUMN bind_type TEXT NOT NULL DEFAULT 'trainer'")
    if 'weeks_consumed' not in bcols:
        # 已发放周数：「奖励已发放」一键 +1，剩余周数 = 日历剩余 - 已发放
        conn.execute('ALTER TABLE bindings ADD COLUMN weeks_consumed INTEGER NOT NULL DEFAULT 0')
    # 状态简化为 active(活跃)/inactive(退出)，老的 graduated 并入 inactive
    conn.execute("UPDATE trainees SET status='inactive' WHERE status='graduated'")
    mcols = {r[1] for r in conn.execute('PRAGMA table_info(trainee_level_monthly)').fetchall()}
    if 'last_retained' not in mcols:
        # 留存判定：UID 查询的排档大厅/权限大厅/当周等级全空 → 0（未留存，可判解散）
        conn.execute('ALTER TABLE trainee_level_monthly ADD COLUMN last_retained INTEGER')
    tcols = {r[1] for r in conn.execute('PRAGMA table_info(trainees)').fetchall()}
    if 'protection_end' not in tcols:
        # 保护期结束时间（查询时同步到档案，绑定列表展示用）
        conn.execute('ALTER TABLE trainees ADD COLUMN protection_end TEXT')
    if 'prev_week_tasks' not in mcols:
        # 上周任务次数（任务档奖励口径 = 上周任务 + 当周牌子）
        conn.execute('ALTER TABLE trainee_level_monthly ADD COLUMN prev_week_tasks INTEGER')
    if 'best_rank_active' not in mcols:
        # 排档周最高等级：仅当周排档天数>0 的查询才计入名额贡献
        conn.execute('ALTER TABLE trainee_level_monthly ADD COLUMN best_rank_active INTEGER DEFAULT 0')
        conn.execute('ALTER TABLE trainee_level_monthly ADD COLUMN best_level_active TEXT')
        # 存量数据一次性回填：老记录没有排档天数字段，按已有等级计入
        conn.execute('UPDATE trainee_level_monthly SET best_rank_active=best_rank, best_level_active=best_level')
    # 唯一索引从「每妹妹一条生效」升级为「每妹妹每类型一条生效」
    idx = {r[1] for r in conn.execute("PRAGMA index_list(bindings)").fetchall()}
    if 'idx_bindings_active_trainee' in idx:
        conn.execute('DROP INDEX idx_bindings_active_trainee')
    conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_bindings_active
                    ON bindings(trainee_id, bind_type) WHERE unbound_at IS NULL''')


def init_trainer_db():
    conn = get_db()
    conn.executescript(DDL)
    _migrate(conn)
    conn.commit()
    conn.close()
    print('[OK] trainer tables initialized.')


if __name__ == '__main__':
    init_trainer_db()
