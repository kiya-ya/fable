#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离职解散原因细分：判断「离职」方是姐姐还是妹妹

两种来源：
1. `35758616 离职` 格式：bigdata 直接给出 UID → 与团内姐姐/妹妹 UID 比对（零请求）
2. `姐妹任意一方从大厅离职自动解散`：通过 UID 查询系统取双方「最近一次离职时间」，
   与解散日期比对（精确日优先，容忍 ±1 天；双方同日 → 「双方」）

判定结果存 team_leaver 表，并把 team_detail 该团所有快照行的 dissolve_reason 回写为
「姐姐从大厅离职自动解散」/「妹妹从大厅离职自动解散」/「姐妹双方同日离职自动解散」。
注意：每日抓取的新快照会带回原始文案，所以每日抓取完成后必须重新 apply_leaver_reasons()。
查询失败（网络/Cookie）不写记录，下一轮自动重试；明确「未判定」的写记录且不再重试。
"""
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_db
from uid_crawler import UIDCrawler, CookieExpiredError

# 细分后的回写文案
ROLE_REASON = {
    '姐姐': '姐姐从大厅离职自动解散',
    '妹妹': '妹妹从大厅离职自动解散',
    '双方': '姐妹双方同日离职自动解散',
}


def reason_text(role, leave_time=''):
    """回写文案：有离职时间时附上（离职 YYYY-MM-DD）"""
    base = ROLE_REASON.get(role)
    if not base:
        return None
    lt = (leave_time or '')[:10]
    return f"{base}（离职 {lt}）" if lt else base

DDL = """
CREATE TABLE IF NOT EXISTS team_leaver (
    team_id INTEGER PRIMARY KEY,
    leaver_role TEXT,       -- 姐姐 / 妹妹 / 双方 / 未判定
    leaver_uid TEXT,        -- 离职方 UID（双方/未判定为空）
    leave_time TEXT,        -- 离职时间（UID 查询系统返回）
    source TEXT,            -- reason_uid / uid_query
    checked_at TEXT
)
"""


def init_table(conn):
    conn.execute(DDL)
    conn.commit()


def _store(conn, team_id, role, uid, leave_time, source):
    conn.execute(
        "INSERT OR REPLACE INTO team_leaver (team_id, leaver_role, leaver_uid, leave_time, source, checked_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (team_id, role, uid or '', leave_time or '', source,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S')))


def _resolve_by_uid_format(reason, sister_uid, sister_uid2, dissolve_date):
    """`NNNNNN 离职` 格式：直接按 UID 匹配；离职时间取解散日期"""
    m = re.match(r'^\s*(\d+)\s*离职', reason or '')
    if not m:
        return None
    uid = m.group(1)
    lt = (dissolve_date or '')[:10]
    if str(sister_uid) == uid:
        return ('姐姐', uid, lt, 'reason_uid')
    if str(sister_uid2) == uid:
        return ('妹妹', uid, lt, 'reason_uid')
    return ('未判定', uid, '', 'reason_uid')  # UID 不在当前团成员里（可能换过妹妹）


def _leave_date(crawler, uid):
    """查询 UID 的最近一次离职日期。返回 (date_str|None, ok)。
    ok=False 表示查询本身失败（未找到/异常由调用方处理），不写记录以便重试。"""
    d = crawler.query(str(uid))
    if not d.get('found'):
        return None, False
    lt = (d.get('last_leave_time') or '').strip()
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', lt)
    return (m.group(0) if m else None), True


def _resolve_by_query(crawler, sister_uid, sister_uid2, dissolve_date):
    """通用文案：查双方离职时间，与解散日期比对（精确优先，容忍 ±1 天）"""
    dd = (dissolve_date or '')[:10]
    leaves = {}
    for role, uid in (('姐姐', sister_uid), ('妹妹', sister_uid2)):
        if not uid:
            continue
        ld, ok = _leave_date(crawler, uid)
        if not ok:
            return None  # 查询失败（UID 未找到等），交由调用方下轮重试
        leaves[role] = (ld, str(uid))
        time.sleep(0.5)  # 两个查询之间缓一下，避免给 UID 系统压力

    def diff_days(ld):
        try:
            return (datetime.strptime(ld, '%Y-%m-%d') - datetime.strptime(dd, '%Y-%m-%d')).days
        except (ValueError, TypeError):
            return None

    exact = [r for r, (ld, _) in leaves.items() if ld and ld == dd]
    near = [r for r, (ld, _) in leaves.items()
            if ld and diff_days(ld) is not None and abs(diff_days(ld)) <= 1]
    for picked in (exact, near):
        if len(picked) == 1:
            r = picked[0]
            return (r, leaves[r][1], leaves[r][0], 'uid_query')
        if len(picked) == 2:
            return ('双方', '', dd, 'uid_query')
    return ('未判定', '', '', 'uid_query')


def refine_leavers(limit=60, delay=0.6, max_heals=3):
    """细分一批未处理的「离职」团。返回统计 dict。
    max_heals：Cookie 过期自动重登次数上限（server1 会话极短，回填大批次需调高）。"""
    conn = get_db()
    init_table(conn)
    candidates = conn.execute("""
        SELECT team_id, sister_uid, sister_uid2, dissolve_reason, dissolve_date
        FROM team_detail
        WHERE rowid IN (SELECT MAX(rowid) FROM team_detail GROUP BY team_id)
          AND dissolve_reason LIKE '%离职%'
          AND dissolve_reason NOT LIKE '姐姐%'
          AND dissolve_reason NOT LIKE '妹妹%'
          AND dissolve_reason NOT LIKE '姐妹双方%'
          AND team_id NOT IN (SELECT team_id FROM team_leaver)
        ORDER BY dissolve_date DESC
        LIMIT ?
    """, (limit,)).fetchall()

    stats = {'total': len(candidates), 'resolved': 0, 'unresolved': 0, 'failed': 0, 'skipped_cookie': 0}
    crawler = None
    healed = 0              # 自动重登次数（上限 max_heals）
    stored_since_heal = 0   # 上次重登以来的处理数：重登后仍 0 进展说明重登无效，停止
    for row in candidates:
        team_id = row['team_id']
        reason = row['dissolve_reason'] or ''
        try:
            res = _resolve_by_uid_format(reason, row['sister_uid'], row['sister_uid2'], row['dissolve_date'])
            if res is None:
                if crawler is None:
                    crawler = UIDCrawler()
                try:
                    res = _resolve_by_query(crawler, row['sister_uid'], row['sister_uid2'], row['dissolve_date'])
                except CookieExpiredError:
                    # server1 会话 TTL 极短（约十几二十个请求）：自动重登（OCR）后续跑
                    if healed >= max_heals or (healed > 0 and stored_since_heal == 0):
                        raise
                    from auto_login import refresh_uid_cookie
                    refresh_uid_cookie()
                    crawler = UIDCrawler()  # 重建会话，加载新 Cookie
                    healed += 1
                    stored_since_heal = 0
                    print(f'[LeaverRefine] Cookie 过期，已自动重登（第 {healed} 次），继续')
                    res = _resolve_by_query(crawler, row['sister_uid'], row['sister_uid2'], row['dissolve_date'])
                time.sleep(delay)
            if res is None:
                stats['failed'] += 1
                print(f'[LeaverRefine] 团 {team_id} 查询失败，下轮重试')
                continue
            role, uid, leave_time, source = res
            _store(conn, team_id, role, uid, leave_time, source)
            stored_since_heal += 1
            if role == '未判定':
                stats['unresolved'] += 1
            else:
                stats['resolved'] += 1
            print(f'[LeaverRefine] 团 {team_id} → {role}（{source}）')
        except CookieExpiredError:
            stats['skipped_cookie'] += 1
            print('[LeaverRefine-WARN] UID 查询 Cookie 已过期，本次停止，更新 Cookie 后下轮继续')
            break
        except Exception as e:
            stats['failed'] += 1
            print(f'[LeaverRefine-WARN] 团 {team_id} 判定异常: {e}')
    conn.commit()
    conn.close()
    return stats


def apply_leaver_reasons():
    """把已判定的细分结果回写到 team_detail（每日抓取后必须执行，覆盖新快照的原始文案）。
    文案附离职时间；team_leaver 缺时间的用解散日期兜底。返回回写的团数。"""
    conn = get_db()
    init_table(conn)
    rows = conn.execute(
        "SELECT team_id, leaver_role, leave_time FROM team_leaver WHERE leaver_role IN ('姐姐', '妹妹', '双方')"
    ).fetchall()
    applied = 0
    for r in rows:
        lt = (r['leave_time'] or '')[:10]
        if not lt:
            drow = conn.execute(
                "SELECT dissolve_date FROM team_detail WHERE team_id = ? "
                "AND dissolve_date IS NOT NULL AND dissolve_date != '' "
                "ORDER BY snapshot_date DESC LIMIT 1", (r['team_id'],)).fetchone()
            lt = (drow['dissolve_date'] or '')[:10] if drow else ''
        text = reason_text(r['leaver_role'], lt)
        if not text:
            continue
        cur = conn.execute(
            "UPDATE team_detail SET dissolve_reason = ? WHERE team_id = ? AND dissolve_reason != ?",
            (text, r['team_id'], text))
        if cur.rowcount:
            applied += 1
    conn.commit()
    conn.close()
    if applied:
        print(f'[LeaverRefine] 已回写 {applied} 个团的离职原因细分')
    return applied


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    max_heals = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f'[LeaverRefine] 开始细分（本批上限 {limit}，重登上限 {max_heals}）...')
    s = refine_leavers(limit=limit, max_heals=max_heals)
    print(f'[LeaverRefine] 本批: {s}')
    apply_leaver_reasons()
