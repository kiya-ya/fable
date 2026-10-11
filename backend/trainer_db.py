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
    bcols = {r[1] for r in conn.execute('PRAGMA table_info(bindings)').fetchall()}
    if 'bind_type' not in bcols:
        conn.execute("ALTER TABLE bindings ADD COLUMN bind_type TEXT NOT NULL DEFAULT 'trainer'")
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
