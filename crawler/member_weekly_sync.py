#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毕业妹妹追踪：每周同步毕业生的个人周流水/排档天数（UID 查询系统 → member_weekly 表）

背景（2026-09-14 grilling 结论）：team_detail 只有姐妹团数据，妹妹毕业后若仍在大厅
排档（不成团）完全不可见 → 毕业留存失真。本模块按人追踪毕业生毕业后的真实产出。
产出线：毕业后按老人要求 ≥1344/周（新人阶梯 336/672/1008/1344 的第四档）。

追踪范围：近 12 周内的姐妹团毕业生，以及完成完整 4 周带教窗口的培训师妹妹。
培训师提前解散不算毕业；同一 UID 取首次毕业，避免换绑后重复进入样本。

用法:
  python crawler/member_weekly_sync.py              # 同步本周和上周
  python crawler/member_weekly_sync.py --weeks 4    # 回填最近 4 周
"""
import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
from db import get_db
from uid_crawler import UIDCrawler, CookieExpiredError

DDL = """
CREATE TABLE IF NOT EXISTS member_weekly (
    uid TEXT NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    nickname TEXT,
    revenue REAL DEFAULT 0.0,
    schedule_days INTEGER DEFAULT 0,
    week_level TEXT,
    queried_at TEXT,
    UNIQUE(uid, week_start)
)
"""

# 追踪窗口：近 12 周内毕业的妹妹
TRACK_WEEKS = 12


def ensure_table(conn):
    conn.execute(DDL)
    conn.commit()


def get_week_range(offset: int = 0):
    today = datetime.now()
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')


def trainer_graduation_date(bound_at):
    """培训师带教毕业日：绑定次周周一起的 4 周窗口结束日（周一）。"""
    local = datetime.strptime(bound_at, '%Y-%m-%d %H:%M:%S') + timedelta(hours=8)
    days_to_monday = (7 - local.weekday()) % 7 or 7
    window_start = (local + timedelta(days=days_to_monday)).date()
    return window_start + timedelta(weeks=4)


def get_trainer_graduates(conn, since=None):
    """完成完整带教窗口的培训师妹妹；提前解散不算毕业，同一 UID 取首次毕业。"""
    today = datetime.now().date()
    rows = conn.execute('''
        SELECT t.uid, t.nickname, b.bound_at, b.unbound_at
        FROM bindings b JOIN trainees t ON t.id=b.trainee_id
        WHERE b.bind_type='trainer' ORDER BY b.bound_at
    ''').fetchall()
    graduates = {}
    for row in rows:
        grad_date = trainer_graduation_date(row['bound_at'])
        if grad_date > today or (since and grad_date < since):
            continue
        if row['unbound_at']:
            unbound_date = (datetime.strptime(row['unbound_at'], '%Y-%m-%d %H:%M:%S') + timedelta(hours=8)).date()
            if unbound_date < grad_date:
                continue
        if row['uid'] not in graduates or grad_date < graduates[row['uid']]['grad_date']:
            graduates[row['uid']] = {
                'uid': row['uid'], 'nickname': row['nickname'], 'grad_date': grad_date,
            }
    return sorted(graduates.values(), key=lambda g: g['grad_date'], reverse=True)


def get_tracked_uids(conn):
    """近 12 周内的姐妹团毕业生 + 完成 4 周带教的培训师妹妹。"""
    since_date = (datetime.now() - timedelta(weeks=TRACK_WEEKS)).date()
    sister_rows = conn.execute("""
        SELECT CAST(sister_uid2 AS TEXT) AS uid, MAX(sister_nickname2) AS nickname,
               MAX(dissolve_date) AS grad_date
        FROM team_detail
        WHERE dissolve_reason = '毕业' AND dissolve_date >= ?
          AND sister_uid2 IS NOT NULL AND sister_uid2 != ''
        GROUP BY uid ORDER BY grad_date DESC
    """, (since_date.strftime('%Y-%m-%d'),)).fetchall()
    graduates = {}
    for row in sister_rows:
        graduates[row['uid']] = {'uid': row['uid'], 'nickname': row['nickname'], 'grad_date': row['grad_date']}
    for row in get_trainer_graduates(conn, since=since_date):
        if row['uid'] not in graduates or str(row['grad_date']) < str(graduates[row['uid']]['grad_date']):
            graduates[row['uid']] = row
    return sorted(graduates.values(), key=lambda g: str(g['grad_date']), reverse=True)


def sync(weeks: int = 2, delay: float = 0.6, max_heals: int = 50):
    conn = get_db()
    ensure_table(conn)
    grads = get_tracked_uids(conn)
    conn.close()
    print(f'[MemberWeekly] 追踪中的毕业妹妹: {len(grads)} 位（近 {TRACK_WEEKS} 周毕业）')

    crawler = None
    healed = 0
    for offset in range(weeks):
        ws, we = get_week_range(offset)
        print(f'\n===== 周期 {ws} ~ {we} =====')
        ok = fail = 0
        for g in grads:
            uid = g['uid']
            try:
                if crawler is None:
                    crawler = UIDCrawler()
                try:
                    d = crawler.query(uid, 'game', ws, we)
                except CookieExpiredError:
                    if healed >= max_heals:
                        raise
                    from auto_login import refresh_uid_cookie
                    refresh_uid_cookie()
                    crawler = UIDCrawler()
                    healed += 1
                    print(f'  [Cookie自愈] 第 {healed} 次重登，继续')
                    d = crawler.query(uid, 'game', ws, we)
                time.sleep(delay)
                if not d.get('found'):
                    fail += 1
                    continue
                conn = get_db()
                ensure_table(conn)
                conn.execute('''
                    INSERT OR REPLACE INTO member_weekly
                    (uid, week_start, week_end, nickname, revenue, schedule_days, week_level, queried_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (uid, ws, we, d.get('nickname') or g['nickname'] or '',
                      float(d.get('week_revenue') or 0), int(d.get('week_schedule_days') or 0),
                      d.get('week_level') or '', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                conn.close()
                ok += 1
                if ok % 50 == 0:
                    print(f'  进度 {ok + fail}/{len(grads)}')
            except CookieExpiredError:
                print('[MemberWeekly-WARN] Cookie 重登超限，本轮停止，剩余下轮再跑')
                return
            except Exception as e:
                fail += 1
                print(f'  [UID {uid} 失败] {str(e)[:80]}')
        print(f'✅ {ws} 周完成：成功 {ok} / 失败 {fail}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='毕业妹妹个人周流水追踪')
    parser.add_argument('--weeks', type=int, default=2, help='同步最近 N 周（默认 2，含本周与上周）')
    args = parser.parse_args()
    sync(weeks=args.weeks)
