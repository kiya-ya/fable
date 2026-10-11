#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量查询「姐妹团周流水」= 姐姐 + 妹妹 的「当周礼物总流水」合计

数据源: server1.tuwan.com:10010 / play_user_newcaptian.php
口径:   姐妹团周流水 = 姐姐(week_revenue) + 妹妹(week_revenue)
存储:   data/stats.db 的 team_sister_revenue 表（team_id + week 维度）

用法:
  python crawler/team_weekly_revenue.py               # 查本周全部进行中团
  python crawler/team_weekly_revenue.py --limit 10    # 先小批量验证
  python crawler/team_weekly_revenue.py --weeks 4     # 回填最近 4 周
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from db import get_db
from uid_crawler import UIDCrawler, CookieExpiredError


def get_week_range(offset: int = 0):
    """本周（或向前偏移 offset 周）的周一起止日期"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')


def ensure_table(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS team_sister_revenue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            hall_name TEXT,
            sister_uid TEXT,
            sister_revenue REAL DEFAULT 0.0,
            sister_uid2 TEXT,
            sister2_revenue REAL DEFAULT 0.0,
            total_revenue REAL DEFAULT 0.0,
            queried_at TEXT,
            UNIQUE(team_id, week_start)
        )
    ''')
    conn.commit()


def get_active_teams(conn):
    """最新快照中所有进行中的姐妹团（team_id, 大厅, 姐姐UID, 妹妹UID）"""
    return conn.execute('''
        SELECT team_id, hall_name, sister_uid, sister_uid2
        FROM team_detail
        WHERE rowid IN (SELECT MAX(rowid) FROM team_detail
                        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM team_detail)
                        GROUP BY team_id)
          AND (dissolve_date = '' OR dissolve_date IS NULL)
          AND sister_uid IS NOT NULL AND sister_uid != ''
    ''').fetchall()


def query_one_uid(uid: str, week_start: str, week_end: str) -> float:
    """查询单个 UID 的当周礼物总流水（未找到返回 0）"""
    c = UIDCrawler()  # 每线程独立实例，热加载 cookie.json
    r = c.query(uid, 'game', week_start, week_end)
    return float(r.get('week_revenue', 0) or 0) if r.get('found') else 0.0


def run(weeks: int = 1, max_workers: int = 8, limit: int = None):
    conn = get_db()
    ensure_table(conn)
    teams = get_active_teams(conn)
    conn.close()
    if limit:
        teams = teams[:limit]
    print(f'进行中姐妹团: {len(teams)} 个')

    for offset in range(weeks):
        ws, we = get_week_range(offset)
        print(f'\n===== 周期 {ws} ~ {we} =====')

        # 收集去重后的 UID（姐姐 + 妹妹），并记录每个 UID 归属的团队与角色
        uid_roles = {}  # uid -> list[(team_id, role)]
        for t in teams:
            for uid, role in [(t['sister_uid'], 'sister'), (t['sister_uid2'], 'sister2')]:
                if uid:
                    uid_roles.setdefault(str(uid), []).append((t['team_id'], role))
        uids = list(uid_roles.keys())
        print(f'需查询 UID: {len(uids)} 个（姐姐+妹妹去重）')

        # 并行查询
        rev = {}
        retry_uids = []   # Cookie 过期导致的失败，重登后补查
        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(query_one_uid, u, ws, we): u for u in uids}
            for fut in as_completed(futs):
                u = futs[fut]
                done += 1
                try:
                    rev[u] = round(fut.result(), 2)
                except CookieExpiredError:
                    # server1 会话 TTL 极短：不中断整批，记录下来稍后自愈重试
                    retry_uids.append(u)
                except Exception as e:
                    rev[u] = 0.0
                    print(f'  [UID {u} 查询失败] {str(e)[:80]}')
                if done % 100 == 0:
                    print(f'  进度 {done}/{len(uids)}')

        # Cookie 过期自愈：重登后串行补查（query_one_uid 每次新建 UIDCrawler，热加载新 cookie）
        heal_round = 0
        while retry_uids and heal_round < 3:
            heal_round += 1
            print(f'  [Cookie自愈] 第 {heal_round} 轮：重登后补查 {len(retry_uids)} 个 UID')
            try:
                from auto_login import refresh_uid_cookie
                refresh_uid_cookie()
            except Exception as he:
                print(f'  [Cookie自愈失败] {he}')
                break
            pending, retry_uids = retry_uids, []
            for u in pending:
                try:
                    rev[u] = round(query_one_uid(u, ws, we), 2)
                except CookieExpiredError:
                    retry_uids.append(u)
                except Exception:
                    rev[u] = 0.0
        if retry_uids:
            print(f'  [WARN] {len(retry_uids)} 个 UID 因 Cookie 问题未查到，按 0 计')
            for u in retry_uids:
                rev.setdefault(u, 0.0)

        # 聚合到团队
        team_rev = {}  # team_id -> {sister_revenue, sister2_revenue, total}
        for uid, pairs in uid_roles.items():
            val = rev.get(uid, 0.0)
            for tid, role in pairs:
                d = team_rev.setdefault(tid, {'sister_revenue': 0.0, 'sister2_revenue': 0.0})
                if role == 'sister':
                    d['sister_revenue'] = val
                else:
                    d['sister2_revenue'] = val
        for d in team_rev.values():
            d['total'] = round(d['sister_revenue'] + d['sister2_revenue'], 2)

        # 写入数据库
        conn = get_db()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for t in teams:
            tid = t['team_id']
            d = team_rev.get(tid, {'sister_revenue': 0.0, 'sister2_revenue': 0.0, 'total': 0.0})
            conn.execute('''
                INSERT OR REPLACE INTO team_sister_revenue
                (team_id, week_start, week_end, hall_name, sister_uid, sister_revenue,
                 sister_uid2, sister2_revenue, total_revenue, queried_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (tid, ws, we, t['hall_name'], str(t['sister_uid']), d['sister_revenue'],
                  str(t['sister_uid2'] or ''), d['sister2_revenue'], d['total'], now))
        conn.commit()
        total = sum(d['total'] for d in team_rev.values())
        conn.close()
        print(f'✅ 完成 {len(teams)} 团 · 姐妹团周流水合计 ¥{total:,.0f}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='批量查询姐妹团周流水（姐姐+妹妹当周礼物总流水）')
    parser.add_argument('--weeks', type=int, default=1, help='回填最近 N 周（默认 1）')
    parser.add_argument('--workers', type=int, default=8, help='并发线程数（默认 8）')
    parser.add_argument('--limit', type=int, default=None, help='只查前 N 个团（测试用）')
    args = parser.parse_args()
    run(weeks=args.weeks, max_workers=args.workers, limit=args.limit)
