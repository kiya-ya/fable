#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
培训师系统后端（Flask）
功能：培训师/妹妹档案管理、绑定关系管理、UID 数据速查
运行: python -X utf8 backend/app.py
"""
import os
import sys
import json
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_file

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'crawler'))

from db import get_db  # noqa: E402
from uid_crawler import UIDCrawler, CookieExpiredError, CAPTAIN_TYPE_LABELS  # noqa: E402
from trainer_db import init_trainer_db  # noqa: E402

app = Flask(__name__, static_folder='static', static_url_path='')

TRAINER_STATUSES = ('active', 'inactive')
TRAINEE_STATUSES = ('active', 'inactive')

# ────────────────────────────────────────────── 名额与奖励政策

# 等级序列（判定用当周等级）
LEVEL_ORDER = {'': 0, '无': 0, '铜牌': 1, '初级银牌': 2, '银牌': 3, '金牌': 4, '王牌': 5, '大神': 6}
SLOT_CAP = 5                # 总名额上限
REWARD_WINDOW_WEEKS = 4     # 奖励有效期：绑定次周周一起，整四周

# 奖励档位（金额为单人份，实际发放 ×2，培训师和新人各一）
REWARD_TIERS = [
    {'key': 'task6_bronze', 'label': '周任务≥6次 + 铜牌及以上', 'amount': 12.8, 'min_rank': 1, 'need_tasks': True},
    {'key': 'lv_junior_silver', 'label': '晋升初银', 'amount': 12.8, 'min_rank': 2},
    {'key': 'lv_silver', 'label': '晋升银牌', 'amount': 23.3, 'min_rank': 3},
    {'key': 'lv_gold', 'label': '晋升金牌', 'amount': 52.0, 'min_rank': 4},
    {'key': 'lv_ace', 'label': '晋升王牌', 'amount': 131.4, 'min_rank': 5},
]

# 学员当月等级 → 额外名额：初银+1 / 银牌+1 / 金牌+1（累计，金牌学员一人 +3）
def slot_plus(rank):
    return (1 if rank >= 2 else 0) + (1 if rank >= 3 else 0) + (1 if rank >= 4 else 0)


def level_rank(name):
    return LEVEL_ORDER.get((name or '').strip(), 0)


def _current_month():
    return datetime.now().strftime('%Y-%m')


def record_trainee_query(conn, uid, data):
    """速查成功后落库当月等级记录（best = 当月最高周等级）"""
    if not data.get('found'):
        return
    month = _current_month()
    lvl = (data.get('week_level') or '').strip()
    rank = level_rank(lvl)
    tasks = int(data.get('daily_task_count') or 0)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute(
        'SELECT * FROM trainee_level_monthly WHERE trainee_uid=? AND month=?', (uid, month)).fetchone()
    if row:
        best_lvl = lvl if rank > row['best_rank'] else row['best_level']
        best_rk = max(rank, row['best_rank'])
        conn.execute(
            '''UPDATE trainee_level_monthly
               SET best_level=?, best_rank=?, last_week_level=?, last_daily_task_count=?, last_queried_at=?
               WHERE id=?''', (best_lvl, best_rk, lvl, tasks, now, row['id']))
    else:
        conn.execute(
            '''INSERT INTO trainee_level_monthly
               (trainee_uid, month, best_level, best_rank, last_week_level, last_daily_task_count, last_queried_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''', (uid, month, lvl, rank, lvl, tasks, now))
    conn.commit()


def _parse_ts(s):
    """SQLite CURRENT_TIMESTAMP 存的是 UTC"""
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')


def reward_window(bound_at_str):
    """奖励窗口（本地时间）：绑定次周周一 00:00 起，整四周（到第四周后的周一 00:00 止，不含）"""
    local_bound = _parse_ts(bound_at_str) + timedelta(hours=8)
    days_to_next_monday = (7 - local_bound.weekday()) % 7 or 7
    start = (local_bound + timedelta(days=days_to_next_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(weeks=REWARD_WINDOW_WEEKS)
    return start, end


def reward_window_status(bound_at_str):
    """返回 (start, end, status)，status: not_started / in_window / expired"""
    start, end = reward_window(bound_at_str)
    now = datetime.now()
    if now < start:
        return start, end, 'not_started'
    if now >= end:
        return start, end, 'expired'
    return start, end, 'in_window'


def sync_pending_rewards(conn, trainee_id):
    """为每条生效绑定（培训师/姐妹团均可）生成 pending 奖励（奖励窗口内；已存在则跳过）"""
    bindings = conn.execute(
        '''SELECT b.*, t.uid AS trainee_uid FROM bindings b JOIN trainees t ON t.id=b.trainee_id
           WHERE b.trainee_id=? AND b.unbound_at IS NULL''', (trainee_id,)).fetchall()
    for b in bindings:
        if reward_window_status(b['bound_at'])[2] != 'in_window':
            continue
        rec = conn.execute(
            'SELECT * FROM trainee_level_monthly WHERE trainee_uid=? AND month=?',
            (b['trainee_uid'], _current_month())).fetchone()
        best_rank = rec['best_rank'] if rec else 0
        tasks = rec['last_daily_task_count'] if rec else 0
        for tier in REWARD_TIERS:
            eligible = best_rank >= tier['min_rank']
            if tier.get('need_tasks'):
                eligible = eligible and tasks >= 6
            if eligible:
                conn.execute(
                    '''INSERT OR IGNORE INTO reward_grants
                       (binding_id, trainee_uid, trainer_id, reward_key, reward_label, amount)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (b['id'], b['trainee_uid'], b['trainer_id'], tier['key'], tier['label'], tier['amount']))
    conn.commit()


def build_slots_panel(conn, trainer_id):
    """名额面板：基础名额 + 生效绑定学员当月等级贡献，上限 5"""
    tr = conn.execute('SELECT * FROM trainers WHERE id=?', (trainer_id,)).fetchone()
    if not tr:
        return None
    month = _current_month()
    rows = conn.execute(
        '''SELECT t.uid, t.nickname, b.bound_at,
                  m.best_level, m.best_rank, m.last_queried_at
           FROM bindings b JOIN trainees t ON t.id = b.trainee_id
           LEFT JOIN trainee_level_monthly m ON m.trainee_uid = t.uid AND m.month = ?
           WHERE b.trainer_id = ? AND b.bind_type='trainer' AND b.unbound_at IS NULL
           ORDER BY b.bound_at''', (month, trainer_id)).fetchall()
    trainees = []
    extra = 0
    for r in rows:
        rank = r['best_rank'] or 0
        plus = slot_plus(rank)
        extra += plus
        trainees.append({
            'uid': r['uid'], 'nickname': r['nickname'], 'bound_at': r['bound_at'],
            'best_level': r['best_level'] or '（本月未查询）', 'slot_plus': plus,
            'last_queried_at': r['last_queried_at'],
        })
    base = tr['base_slots']
    total = min(base + extra, SLOT_CAP)
    return {
        'trainer': {'id': tr['id'], 'uid': tr['uid'], 'nickname': tr['nickname']},
        'month': month,
        'base_slots': base, 'extra_slots': extra, 'total_slots': total,
        'used_slots': len(rows), 'over': len(rows) > total,
        'slot_cap': SLOT_CAP,
        'trainees': trainees,
    }


def build_rewards_panel(conn, trainee_id):
    """奖励面板：每条生效绑定（培训师/姐妹团）各一组窗口 + 五档奖励状态"""
    t = conn.execute('SELECT * FROM trainees WHERE id=?', (trainee_id,)).fetchone()
    if not t:
        return None
    bindings = conn.execute(
        '''SELECT b.*, tr.nickname AS side_nickname, tr.uid AS side_uid
           FROM bindings b JOIN trainers tr ON tr.id = b.trainer_id
           WHERE b.trainee_id=? AND b.unbound_at IS NULL
           ORDER BY b.bind_type, b.bound_at''', (trainee_id,)).fetchall()
    grants = conn.execute(
        'SELECT * FROM reward_grants WHERE trainee_uid=? ORDER BY id', (t['uid'],)).fetchall()

    panels = []
    for b in bindings:
        start, end, status = reward_window_status(b['bound_at'])
        bg = {g['reward_key']: g for g in grants if g['binding_id'] == b['id']}
        panels.append({
            'bind_type': b['bind_type'],
            'type_label': '姐妹团三胎' if b['bind_type'] == 'sister' else '培训师',
            'side_label': '姐姐' if b['bind_type'] == 'sister' else '培训师',
            'binding': {
                'id': b['id'], 'bound_at': b['bound_at'],
                'side_nickname': b['side_nickname'], 'side_uid': b['side_uid'],
            },
            'window_status': status,
            'in_window': status == 'in_window',
            'window_start': start.strftime('%Y-%m-%d'),
            'window_end': end.strftime('%Y-%m-%d'),
            'days_left': max((end - datetime.now()).days, 0) if status == 'in_window' else None,
            'rewards': [{
                'key': tier['key'], 'label': tier['label'], 'amount': tier['amount'],
                'status': bg[tier['key']]['status'] if tier['key'] in bg else 'ineligible',
                'grant_id': bg[tier['key']]['id'] if tier['key'] in bg else None,
                'granted_at': bg[tier['key']]['granted_at'] if tier['key'] in bg else None,
            } for tier in REWARD_TIERS],
        })
    return {
        'trainee': {'id': t['id'], 'uid': t['uid'], 'nickname': t['nickname']},
        'window_weeks': REWARD_WINDOW_WEEKS,
        'panels': panels,
    }


# ────────────────────────────────────────────── 工具

def err(msg, code=400):
    return jsonify({'ok': False, 'msg': msg}), code


def ok(data=None):
    payload = {'ok': True}
    if data is not None:
        payload.update(data)
    return jsonify(payload)


# ────────────────────────────────────────────── 首页

@app.get('/')
def index():
    return app.send_static_file('index.html')


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def _page_args():
    """分页参数：page 从 1 开始，page_size 默认 20，上限 100"""
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(max(int(request.args.get('page_size', 20)), 1), 100)
    except (TypeError, ValueError):
        page_size = 20
    return page, page_size


def _validate_person(data, statuses, with_slots=False):
    uid = str(data.get('uid', '')).strip()
    nickname = str(data.get('nickname', '')).strip()
    status = data.get('status', 'active')
    if not uid:
        return None, 'uid 不能为空'
    if not nickname:
        return None, 'nickname 不能为空'
    if status not in statuses:
        return None, f'status 必须是 {" / ".join(statuses)} 之一'
    person = {
        'uid': uid,
        'nickname': nickname,
        'hall_name': str(data.get('hall_name', '') or '').strip(),
        'status': status,
        'note': str(data.get('note', '') or '').strip(),
    }
    if with_slots:
        try:
            base_slots = int(data.get('base_slots', 2))
        except (TypeError, ValueError):
            return None, 'base_slots 必须是整数'
        if not 0 <= base_slots <= SLOT_CAP:
            return None, f'基础名额必须在 0~{SLOT_CAP} 之间'
        person['base_slots'] = base_slots
    return person, None


# ────────────────────────────────────────────── 培训师档案

@app.get('/api/trainers')
def list_trainers():
    kw = request.args.get('kw', '').strip()
    role = request.args.get('role', 'trainer').strip()  # trainer(默认) / sister / all
    page, page_size = _page_args()
    conn = get_db()
    where = 'WHERE 1=1'
    params = []
    if role != 'all':
        where += ' AND role = ?'
        params.append(role)
    if kw:
        where += ' AND (uid LIKE ? OR nickname LIKE ?)'
        params += [f'%{kw}%', f'%{kw}%']
    total = conn.execute(f'SELECT COUNT(*) FROM trainers {where}', params).fetchone()[0]
    rows = conn.execute(
        f'SELECT * FROM trainers {where} ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [page_size, (page - 1) * page_size]).fetchall()
    # 附带当前带的妹妹数与名额（只统计培训师类型绑定；当月等级贡献）
    counts = dict(conn.execute(
        "SELECT trainer_id, COUNT(*) FROM bindings WHERE unbound_at IS NULL AND bind_type='trainer' GROUP BY trainer_id"
    ).fetchall())
    month = _current_month()
    plus_rows = conn.execute(
        '''SELECT b.trainer_id, m.best_rank FROM bindings b
           JOIN trainees t ON t.id = b.trainee_id
           LEFT JOIN trainee_level_monthly m ON m.trainee_uid = t.uid AND m.month = ?
           WHERE b.unbound_at IS NULL AND b.bind_type='trainer' ''', (month,)).fetchall()
    extras = {}
    for r in plus_rows:
        extras[r['trainer_id']] = extras.get(r['trainer_id'], 0) + slot_plus(r['best_rank'] or 0)
    conn.close()
    items = rows_to_dicts(rows)
    for it in items:
        it['active_trainee_count'] = counts.get(it['id'], 0)
        it['total_slots'] = min(it['base_slots'] + extras.get(it['id'], 0), SLOT_CAP)
    return ok({'items': items, 'total': total, 'page': page, 'page_size': page_size})


@app.post('/api/trainers')
def create_trainer():
    person, msg = _validate_person(request.get_json(force=True), TRAINER_STATUSES, with_slots=True)
    if msg:
        return err(msg)
    conn = get_db()
    try:
        cur = conn.execute(
            'INSERT INTO trainers (uid, nickname, hall_name, status, note, base_slots) VALUES (?, ?, ?, ?, ?, ?)',
            (person['uid'], person['nickname'], person['hall_name'], person['status'], person['note'], person['base_slots']))
        conn.commit()
        return ok({'id': cur.lastrowid})
    except Exception as e:
        if 'UNIQUE' in str(e):
            return err(f"UID {person['uid']} 的培训师已存在", 409)
        raise
    finally:
        conn.close()


@app.put('/api/trainers/<int:tid>')
def update_trainer(tid):
    person, msg = _validate_person(request.get_json(force=True), TRAINER_STATUSES, with_slots=True)
    if msg:
        return err(msg)
    conn = get_db()
    try:
        cur = conn.execute(
            'UPDATE trainers SET uid=?, nickname=?, hall_name=?, status=?, note=?, base_slots=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (person['uid'], person['nickname'], person['hall_name'], person['status'], person['note'], person['base_slots'], tid))
        conn.commit()
        if cur.rowcount == 0:
            return err('培训师不存在', 404)
        return ok()
    except Exception as e:
        if 'UNIQUE' in str(e):
            return err(f"UID {person['uid']} 已被其他培训师使用", 409)
        raise
    finally:
        conn.close()


@app.delete('/api/trainers/<int:tid>')
def delete_trainer(tid):
    conn = get_db()
    active = conn.execute(
        'SELECT COUNT(*) FROM bindings WHERE trainer_id=? AND unbound_at IS NULL', (tid,)).fetchone()[0]
    if active:
        conn.close()
        return err(f'该培训师还有 {active} 个生效绑定，请先解绑', 409)
    cur = conn.execute('DELETE FROM trainers WHERE id=?', (tid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return err('培训师不存在', 404)
    return ok()


@app.get('/api/trainers/<int:tid>/trainees')
def trainer_trainees(tid):
    conn = get_db()
    rows = conn.execute(
        '''SELECT t.*, b.id AS binding_id, b.bound_at, b.note AS binding_note
           FROM bindings b JOIN trainees t ON t.id = b.trainee_id
           WHERE b.trainer_id=? AND b.bind_type='trainer' AND b.unbound_at IS NULL
           ORDER BY b.bound_at DESC''', (tid,)).fetchall()
    conn.close()
    return ok({'items': rows_to_dicts(rows)})


# ────────────────────────────────────────────── 妹妹档案

@app.get('/api/trainees')
def list_trainees():
    kw = request.args.get('kw', '').strip()
    status = request.args.get('status', '').strip()
    page, page_size = _page_args()
    where = 'WHERE 1=1'
    params = []
    if kw:
        where += ' AND (uid LIKE ? OR nickname LIKE ?)'
        params += [f'%{kw}%', f'%{kw}%']
    if status:
        where += ' AND status = ?'
        params.append(status)
    conn = get_db()
    total = conn.execute(f'SELECT COUNT(*) FROM trainees {where}', params).fetchone()[0]
    rows = conn.execute(
        f'SELECT * FROM trainees {where} ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [page_size, (page - 1) * page_size]).fetchall()
    # 附带当前绑定（培训师 + 姐妹团姐姐）
    bound_rows = conn.execute(
        '''SELECT b.trainee_id, b.bind_type, tr.nickname AS side_nickname, tr.uid AS side_uid
           FROM bindings b JOIN trainers tr ON tr.id = b.trainer_id
           WHERE b.unbound_at IS NULL''').fetchall()
    conn.close()
    bound = {}
    for r in bound_rows:
        bound.setdefault(r['trainee_id'], {})[r['bind_type']] = r
    items = rows_to_dicts(rows)
    for it in items:
        bs = bound.get(it['id'], {})
        tr_b = bs.get('trainer')
        it['trainer_nickname'] = tr_b['side_nickname'] if tr_b else None
        it['trainer_uid'] = tr_b['side_uid'] if tr_b else None
        st_b = bs.get('sister')
        it['sister_nickname'] = st_b['side_nickname'] if st_b else None
        it['sister_uid'] = st_b['side_uid'] if st_b else None
    return ok({'items': items, 'total': total, 'page': page, 'page_size': page_size})


@app.post('/api/trainees')
def create_trainee():
    person, msg = _validate_person(request.get_json(force=True), TRAINEE_STATUSES)
    if msg:
        return err(msg)
    conn = get_db()
    try:
        cur = conn.execute(
            'INSERT INTO trainees (uid, nickname, hall_name, status, note) VALUES (?, ?, ?, ?, ?)',
            (person['uid'], person['nickname'], person['hall_name'], person['status'], person['note']))
        conn.commit()
        return ok({'id': cur.lastrowid})
    except Exception as e:
        if 'UNIQUE' in str(e):
            return err(f"UID {person['uid']} 的妹妹已存在", 409)
        raise
    finally:
        conn.close()


@app.put('/api/trainees/<int:tid>')
def update_trainee(tid):
    person, msg = _validate_person(request.get_json(force=True), TRAINEE_STATUSES)
    if msg:
        return err(msg)
    conn = get_db()
    try:
        cur = conn.execute(
            'UPDATE trainees SET uid=?, nickname=?, hall_name=?, status=?, note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (person['uid'], person['nickname'], person['hall_name'], person['status'], person['note'], tid))
        conn.commit()
        if cur.rowcount == 0:
            return err('妹妹不存在', 404)
        return ok()
    except Exception as e:
        if 'UNIQUE' in str(e):
            return err(f"UID {person['uid']} 已被其他妹妹使用", 409)
        raise
    finally:
        conn.close()


@app.delete('/api/trainees/<int:tid>')
def delete_trainee(tid):
    conn = get_db()
    active = conn.execute(
        'SELECT COUNT(*) FROM bindings WHERE trainee_id=? AND unbound_at IS NULL', (tid,)).fetchone()[0]
    if active:
        conn.close()
        return err('该妹妹当前有生效绑定，请先解绑', 409)
    cur = conn.execute('DELETE FROM trainees WHERE id=?', (tid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return err('妹妹不存在', 404)
    return ok()


# ────────────────────────────────────────────── 历史数据导入（team_detail 快照）

def _latest_snapshot_trainees(conn):
    snap = conn.execute('SELECT MAX(snapshot_date) FROM team_detail').fetchone()[0]
    if not snap:
        return [], None
    rows = conn.execute(
        '''SELECT sister_uid2 AS uid, sister_nickname2 AS nickname, hall_name,
                  MAX(COALESCE(dissolve_date, '') = '') AS active
           FROM team_detail
           WHERE snapshot_date=? AND sister_uid2 IS NOT NULL
           GROUP BY sister_uid2''', (snap,)).fetchall()
    return rows_to_dicts(rows), snap


@app.get('/api/trainees/import-candidates')
def import_candidates():
    conn = get_db()
    items, snap = _latest_snapshot_trainees(conn)
    existing = {r[0] for r in conn.execute('SELECT uid FROM trainees').fetchall()}
    conn.close()
    for it in items:
        it['uid'] = str(it['uid'])
        it['already'] = it['uid'] in existing
        it['active'] = bool(it['active'])
    items.sort(key=lambda x: (x['already'], not x['active'], x['uid']))
    return ok({'items': items, 'snapshot_date': snap})


@app.post('/api/trainees/import')
def import_trainees():
    uids = [str(u).strip() for u in (request.get_json(force=True).get('uids') or []) if str(u).strip()]
    if not uids:
        return err('uids 不能为空')
    conn = get_db()
    candidates, _ = _latest_snapshot_trainees(conn)
    by_uid = {str(c['uid']): c for c in candidates}
    imported, skipped = 0, []
    for uid in uids:
        c = by_uid.get(uid)
        if not c:
            skipped.append({'uid': uid, 'reason': '快照中不存在'})
            continue
        try:
            conn.execute(
                'INSERT INTO trainees (uid, nickname, hall_name) VALUES (?, ?, ?)',
                (uid, c['nickname'] or uid, c['hall_name'] or ''))
            imported += 1
        except Exception as e:
            if 'UNIQUE' in str(e):
                skipped.append({'uid': uid, 'reason': '已建档'})
            else:
                conn.rollback()
                conn.close()
                raise
    conn.commit()
    conn.close()
    return ok({'imported': imported, 'skipped': skipped})


# ────────────────────────────────────────────── 绑定关系

@app.get('/api/bindings')
def list_bindings():
    active = request.args.get('active', '1') != '0'
    conn = get_db()
    rows = conn.execute(
        '''SELECT b.id, b.bind_type, b.bound_at, b.unbound_at, b.note,
                  tr.id AS trainer_id, tr.uid AS trainer_uid, tr.nickname AS trainer_nickname, tr.role AS side_role,
                  te.id AS trainee_id, te.uid AS trainee_uid, te.nickname AS trainee_nickname, te.hall_name
           FROM bindings b
           JOIN trainers tr ON tr.id = b.trainer_id
           JOIN trainees te ON te.id = b.trainee_id
           WHERE b.unbound_at IS {} NULL
           ORDER BY b.id DESC'''.format('' if active else 'NOT')).fetchall()
    items = rows_to_dicts(rows)
    btype = request.args.get('bind_type', '').strip()
    if btype in BIND_TYPES:
        items = [b for b in items if b['bind_type'] == btype]
    # 每行附奖励窗口信息：结束日期 / 状态 / 剩余周数
    for b in items:
        start, end, status = reward_window_status(b['bound_at'])
        b['window_start'] = start.strftime('%Y-%m-%d')
        b['window_end'] = end.strftime('%Y-%m-%d')
        b['window_status'] = status
        if status == 'in_window':
            b['weeks_left'] = min(max(-(-(end - datetime.now()).days // 7), 0), REWARD_WINDOW_WEEKS)
        elif status == 'not_started':
            b['weeks_left'] = REWARD_WINDOW_WEEKS
        else:
            b['weeks_left'] = 0
    total = len(items)
    page, page_size = _page_args()
    conn.close()
    return ok({'items': items[(page - 1) * page_size: page * page_size],
               'total': total, 'page': page, 'page_size': page_size})


BIND_TYPES = {'trainer': '培训师', 'sister': '姐妹团三胎'}


def _bind_core(conn, trainer_id, trainee_id, note, force, bind_type='trainer'):
    """绑定核心逻辑（调用方负责 commit/rollback）。返回 (payload, http_code)"""
    side_label = BIND_TYPES.get(bind_type)
    if not side_label:
        return {'ok': False, 'msg': 'bind_type 必须是 trainer / sister'}, 400
    trainer = conn.execute('SELECT id, nickname FROM trainers WHERE id=?', (trainer_id,)).fetchone()
    trainee = conn.execute('SELECT id, nickname FROM trainees WHERE id=?', (trainee_id,)).fetchone()
    if not trainer:
        return {'ok': False, 'msg': '左侧人员（培训师/姐姐）不存在'}, 404
    if not trainee:
        return {'ok': False, 'msg': '妹妹不存在'}, 404

    rebound = False
    # 姐妹团三胎：一个姐姐同时只能绑一个妹妹
    if bind_type == 'sister':
        busy = conn.execute(
            '''SELECT b.id, t.nickname FROM bindings b JOIN trainees t ON t.id=b.trainee_id
               WHERE b.trainer_id=? AND b.bind_type='sister' AND b.unbound_at IS NULL''',
            (trainer_id,)).fetchone()
        if busy:
            if not force:
                return {
                    'ok': False, 'conflict': True,
                    'msg': f"姐姐「{trainer['nickname']}」已绑定妹妹「{busy['nickname']}」（三胎只能一对一），确认换绑？",
                }, 409
            conn.execute('UPDATE bindings SET unbound_at=CURRENT_TIMESTAMP WHERE id=?', (busy['id'],))
            rebound = True

    # 同一妹妹同类型最多一条生效绑定（培训师与姐妹团相互独立，可各有一条）
    current = conn.execute(
        '''SELECT b.id, tr.nickname FROM bindings b JOIN trainers tr ON tr.id=b.trainer_id
           WHERE b.trainee_id=? AND b.bind_type=? AND b.unbound_at IS NULL''',
        (trainee_id, bind_type)).fetchone()
    if current:
        if not force:
            return {
                'ok': False, 'conflict': True,
                'msg': f"「{trainee['nickname']}」当前已有{side_label}绑定（{current['nickname']}），确认换绑？",
            }, 409
        conn.execute('UPDATE bindings SET unbound_at=CURRENT_TIMESTAMP WHERE id=?', (current['id'],))
        rebound = True

    cur = conn.execute(
        'INSERT INTO bindings (trainer_id, trainee_id, bind_type, note) VALUES (?, ?, ?, ?)',
        (trainer_id, trainee_id, bind_type, note))
    return {'ok': True, 'id': cur.lastrowid, 'rebound': rebound, 'bind_type': bind_type}, 200


@app.post('/api/bindings')
def create_binding():
    data = request.get_json(force=True)
    trainer_id = data.get('trainer_id')
    trainee_id = data.get('trainee_id')
    note = str(data.get('note', '') or '').strip()
    force = bool(data.get('force'))
    bind_type = data.get('bind_type', 'trainer')
    if not trainer_id or not trainee_id:
        return err('trainer_id 和 trainee_id 不能为空')

    conn = get_db()
    try:
        payload, code = _bind_core(conn, trainer_id, trainee_id, note, force, bind_type)
        if code == 200:
            conn.commit()
        return jsonify(payload), code
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _upsert_person(conn, table, uid, nickname, hall_name, role=None):
    """按 UID 查档案，不存在则用速查回填的信息自动建档。返回 (id, created)"""
    row = conn.execute(f'SELECT id FROM {table} WHERE uid=?', (uid,)).fetchone()
    if row:
        return row['id'], False
    if table == 'trainers':
        cur = conn.execute(
            'INSERT INTO trainers (uid, nickname, hall_name, role) VALUES (?, ?, ?, ?)',
            (uid, nickname or uid, hall_name or '', role or 'trainer'))
    else:
        cur = conn.execute(
            'INSERT INTO trainees (uid, nickname, hall_name) VALUES (?, ?, ?)',
            (uid, nickname or uid, hall_name or ''))
    return cur.lastrowid, True


@app.post('/api/bindings/by-uid')
def create_binding_by_uid():
    """输 UID 直接绑定：未建档的培训师/姐姐/妹妹用前端速查回填的昵称/大厅自动建档"""
    data = request.get_json(force=True)
    bind_type = data.get('bind_type', 'trainer')
    if bind_type not in BIND_TYPES:
        return err('bind_type 必须是 trainer / sister')
    trainer_uid = str(data.get('trainer_uid', '')).strip()
    trainee_uid = str(data.get('trainee_uid', '')).strip()
    note = str(data.get('note', '') or '').strip()
    force = bool(data.get('force'))
    if not trainer_uid or not trainee_uid:
        return err('trainer_uid 和 trainee_uid 不能为空')
    if trainer_uid == trainee_uid:
        return err('两侧不能是同一人')

    conn = get_db()
    try:
        trainer_id, trainer_created = _upsert_person(
            conn, 'trainers', trainer_uid,
            str(data.get('trainer_nickname', '') or '').strip(),
            str(data.get('trainer_hall', '') or '').strip(),
            role='sister' if bind_type == 'sister' else 'trainer')
        trainee_id, trainee_created = _upsert_person(
            conn, 'trainees', trainee_uid,
            str(data.get('trainee_nickname', '') or '').strip(),
            str(data.get('trainee_hall', '') or '').strip())
        payload, code = _bind_core(conn, trainer_id, trainee_id, note, force, bind_type)
        if code == 200:
            payload['trainer_created'] = trainer_created
            payload['trainee_created'] = trainee_created
            conn.commit()
        return jsonify(payload), code
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post('/api/bindings/<int:bid>/unbind')
def unbind(bid):
    conn = get_db()
    cur = conn.execute(
        'UPDATE bindings SET unbound_at=CURRENT_TIMESTAMP WHERE id=? AND unbound_at IS NULL', (bid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return err('绑定不存在或已解绑', 404)
    return ok()


# ────────────────────────────────────────────── 周奖励导出（XLSX）

# 导出金额口径（与参考文件一致）：任务奖固定 12.8（周任务≥6次且当周铜牌及以上）；等级奖按牌子
TASK_REWARD_MIN = 6
TASK_REWARD_AMOUNT = 12.8
LEVEL_REWARD = {'初级银牌': 12.8, '银牌': 23.3, '金牌': 52.0, '王牌': 131.4}


@app.post('/api/export/rewards')
def export_rewards():
    """导出周奖励 XLSX：任务次数/礼物流水 = 所选日期的上一周，牌子 = 所选日期当周"""
    data = request.get_json(force=True)
    bind_type = data.get('bind_type', 'trainer')
    if bind_type not in BIND_TYPES:
        return err('bind_type 必须是 trainer / sister')
    try:
        d = datetime.strptime(str(data.get('date', '')).strip(), '%Y-%m-%d')
    except ValueError:
        return err('date 格式应为 YYYY-MM-DD')

    this_monday = d - timedelta(days=d.weekday())
    last_monday = this_monday - timedelta(days=7)
    fmt = '%Y-%m-%d'
    this_range = (this_monday.strftime(fmt), (this_monday + timedelta(days=6)).strftime(fmt))
    last_range = (last_monday.strftime(fmt), (last_monday + timedelta(days=6)).strftime(fmt))

    conn = get_db()
    all_bindings = conn.execute(
        '''SELECT b.id, b.bound_at, tr.uid AS side_uid, tr.nickname AS side_nickname,
                  te.uid AS trainee_uid, te.nickname AS trainee_nickname, te.hall_name
           FROM bindings b
           JOIN trainers tr ON tr.id = b.trainer_id
           JOIN trainees te ON te.id = b.trainee_id
           WHERE b.bind_type=? AND b.unbound_at IS NULL
           ORDER BY b.bound_at''', (bind_type,)).fetchall()
    conn.close()
    # 只导「在档且奖励窗口未过期」的绑定（窗口 = 绑定次周周一起整四周）
    bindings = [b for b in all_bindings
                if reward_window_status(b['bound_at'])[2] != 'expired']

    crawler = UIDCrawler()
    healed = False
    rows, errors = [], []
    for i, b in enumerate(bindings):
        if i:
            time.sleep(0.6)  # server1 会话 TTL 短，控制频率
        try:
            cur = crawler.query(b['trainee_uid'], 'game', *this_range)
            last = crawler.query(b['trainee_uid'], 'game', *last_range)
        except CookieExpiredError:
            if healed:
                return err(f'导出到第 {i + 1} 行时 Cookie 再次过期，请稍后重试', 401)
            healed = True
            try:
                _heal_uid_cookie()
                crawler = UIDCrawler()
                cur = crawler.query(b['trainee_uid'], 'game', *this_range)
                last = crawler.query(b['trainee_uid'], 'game', *last_range)
            except Exception as e:
                return err(f'自动重登后查询仍失败: {e}', 502)
        except Exception as e:
            errors.append(f"{b['trainee_nickname']}({b['trainee_uid']}): {e}")
            continue

        level = (cur.get('week_level') or '').strip() if cur.get('found') else ''
        tasks = int(last.get('daily_task_count') or 0) if last.get('found') else 0
        revenue = float(last.get('week_revenue') or 0) if last.get('found') else 0
        hall = (cur.get('schedule_hall') or cur.get('auth_hall')
                or last.get('schedule_hall') or last.get('auth_hall') or b['hall_name'] or '')
        task_reward = TASK_REWARD_AMOUNT if (tasks >= TASK_REWARD_MIN and level_rank(level) >= 1) else '无'
        level_reward = LEVEL_REWARD.get(level, '无')
        rows.append([
            int(b['side_uid']) if str(b['side_uid']).isdigit() else b['side_uid'],
            b['side_nickname'],
            int(b['trainee_uid']) if str(b['trainee_uid']).isdigit() else b['trainee_uid'],
            b['trainee_nickname'], hall, tasks, task_reward, revenue, level, level_reward,
        ])

    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    side = '姐姐' if bind_type == 'sister' else '培训师'
    wb = Workbook()
    ws = wb.active
    ws.title = 'Sheet1'
    ws.append([])  # 与参考文件一致：前两行留空，表头在第 3 行
    ws.append([])
    ws.append([f'{side}UID', f'{side}昵称', '妹妹UID', '妹妹昵称', '所属大厅',
               '完成任务次数', '奖励', '礼物流水', '牌子', '奖励'])
    ws.append([])
    for row in rows:
        ws.append(row)
    widths = [15.5, 21.8, 14, 17.2, 27.5, 13.3, 9, 13.3, 12, 9]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = w

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"{d.strftime('%Y%m%d')}{'三胎' if bind_type == 'sister' else '培训师'}奖励.xlsx"
    resp = send_file(buf, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if errors:
        resp.headers['X-Export-Errors'] = '; '.join(errors)[:500]
    return resp


# ────────────────────────────────────────────── 名额与奖励

def _heal_uid_cookie():
    """Cookie 过期时自动 OCR 重登（ddddocr 首次 import 较慢）"""
    import auto_login
    auto_login.refresh_uid_cookie()


@app.get('/api/trainers/<int:tid>/slots')
def trainer_slots(tid):
    conn = get_db()
    panel = build_slots_panel(conn, tid)
    conn.close()
    if not panel:
        return err('培训师不存在', 404)
    return ok({'slots': panel})


@app.post('/api/trainers/<int:tid>/refresh-trainees')
def refresh_trainees(tid):
    """逐个实时查询该培训师生效绑定的学员，刷新当月等级并重新判定奖励"""
    conn = get_db()
    tr = conn.execute('SELECT id FROM trainers WHERE id=?', (tid,)).fetchone()
    if not tr:
        conn.close()
        return err('培训师不存在', 404)
    bindings = conn.execute(
        '''SELECT b.trainee_id, t.uid, t.nickname FROM bindings b JOIN trainees t ON t.id=b.trainee_id
           WHERE b.trainer_id=? AND b.bind_type='trainer' AND b.unbound_at IS NULL ORDER BY b.bound_at''', (tid,)).fetchall()
    conn.close()

    crawler = UIDCrawler()
    healed = False
    queried, errors = [], []
    for i, b in enumerate(bindings):
        if i:
            time.sleep(0.6)  # server1 会话 TTL 短，控制频率
        try:
            r = crawler.query(b['uid'], 'game')
        except CookieExpiredError as e:
            if healed:
                return err(f'已刷新 {len(queried)}/{len(bindings)} 人时 Cookie 再次过期: {e}', 401)
            healed = True
            try:
                _heal_uid_cookie()
                crawler = UIDCrawler()
                r = crawler.query(b['uid'], 'game')
            except CookieExpiredError as e2:
                return err(f'自动重登后 Cookie 仍无效: {e2}', 401)
            except Exception as e2:
                return err(f'自动重登失败: {e2}', 502)
        except Exception as e:
            errors.append({'uid': b['uid'], 'nickname': b['nickname'], 'msg': str(e)})
            continue
        conn = get_db()
        record_trainee_query(conn, b['uid'], r)
        if r.get('found'):
            sync_pending_rewards(conn, b['trainee_id'])
            queried.append({'uid': b['uid'], 'nickname': b['nickname'], 'week_level': r.get('week_level', '')})
        else:
            errors.append({'uid': b['uid'], 'nickname': b['nickname'], 'msg': r.get('msg', '未查到数据')})
        conn.close()

    conn = get_db()
    panel = build_slots_panel(conn, tid)
    conn.close()
    return ok({'slots': panel, 'queried': queried, 'errors': errors})


@app.get('/api/trainees/<int:tid>/rewards')
def trainee_rewards(tid):
    conn = get_db()
    sync_pending_rewards(conn, tid)  # 纯本地按月度记录重算，幂等
    panel = build_rewards_panel(conn, tid)
    conn.close()
    if not panel:
        return err('妹妹不存在', 404)
    return ok({'rewards_panel': panel})


@app.post('/api/rewards/<int:rid>/grant')
def grant_reward(rid):
    conn = get_db()
    cur = conn.execute(
        "UPDATE reward_grants SET status='granted', granted_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
        (rid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return err('奖励记录不存在或已发放', 404)
    return ok()


@app.post('/api/rewards/<int:rid>/revoke')
def revoke_reward(rid):
    conn = get_db()
    cur = conn.execute(
        "UPDATE reward_grants SET status='pending', granted_at=NULL WHERE id=? AND status='granted'", (rid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return err('奖励记录不存在或未发放', 404)
    return ok()


# ────────────────────────────────────────────── UID 速查

@app.get('/api/uid-query/types')
def uid_query_types():
    return ok({'items': [{'key': k, 'label': v} for k, v in CAPTAIN_TYPE_LABELS.items()]})


@app.post('/api/uid-query')
def uid_query():
    data = request.get_json(force=True)
    uid = str(data.get('uid', '')).strip()
    captain_type = data.get('captain_type', 'game')
    if not uid:
        return err('uid 不能为空')
    if captain_type not in CAPTAIN_TYPE_LABELS:
        return err(f"captain_type 必须是 {' / '.join(CAPTAIN_TYPE_LABELS)} 之一")
    try:
        result = UIDCrawler().query_with_compare(uid, captain_type)
    except CookieExpiredError:
        try:
            _heal_uid_cookie()
            result = UIDCrawler().query_with_compare(uid, captain_type)
        except CookieExpiredError as e:
            return err(str(e), 401)
        except Exception as e:
            return err(f'自动重登后查询仍失败: {e}', 502)
    except Exception as e:
        return err(f'查询失败: {e}', 502)

    payload = {'result': result}
    week_data = result.get('this_week', {}).get('data', {})
    conn = get_db()
    try:
        tr = conn.execute('SELECT id FROM trainers WHERE uid=?', (uid,)).fetchone()
        if tr:
            payload['slots'] = build_slots_panel(conn, tr['id'])
        te = conn.execute('SELECT id FROM trainees WHERE uid=?', (uid,)).fetchone()
        if te:
            if week_data.get('found'):
                record_trainee_query(conn, uid, week_data)
                sync_pending_rewards(conn, te['id'])
            payload['rewards_panel'] = build_rewards_panel(conn, te['id'])
    finally:
        conn.close()
    return ok(payload)


@app.get('/api/uid-lookup')
def uid_lookup():
    """轻量本周单查，取昵称/大厅/等级，用于档案表单自动回填"""
    uid = request.args.get('uid', '').strip()
    captain_type = request.args.get('captain_type', 'game')
    if not uid:
        return err('uid 不能为空')
    try:
        r = UIDCrawler().query(uid, captain_type)
    except CookieExpiredError:
        try:
            _heal_uid_cookie()
            r = UIDCrawler().query(uid, captain_type)
        except CookieExpiredError as e:
            return err(str(e), 401)
        except Exception as e:
            return err(f'自动重登后查询仍失败: {e}', 502)
    except Exception as e:
        return err(f'查询失败: {e}', 502)
    if not r.get('found'):
        return ok({'found': False, 'msg': r.get('msg', '未找到该 UID')})
    return ok({'found': True, 'info': {
        'uid': uid,
        'nickname': r.get('nickname', ''),
        'hall_name': r.get('schedule_hall', '') or r.get('auth_hall', ''),
        'week_level': r.get('week_level', ''),
    }})


@app.post('/api/admin/refresh-all-trainees')
def refresh_all_trainees_api():
    """手动触发：刷新全部生效绑定学员的当周等级（名额/奖励判定用）"""
    queried, errors = refresh_all_bound_trainees()
    return ok({'queried': len(queried), 'errors': errors})


# ────────────────────────────────────────────── 每周自动刷新（周一统计用）

WEEKLY_REFRESH_DAY = 0       # 周一
WEEKLY_REFRESH_HOUR = 9      # 09:00 后执行
WEEKLY_REFRESH_STATE = os.path.join(PROJECT_ROOT, 'data', 'weekly_refresh_status.json')


def refresh_all_bound_trainees():
    """逐个实时查询所有生效绑定的学员（两类绑定都刷），落库当月等级并重算奖励"""
    conn = get_db()
    rows = conn.execute(
        '''SELECT DISTINCT t.id AS trainee_id, t.uid, t.nickname
           FROM bindings b JOIN trainees t ON t.id = b.trainee_id
           WHERE b.unbound_at IS NULL ORDER BY t.uid''').fetchall()
    conn.close()

    crawler = UIDCrawler()
    healed = False
    queried, errors = [], []
    for i, b in enumerate(rows):
        if i:
            time.sleep(0.6)  # server1 会话 TTL 短，控制频率
        try:
            r = crawler.query(b['uid'], 'game')
        except CookieExpiredError:
            if healed:
                errors.append({'uid': b['uid'], 'msg': 'Cookie 再次过期，中止'})
                break
            healed = True
            try:
                _heal_uid_cookie()
                crawler = UIDCrawler()
                r = crawler.query(b['uid'], 'game')
            except Exception as e:
                errors.append({'uid': b['uid'], 'msg': f'自动重登失败: {e}'})
                break
        except Exception as e:
            errors.append({'uid': b['uid'], 'nickname': b['nickname'], 'msg': str(e)})
            continue
        conn = get_db()
        record_trainee_query(conn, b['uid'], r)
        if r.get('found'):
            sync_pending_rewards(conn, b['trainee_id'])
            queried.append({'uid': b['uid'], 'nickname': b['nickname'], 'week_level': r.get('week_level', '')})
        else:
            errors.append({'uid': b['uid'], 'nickname': b['nickname'], 'msg': r.get('msg', '未查到数据')})
        conn.close()
    return queried, errors


def _weekly_refresh_loop():
    """每周一 09:00 后自动刷新全部生效绑定学员（每周只跑一次，状态落盘防重启重复）"""
    while True:
        try:
            now = datetime.now()
            if now.weekday() == WEEKLY_REFRESH_DAY and now.hour >= WEEKLY_REFRESH_HOUR:
                week_key = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
                state = {}
                try:
                    with open(WEEKLY_REFRESH_STATE, 'r', encoding='utf-8') as f:
                        state = json.load(f)
                except Exception:
                    pass
                if state.get('last_week') != week_key:
                    print(f'[WeeklyRefresh] 开始本周({week_key})学员刷新…', flush=True)
                    queried, errors = refresh_all_bound_trainees()
                    with open(WEEKLY_REFRESH_STATE, 'w', encoding='utf-8') as f:
                        json.dump({'last_week': week_key, 'ran_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                                   'queried': len(queried), 'errors': len(errors)}, f, ensure_ascii=False)
                    print(f'[WeeklyRefresh] 完成: {len(queried)} 人, 失败 {len(errors)}', flush=True)
        except Exception as e:
            print(f'[WeeklyRefresh-ERROR] {e}', flush=True)
        time.sleep(1800)


# ────────────────────────────────────────────── Cookie 保活后台线程

def _keepalive_loop():
    time.sleep(60)
    while True:
        try:
            import cookie_keepalive
            status = cookie_keepalive.run_keepalive()
            print(f'[Keepalive] {status}', flush=True)
        except Exception as e:
            print(f'[Keepalive-ERROR] {e}', flush=True)
        time.sleep(1800)


# ────────────────────────────────────────────── 启动

init_trainer_db()
threading.Thread(target=_keepalive_loop, daemon=True).start()
threading.Thread(target=_weekly_refresh_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(
        host=os.environ.get('FLASK_HOST', '127.0.0.1'),
        port=int(os.environ.get('FLASK_PORT', '5000')),
        debug=False,
    )
