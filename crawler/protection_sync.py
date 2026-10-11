#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""妹妹「保护期结束时间」同步（UID 查询系统 → member_protection 表）

明细表「保护期结束时间」列的数据源。bigdata 快照里没有该字段，
只能通过 UID 查询系统逐个查妹妹（server1 会话极短，带自动重登续跑）。
保护期结束时间相对固定，默认 7 天内的记录不重复查询。
"""
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_db
from uid_crawler import UIDCrawler, CookieExpiredError

DDL = """
CREATE TABLE IF NOT EXISTS member_protection (
    uid TEXT PRIMARY KEY,
    protection_end TEXT,
    checked_at TEXT
)
"""


def init_table(conn):
    conn.execute(DDL)
    conn.commit()


def _active_sister2_uids(conn):
    """最新快照中进行中团的妹妹 UID 列表"""
    return [str(r['uid']) for r in conn.execute("""
        SELECT DISTINCT sister_uid2 AS uid FROM team_detail
        WHERE rowid IN (SELECT MAX(rowid) FROM team_detail GROUP BY team_id)
          AND (dissolve_date IS NULL OR dissolve_date = '')
          AND sister_uid2 IS NOT NULL AND sister_uid2 != ''
    """).fetchall()]


def sync_protection(limit=120, delay=0.6, max_heals=3, stale_days=7):
    """同步进行中团妹妹的保护期结束时间。返回统计 dict。"""
    conn = get_db()
    init_table(conn)
    stale_before = (datetime.now() - timedelta(days=stale_days)).strftime('%Y-%m-%d %H:%M:%S')
    known = {r['uid'] for r in conn.execute(
        "SELECT uid FROM member_protection WHERE checked_at >= ?", (stale_before,)).fetchall()}
    pending = [u for u in _active_sister2_uids(conn) if u not in known][:limit]

    stats = {'total': len(pending), 'ok': 0, 'not_found': 0, 'failed': 0}
    crawler = None
    healed = 0
    stored_since_heal = 0
    for uid in pending:
        try:
            if crawler is None:
                crawler = UIDCrawler()
            try:
                d = crawler.query(uid)
            except CookieExpiredError:
                if healed >= max_heals or (healed > 0 and stored_since_heal == 0):
                    raise
                from auto_login import refresh_uid_cookie
                refresh_uid_cookie()
                crawler = UIDCrawler()
                healed += 1
                stored_since_heal = 0
                print(f'[ProtectionSync] Cookie 过期，已自动重登（第 {healed} 次），继续')
                d = crawler.query(uid)
            time.sleep(delay)
            if d.get('found'):
                pe = (d.get('protection_end') or '').strip()[:10]
                conn.execute(
                    "INSERT OR REPLACE INTO member_protection (uid, protection_end, checked_at) "
                    "VALUES (?, ?, ?)",
                    (uid, pe, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                stored_since_heal += 1
                stats['ok'] += 1
            else:
                stats['not_found'] += 1
        except CookieExpiredError:
            print('[ProtectionSync-WARN] Cookie 重登无效，本次停止，下轮继续')
            break
        except Exception as e:
            stats['failed'] += 1
            print(f'[ProtectionSync-WARN] UID {uid} 查询异常: {e}')
    conn.close()
    print(f'[ProtectionSync] 本批: {stats}')
    return stats


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    max_heals = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f'[ProtectionSync] 开始同步（本批上限 {limit}，重登上限 {max_heals}）...')
    sync_protection(limit=limit, max_heals=max_heals)
