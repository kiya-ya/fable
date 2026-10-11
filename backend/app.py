#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
培训师系统后端（Flask）
功能：培训师/妹妹档案管理、绑定关系管理、UID 数据速查
运行: python -X utf8 backend/app.py
"""
import os
import sys
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, request

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'crawler'))

from db import get_db  # noqa: E402
from uid_crawler import UIDCrawler, CookieExpiredError, CAPTAIN_TYPE_LABELS  # noqa: E402
from trainer_db import init_trainer_db  # noqa: E402

app = Flask(__name__, static_folder='static', static_url_path='')

TRAINER_STATUSES = ('active', 'inactive')
TRAINEE_STATUSES = ('active', 'graduated', 'inactive')

# ────────────────────────────────────────────── 名额与奖励政策

# 等级序列（判定用当周等级）
LEVEL_ORDER = {'': 0, '无': 0, '铜牌': 1, '初级银牌': 2, '银牌': 3, '金牌': 4, '王牌': 5, '大神': 6}
SLOT_CAP = 5                # 总名额上限
REWARD_WINDOW_DAYS = 28     # 奖励有效期：绑定起四周

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


def sync_pending_rewards(conn, trainee_id):
    """为生效绑定生成 pending 奖励（绑定起 28 天内；已存在则跳过）"""
    b = conn.execute(
        '''SELECT b.*, t.uid AS trainee_uid FROM bindings b JOIN trainees t ON t.id=b.trainee_id
           WHERE b.trainee_id=? AND b.unbound_at IS NULL''', (trainee_id,)).fetchone()
    if not b:
        return
    if datetime.utcnow() > _parse_ts(b['bound_at']) + timedelta(days=REWARD_WINDOW_DAYS):
        return
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
           WHERE b.trainer_id = ? AND b.unbound_at IS NULL
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
    """奖励面板：绑定窗口 + 五档奖励状态（未达标/待发放/已发放）"""
    t = conn.execute('SELECT * FROM trainees WHERE id=?', (trainee_id,)).fetchone()
    if not t:
        return None
    b = conn.execute(
        '''SELECT b.*, tr.nickname AS trainer_nickname, tr.uid AS trainer_uid
           FROM bindings b JOIN trainers tr ON tr.id = b.trainer_id
           WHERE b.trainee_id=? AND b.unbound_at IS NULL''', (trainee_id,)).fetchone()
    grants = {g['reward_key']: g for g in conn.execute(
        'SELECT * FROM reward_grants WHERE trainee_uid=? ORDER BY id', (t['uid'],)).fetchall()}

    panel = {
        'trainee': {'id': t['id'], 'uid': t['uid'], 'nickname': t['nickname']},
        'window_days': REWARD_WINDOW_DAYS,
        'binding': None, 'in_window': False, 'window_end': None, 'days_left': None,
        'rewards': [],
    }
    if b:
        window_end = _parse_ts(b['bound_at']) + timedelta(days=REWARD_WINDOW_DAYS)
        days_left = (window_end - datetime.utcnow()).days
        panel.update({
            'binding': {
                'id': b['id'], 'bound_at': b['bound_at'],
                'trainer_nickname': b['trainer_nickname'], 'trainer_uid': b['trainer_uid'],
            },
            'in_window': days_left >= 0,
            'window_end': window_end.strftime('%Y-%m-%d'),
            'days_left': max(days_left, 0),
        })
    for tier in REWARD_TIERS:
        g = grants.get(tier['key'])
        panel['rewards'].append({
            'key': tier['key'], 'label': tier['label'], 'amount': tier['amount'],
            'status': g['status'] if g else 'ineligible',   # granted / pending / ineligible
            'grant_id': g['id'] if g else None,
            'granted_at': g['granted_at'] if g else None,
        })
    return panel


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
    conn = get_db()
    if kw:
        like = f'%{kw}%'
        rows = conn.execute(
            'SELECT * FROM trainers WHERE uid LIKE ? OR nickname LIKE ? ORDER BY id DESC',
            (like, like)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM trainers ORDER BY id DESC').fetchall()
    # 附带当前带的妹妹数与名额（当月等级贡献）
    counts = dict(conn.execute(
        'SELECT trainer_id, COUNT(*) FROM bindings WHERE unbound_at IS NULL GROUP BY trainer_id'
    ).fetchall())
    month = _current_month()
    plus_rows = conn.execute(
        '''SELECT b.trainer_id, m.best_rank FROM bindings b
           JOIN trainees t ON t.id = b.trainee_id
           LEFT JOIN trainee_level_monthly m ON m.trainee_uid = t.uid AND m.month = ?
           WHERE b.unbound_at IS NULL''', (month,)).fetchall()
    extras = {}
    for r in plus_rows:
        extras[r['trainer_id']] = extras.get(r['trainer_id'], 0) + slot_plus(r['best_rank'] or 0)
    conn.close()
    items = rows_to_dicts(rows)
    for it in items:
        it['active_trainee_count'] = counts.get(it['id'], 0)
        it['total_slots'] = min(it['base_slots'] + extras.get(it['id'], 0), SLOT_CAP)
    return ok({'items': items})


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
           WHERE b.trainer_id=? AND b.unbound_at IS NULL
           ORDER BY b.bound_at DESC''', (tid,)).fetchall()
    conn.close()
    return ok({'items': rows_to_dicts(rows)})


# ────────────────────────────────────────────── 妹妹档案

@app.get('/api/trainees')
def list_trainees():
    kw = request.args.get('kw', '').strip()
    status = request.args.get('status', '').strip()
    sql = 'SELECT * FROM trainees WHERE 1=1'
    params = []
    if kw:
        sql += ' AND (uid LIKE ? OR nickname LIKE ?)'
        params += [f'%{kw}%', f'%{kw}%']
    if status:
        sql += ' AND status = ?'
        params.append(status)
    sql += ' ORDER BY id DESC'
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    # 附带当前绑定的培训师
    bound = {r['trainee_id']: r for r in conn.execute(
        '''SELECT b.trainee_id, b.id AS binding_id, tr.id AS trainer_id, tr.nickname AS trainer_nickname, tr.uid AS trainer_uid
           FROM bindings b JOIN trainers tr ON tr.id = b.trainer_id
           WHERE b.unbound_at IS NULL''').fetchall()}
    conn.close()
    items = rows_to_dicts(rows)
    for it in items:
        b = bound.get(it['id'])
        it['trainer_nickname'] = b['trainer_nickname'] if b else None
        it['trainer_uid'] = b['trainer_uid'] if b else None
    return ok({'items': items})


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
        '''SELECT b.id, b.bound_at, b.unbound_at, b.note,
                  tr.id AS trainer_id, tr.uid AS trainer_uid, tr.nickname AS trainer_nickname,
                  te.id AS trainee_id, te.uid AS trainee_uid, te.nickname AS trainee_nickname, te.hall_name
           FROM bindings b
           JOIN trainers tr ON tr.id = b.trainer_id
           JOIN trainees te ON te.id = b.trainee_id
           WHERE b.unbound_at IS {} NULL
           ORDER BY b.id DESC'''.format('' if active else 'NOT')).fetchall()
    conn.close()
    return ok({'items': rows_to_dicts(rows)})


@app.post('/api/bindings')
def create_binding():
    data = request.get_json(force=True)
    trainer_id = data.get('trainer_id')
    trainee_id = data.get('trainee_id')
    note = str(data.get('note', '') or '').strip()
    force = bool(data.get('force'))
    if not trainer_id or not trainee_id:
        return err('trainer_id 和 trainee_id 不能为空')

    conn = get_db()
    try:
        trainer = conn.execute('SELECT id, nickname FROM trainers WHERE id=?', (trainer_id,)).fetchone()
        trainee = conn.execute('SELECT id, nickname FROM trainees WHERE id=?', (trainee_id,)).fetchone()
        if not trainer:
            return err('培训师不存在', 404)
        if not trainee:
            return err('妹妹不存在', 404)

        current = conn.execute(
            '''SELECT b.id, tr.nickname FROM bindings b JOIN trainers tr ON tr.id=b.trainer_id
               WHERE b.trainee_id=? AND b.unbound_at IS NULL''', (trainee_id,)).fetchone()
        if current:
            if current['id'] and not force:
                return jsonify({
                    'ok': False, 'conflict': True,
                    'msg': f"「{trainee['nickname']}」当前已绑定培训师「{current['nickname']}」，确认换绑？",
                }), 409
            conn.execute('UPDATE bindings SET unbound_at=CURRENT_TIMESTAMP WHERE id=?', (current['id'],))

        cur = conn.execute(
            'INSERT INTO bindings (trainer_id, trainee_id, note) VALUES (?, ?, ?)',
            (trainer_id, trainee_id, note))
        conn.commit()
        return ok({'id': cur.lastrowid, 'rebound': bool(current)})
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
           WHERE b.trainer_id=? AND b.unbound_at IS NULL ORDER BY b.bound_at''', (tid,)).fetchall()
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

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
