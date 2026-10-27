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
import re
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'crawler'))

from db import get_db  # noqa: E402
from uid_crawler import UIDCrawler, CookieExpiredError, CAPTAIN_TYPE_LABELS  # noqa: E402
from trainer_db import init_trainer_db  # noqa: E402

app = Flask(__name__, static_folder='static', static_url_path='')

# 登录态：Flask session（密钥持久化在 data/，重启不失效）
def _load_secret_key():
    path = os.path.join(PROJECT_ROOT, 'data', 'flask_secret.txt')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        import secrets
        key = secrets.token_hex(32)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(key)
        return key

app.secret_key = _load_secret_key()


def _load_admin_config():
    """管理员账号从 data/admin_config.json 读取（gitignore，不进入代码库）"""
    path = os.path.join(PROJECT_ROOT, 'data', 'admin_config.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get('username', 'admin'), cfg.get('password', '112233')
    except Exception:
        return 'admin', '112233'


ADMIN_USER, ADMIN_PASSWORD = _load_admin_config()
PORTAL_CODE_TTL = 300  # 用户端验证码有效期（秒）

PUBLIC_PATHS = {'/login', '/portal', '/api/login', '/api/portal/login', '/api/portal/captcha',
                '/app.js', '/style.css', '/brand.css', '/portal.js', '/shares.js', '/favicon.ico', '/logo.jpg',
                '/wutong.png', '/ludeng.png', '/api/client-config'}


# 用户端登录态也允许访问的只读接口（自助绑定需要查妹妹信息）
PORTAL_ALLOWED_APIS = {'/api/uid-lookup'}


@app.get('/api/client-config')
def client_config():
    """前端公共配置：考试系统地址等（改 data/client_config.json 即可，无需改代码）"""
    default = {'exam_url': 'http://192.168.100.117:5001'}
    try:
        with open('data/client_config.json', encoding='utf-8') as f:
            default.update(json.load(f))
    except Exception:
        pass
    return jsonify(default)


@app.before_request
def _auth_guard():
    path = request.path
    if path in PUBLIC_PATHS or path.startswith('/portal/') or path.startswith('/api/portal/'):
        return None
    if session.get('admin'):
        return None
    if session.get('portal_trainer_id') and path in PORTAL_ALLOWED_APIS:
        return None
    if path.startswith('/api/'):
        return jsonify({'ok': False, 'msg': '未登录或登录已过期'}, ), 401
    return app.send_static_file('login.html')


# ────────────────────────────────────────────── 管理员登录

@app.get('/login')
def login_page():
    return app.send_static_file('login.html')


@app.post('/api/login')
def admin_login():
    data = request.get_json(force=True)
    if data.get('username') == ADMIN_USER and data.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return ok()
    return err('账号或密码错误', 401)


@app.post('/api/logout')
def admin_logout():
    session.pop('admin', None)
    return ok()


# ────────────────────────────────────────────── 用户端登录（UID + 5位验证码 + 培训师校验）

@app.get('/portal')
def portal_page():
    return app.send_static_file('portal.html')


def _new_portal_code():
    import random
    import string
    code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    session['portal_code'] = code
    session['portal_code_at'] = time.time()
    return code


@app.get('/api/portal/captcha')
def portal_captcha():
    return ok({'code': _new_portal_code()})


@app.post('/api/portal/login')
def portal_login():
    data = request.get_json(force=True)
    # 每次登录尝试先清除旧登录态，防止失败后沿用上一个身份
    session.pop('portal_uid', None)
    session.pop('portal_trainer_id', None)
    session.pop('portal_preview', None)
    uid = str(data.get('uid', '')).strip()
    password = str(data.get('password', ''))
    if not uid:
        return err('UID 不能为空')
    if not password:
        return err('请输入密码')
    conn = get_db()
    tr = conn.execute("SELECT * FROM trainers WHERE uid=? AND role='trainer'", (uid,)).fetchone()
    conn.close()
    if not tr:
        return err('该 UID 不在培训师名单中，不能进入系统', 403)
    if not tr['password_hash']:
        # 初始密码 = UID 后 5 位（登录后请修改密码）
        if password != uid[-5:]:
            return err('初始密码为 UID 后 5 位，请输入正确的初始密码', 401)
    elif not check_password_hash(tr['password_hash'], password):
        return err('密码错误', 401)
    session.pop('portal_code', None)
    session['portal_uid'] = uid
    session['portal_trainer_id'] = tr['id']
    return ok({'uid': uid, 'nickname': tr['nickname']})


@app.post('/api/portal/logout')
def portal_logout():
    session.pop('portal_uid', None)
    session.pop('portal_trainer_id', None)
    session.pop('portal_preview', None)
    return ok()


@app.post('/api/admin/preview-portal')
def preview_portal():
    """管理员以指定培训师身份预览用户端（不改变该培训师的任何数据）"""
    data = request.get_json(force=True)
    try:
        tid = int(data.get('trainer_id'))
    except (TypeError, ValueError):
        return err('trainer_id 无效')
    conn = get_db()
    tr = conn.execute("SELECT * FROM trainers WHERE id=? AND role='trainer'", (tid,)).fetchone()
    conn.close()
    if not tr:
        return err('培训师不存在', 404)
    session['portal_uid'] = tr['uid']
    session['portal_trainer_id'] = tr['id']
    session['portal_preview'] = True
    log_operation('admin', None, 'preview', 'trainer', tr['uid'], None, '管理员预览用户端')
    return ok({'uid': tr['uid'], 'nickname': tr['nickname']})


def _portal_trainer():
    tid = session.get('portal_trainer_id')
    if not tid:
        return None
    conn = get_db()
    tr = conn.execute("SELECT * FROM trainers WHERE id=? AND role='trainer'", (tid,)).fetchone()
    conn.close()
    return tr


@app.post('/api/trainers/<int:tid>/set-password')
def set_trainer_password(tid):
    """管理员为培训师设置/重置密码（只写哈希，不显示旧密码）"""
    data = request.get_json(force=True)
    password = str(data.get('password', ''))
    if len(password) < 6:
        return err('密码至少 6 位')
    conn = get_db()
    cur = conn.execute('UPDATE trainers SET password_hash=? WHERE id=?',
                       (generate_password_hash(password), tid))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return err('培训师不存在', 404)
    return ok()


@app.post('/api/portal/change-password')
def portal_change_password():
    """用户端修改密码：校验旧密码后更新哈希"""
    tr = _portal_trainer()
    if not tr:
        return err('未登录', 401)
    data = request.get_json(force=True)
    old = str(data.get('old_password', ''))
    new = str(data.get('new_password', ''))
    if len(new) < 6:
        return err('新密码至少 6 位')
    # 无哈希（初始密码 = UID 后 5 位）时按初始密码校验，避免 check_password_hash(None) 抛异常
    if tr['password_hash']:
        if not check_password_hash(tr['password_hash'], old):
            return err('原密码错误', 401)
    elif old != tr['uid'][-5:]:
        return err('原密码错误（初始密码为 UID 后 5 位）', 401)
    conn = get_db()
    conn.execute('UPDATE trainers SET password_hash=? WHERE id=?',
                 (generate_password_hash(new), tr['id']))
    conn.commit()
    conn.close()
    return ok()


@app.get('/api/portal/me')
def portal_me():
    tr = _portal_trainer()
    if not tr:
        return err('未登录', 401)
    conn = get_db()
    panel = build_slots_panel(conn, tr['id'])
    conn.close()
    return ok({'trainer': {'uid': tr['uid'], 'nickname': tr['nickname'], 'hall_name': tr['hall_name']},
               'slots': panel, 'preview': bool(session.get('portal_preview'))})


@app.post('/api/portal/bind')
def portal_bind():
    """用户自助绑定：培训师 UID 固定为登录者，只需输入妹妹 UID"""
    tr = _portal_trainer()
    if not tr:
        return err('未登录', 401)
    data = request.get_json(force=True)
    trainee_uid = str(data.get('trainee_uid', '')).strip()
    note = str(data.get('note', '') or '').strip()
    if not trainee_uid:
        return err('妹妹 UID 不能为空')
    if trainee_uid == tr['uid']:
        return err('不能绑定自己')

    allowed, gate_msg, gate_warn = _protection_gate(trainee_uid)
    if not allowed:
        return jsonify({'ok': False, 'msg': gate_msg, 'gate': True}), 422

    conn = get_db()
    try:
        ok2, msg2, _, _, _ = live_sister_conflict(conn, trainee_uid, tr['uid'])
        if not ok2:
            conn.close()
            return jsonify({'ok': False, 'msg': msg2, 'gate': True, 'conflict_sister': True}), 409
        trainee_id, trainee_created = _upsert_person(
            conn, 'trainees', trainee_uid,
            str(data.get('trainee_nickname', '') or '').strip(),
            str(data.get('trainee_hall', '') or '').strip())
        payload, code = _bind_core(conn, tr['id'], trainee_id, note, False, 'trainer')
        if code == 200:
            payload['trainee_created'] = trainee_created
            if gate_msg:
                payload['gate_msg'] = gate_msg
                payload['gate_warn'] = gate_warn
            conn.commit()
            log_operation('portal', tr['uid'], 'bind', 'trainer', tr['uid'], trainee_uid, '用户自助绑定')
        return jsonify(payload), code
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


TRAINER_STATUSES = ('active', 'inactive')
TRAINEE_STATUSES = ('active', 'inactive')

# 长查询任务串行，防止互踢 server1 会话 / SQLite 写冲突
QUERY_LOCK = threading.Lock()


def serialized_query(fn):
    """长查询任务串行执行装饰器"""
    import functools
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with QUERY_LOCK:
            return fn(*args, **kwargs)
    return wrapper

@app.post('/api/portal/refresh')
def portal_refresh():
    """用户端刷新自己学员的数据"""
    tr = _portal_trainer()
    if not tr:
        return err('未登录', 401)
    return refresh_trainees(tr['id'])


@app.get('/api/portal/trainee-data')
@serialized_query
def portal_trainee_data():
    """查看自己某个妹妹的本周/上周数据（等级/流水/任务/排档）"""
    tr = _portal_trainer()
    if not tr:
        return err('未登录', 401)
    uid = request.args.get('uid', '').strip()
    if not uid:
        return err('uid 不能为空')
    conn = get_db()
    owned = conn.execute(
        'SELECT id FROM bindings WHERE trainer_id=? AND unbound_at IS NULL AND trainee_id=(SELECT id FROM trainees WHERE uid=?)',
        (tr['id'], uid)).fetchone()
    conn.close()
    if not owned:
        return err('只能查看自己绑定的妹妹', 403)
    try:
        result = UIDCrawler().query_with_compare(uid, 'game')
    except CookieExpiredError:
        try:
            _heal_uid_cookie()
            result = UIDCrawler().query_with_compare(uid, 'game')
        except CookieExpiredError as e:
            return err(str(e), 401)
        except Exception as e:
            return err(f'查询失败: {e}', 502)
    except Exception as e:
        return err(f'查询失败: {e}', 502)
    return ok({'result': result})


@app.post('/api/portal/unbind')
def portal_unbind():
    """用户自行解散自己的绑定（名额贡献随绑定结束自动减除）"""
    tr = _portal_trainer()
    if not tr:
        return err('未登录', 401)
    data = request.get_json(force=True)
    bid = data.get('binding_id')
    conn = get_db()
    b = conn.execute(
        'SELECT * FROM bindings WHERE id=? AND trainer_id=? AND unbound_at IS NULL',
        (bid, tr['id'])).fetchone()
    if not b:
        conn.close()
        return err('绑定不存在或不属于当前登录培训师', 403)
    note = ((b['note'] or '') + ' [用户自行解散]').strip()
    conn.execute('UPDATE bindings SET unbound_at=CURRENT_TIMESTAMP, note=? WHERE id=?', (note, bid))
    conn.commit()
    trainee_uid = conn.execute('SELECT uid FROM trainees WHERE id=?', (b['trainee_id'],)).fetchone()[0]
    conn.close()
    log_operation('portal', tr['uid'], 'unbind', b['bind_type'], tr['uid'], trainee_uid, '用户自行解散')
    return ok()


@app.get('/api/portal/granted-rewards')
def portal_granted_rewards():
    """用户端「已发放奖励」：当前培训师所有已发放记录（按发放时间倒序）"""
    tr = _portal_trainer()
    if not tr:
        return err('未登录', 401)
    conn = get_db()
    rows = conn.execute(
        '''SELECT g.reward_label, g.amount, g.granted_at,
                  te.uid AS trainee_uid, te.nickname AS trainee_nickname, te.hall_name,
                  b.bind_type
           FROM reward_grants g
           JOIN bindings b ON b.id = g.binding_id
           JOIN trainees te ON te.id = b.trainee_id
           WHERE g.trainer_id = ? AND g.status = 'granted'
           ORDER BY g.granted_at DESC, g.id DESC LIMIT 100''', (tr['id'],)).fetchall()
    conn.close()
    return ok({'items': rows_to_dicts(rows)})


def _refresh_trainer_info(conn, crawler, uid):
    """用 UID 查询同步培训师昵称/大厅。返回是否同步到有效值"""
    r = crawler.query(uid, 'game')
    if not r.get('found'):
        return False
    nick = (r.get('nickname') or '').strip()
    hall = (r.get('schedule_hall') or r.get('auth_hall') or '').strip()
    if hall == '-':
        hall = ''
    if not nick and not hall:
        return False
    conn.execute(
        """UPDATE trainers SET nickname=COALESCE(NULLIF(?, ''), nickname),
           hall_name=COALESCE(NULLIF(?, ''), hall_name), updated_at=CURRENT_TIMESTAMP WHERE uid=?""",
        (nick, hall, uid))
    conn.commit()
    return True


@app.post('/api/trainers/<int:tid>/refresh')
def refresh_trainer(tid):
    """刷新单个培训师的昵称/大厅（解决批量导入后昵称未同步）"""
    conn = get_db()
    tr = conn.execute("SELECT * FROM trainers WHERE id=? AND role='trainer'", (tid,)).fetchone()
    if not tr:
        conn.close()
        return err('培训师不存在', 404)
    try:
        updated = _refresh_trainer_info(conn, UIDCrawler(), tr['uid'])
    except CookieExpiredError:
        try:
            _heal_uid_cookie()
            updated = _refresh_trainer_info(conn, UIDCrawler(), tr['uid'])
        except Exception as e:
            conn.close()
            return err(f'刷新失败: {e}', 502)
    except Exception as e:
        conn.close()
        return err(f'刷新失败: {e}', 502)
    new = conn.execute('SELECT uid, nickname, hall_name FROM trainers WHERE id=?', (tid,)).fetchone()
    conn.close()
    return ok({'updated': updated, 'info': dict(new)})


@app.post('/api/trainers/refresh-all')
def refresh_all_trainers_info():
    """批量补全培训师信息：只处理昵称为 UID 的记录（即批量导入未同步的）"""
    conn = get_db()
    uids = [r['uid'] for r in conn.execute(
        "SELECT uid FROM trainers WHERE role='trainer' AND nickname = uid").fetchall()]
    conn.close()
    if not uids:
        return ok({'updated': 0, 'total': 0})
    crawler = UIDCrawler()
    updated, failed = 0, 0
    for i, uid in enumerate(uids):
        if i:
            time.sleep(0.6)
        try:
            if _refresh_trainer_info(get_db(), crawler, uid):
                updated += 1
        except CookieExpiredError:
            try:
                _heal_uid_cookie()
                crawler = UIDCrawler()
            except Exception:
                failed += 1
                break
        except Exception:
            failed += 1
            continue
    return ok({'updated': updated, 'total': len(uids), 'failed': failed})


@app.post('/api/trainers/<int:tid>/reset-password')
def reset_trainer_password(tid):
    """管理员重置密码：生成一次性随机密码并返回一次（只显示一次）"""
    import secrets
    import string
    conn = get_db()
    tr = conn.execute("SELECT id FROM trainers WHERE id=? AND role='trainer'", (tid,)).fetchone()
    if not tr:
        conn.close()
        return err('培训师不存在', 404)
    alphabet = string.ascii_letters + string.digits
    new_pwd = ''.join(secrets.choice(alphabet) for _ in range(8))
    conn.execute('UPDATE trainers SET password_hash=? WHERE id=?',
                 (generate_password_hash(new_pwd), tid))
    conn.commit()
    conn.close()
    return ok({'password': new_pwd})


# ────────────────────────────────────────────── 操作日志与查询串行锁

def log_operation(actor_type, actor_uid, action, bind_type, trainer_uid, trainee_uid, detail=''):
    conn = get_db()
    conn.execute(
        'INSERT INTO operation_log (actor_type, actor_uid, action, bind_type, trainer_uid, trainee_uid, detail) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (actor_type, actor_uid, action, bind_type, trainer_uid, trainee_uid, detail))
    conn.commit()
    conn.close()


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


def _last_month():
    first = datetime.now().replace(day=1)
    return (first - timedelta(days=1)).strftime('%Y-%m')


def _last_week_range():
    """上周（周一~周日）日期范围"""
    this_monday = datetime.now() - timedelta(days=datetime.now().weekday())
    last_monday = this_monday - timedelta(days=7)
    fmt = '%Y-%m-%d'
    return last_monday.strftime(fmt), (last_monday + timedelta(days=6)).strftime(fmt)


def get_effective_levels(conn, uids):
    """名额用有效等级：当月有记录用当月最高；当月无记录（月初真空期）用上月最高兜底。
    返回 {uid: {'best_level', 'best_rank', 'last_queried_at', 'from_last_month'}}"""
    if not uids:
        return {}
    month, last = _current_month(), _last_month()
    marks = ','.join('?' * len(uids))
    rows = conn.execute(
        f'''SELECT trainee_uid, month, best_level_active, best_rank_active, last_queried_at
            FROM trainee_level_monthly WHERE trainee_uid IN ({marks}) AND month IN (?, ?)''',
        (*uids, month, last)).fetchall()
    by_uid = {}
    for r in rows:
        cur = by_uid.get(r['trainee_uid'], {})
        if r['month'] == month:
            cur['this'] = r
        else:
            cur['last'] = r
        by_uid[r['trainee_uid']] = cur
    out = {}
    for uid in uids:
        cur = by_uid.get(uid, {})
        rec = cur.get('this') or cur.get('last')
        if rec:
            out[uid] = {
                # 名额贡献用「排档周最高等级」（当周排档天数>0 才计入）
                'best_level': rec['best_level_active'] or '',
                'best_rank': rec['best_rank_active'] or 0,
                'last_queried_at': rec['last_queried_at'],
                'from_last_month': 'this' not in cur,
            }
    return out


def judge_retained(data):
    """留存判定：排档所属大厅 + 当周队长等级 均为空 → 未留存（可判团队解散）
    （权限所属大厅有滞后，不参与判定）空值口径：None / '' / '-'"""
    if not data.get('found'):
        return None
    def empty(v):
        return v is None or str(v).strip() in ('', '-')
    return not (empty(data.get('schedule_hall')) and empty(data.get('week_level')))


def check_sister_conflict(conn, trainee_uid, trainer_uid):
    """姐姐冲突检查：该妹妹在最新姐妹团快照里若绑定了其他姐姐（不同 UID），则拒绝绑定。
    返回 (allowed, msg, sister_uid, sister_nickname, snapshot_date)"""
    snap = conn.execute('SELECT MAX(snapshot_date) FROM team_detail').fetchone()[0]
    if not snap:
        return True, '姐妹团快照为空，跳过姐姐冲突检查', None, None, None
    today = datetime.now().strftime('%Y-%m-%d')
    row = conn.execute(
        '''SELECT sister_uid, sister_nickname FROM team_detail
           WHERE snapshot_date=? AND CAST(sister_uid2 AS TEXT)=?
             AND (dissolve_date IS NULL OR dissolve_date='' OR dissolve_date>?)
           ORDER BY id DESC LIMIT 1''', (snap, str(trainee_uid), today)).fetchone()
    if not row:
        return True, '未在姐妹团中查到该妹妹', None, None, snap
    sister_uid = str(row['sister_uid'] or '')
    if sister_uid == str(trainer_uid):
        return True, '已绑定同一姐姐，允许', sister_uid, row['sister_nickname'], snap
    return False, f"该妹妹当前已绑定姐姐「{row['sister_nickname']}」（UID:{sister_uid}），不能绑定其他培训师（基于 {snap} 快照）", sister_uid, row['sister_nickname'], snap


def _refresh_bigdata_detail():
    """现场刷新 bigdata 明细快照到 team_detail（用于绑定前姐姐冲突检查）。返回抓取条数"""
    from crawler import SistersCrawler
    from auto_login import refresh_bigdata_cookie
    c = SistersCrawler()
    try:
        data = c.crawl_detail()
    except Exception as e:
        if 'Cookie已过期' in str(e) or '登录' in str(e):
            refresh_bigdata_cookie()
            data = SistersCrawler().crawl_detail()
        else:
            raise
    SistersCrawler().save_detail(data)
    return len(data)


def live_sister_conflict(conn, trainee_uid, trainer_uid):
    """绑定前姐姐冲突检查：先现场刷新 bigdata 快照，再按最新数据判断"""
    try:
        count = _refresh_bigdata_detail()
        print(f'[SisterCheck] 已刷新 bigdata 明细 {count} 条', flush=True)
    except Exception as e:
        print(f'[SisterCheck-WARN] bigdata 刷新失败，回退本地快照: {e}', flush=True)
    return check_sister_conflict(conn, trainee_uid, trainer_uid)


def _protection_gate(uid):
    """培训师绑定门槛：妹妹须在保护期内（UID 查询的保护期结束时间 >= 今天）。
    返回 (allowed, msg, warn)。查不到数据或查询失败一律拒绝（保护期无法确认）"""
    try:
        r = UIDCrawler().query(uid, 'game')
    except CookieExpiredError:
        try:
            _heal_uid_cookie()
            r = UIDCrawler().query(uid, 'game')
        except Exception as e:
            return False, f'保护期查询异常（请稍后重试）: {e}', False
    except Exception as e:
        return False, f'保护期查询异常（请稍后重试）: {e}', False
    if not r.get('found'):
        return False, '未查到该 UID 的数据，保护期无法确认，不能绑定', False
    raw = (r.get('protection_end') or '').strip()
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', raw)
    if not m:
        return False, f'该妹妹无保护期结束时间记录，不在保护期内，不能绑定培训师', False
    end = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    if end >= datetime.now().date():
        return True, f'保护期内（至 {end}）', False
    return False, f'该妹妹保护期已于 {end} 结束，不能绑定培训师', False


def judge_side_retained(data):
    """侧方（培训师/姐姐）留存判定：排档大厅 / 权限大厅 / 当周等级 任一非空即算留存。
    侧方本人不排档很常见，不能只看排档+等级（会误判成未留存而不发奖）"""
    if not data.get('found'):
        return None
    def empty(v):
        return v is None or str(v).strip() in ('', '-')
    return not (empty(data.get('schedule_hall')) and empty(data.get('auth_hall'))
                and empty(data.get('week_level')))


def record_trainee_query(conn, uid, data, last_week_data=None, side=False):
    """速查成功后落库当月等级记录（best = 当月最高周等级；含留存判定）。
    last_week_data 可选：用于任务档奖励口径「上周任务 + 当周牌子」。
    side=True 表示侧方（培训师/姐姐），留存用任一非空的宽松口径。
    返回 (retained, prev_retained)：本次判定与上次记录（None=首次查询）"""
    if not data.get('found'):
        return None, None
    month = _current_month()
    lvl = (data.get('week_level') or '').strip()
    rank = level_rank(lvl)
    tasks = int(data.get('daily_task_count') or 0)
    sched_days = int(data.get('week_schedule_days') or 0)
    prev_tasks = int(last_week_data.get('daily_task_count') or 0) if last_week_data and last_week_data.get('found') else None
    retained = judge_side_retained(data) if side else judge_retained(data)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute(
        'SELECT * FROM trainee_level_monthly WHERE trainee_uid=? AND month=?', (uid, month)).fetchone()
    prev = row['last_retained'] if row else None
    # 排档周等级：仅当周排档天数>0 的查询才计入名额贡献
    if row:
        best_lvl = lvl if rank > row['best_rank'] else row['best_level']
        best_rk = max(rank, row['best_rank'])
        act_rk = row['best_rank_active'] or 0
        act_lvl = row['best_level_active'] or ''
        if sched_days > 0 and rank > act_rk:
            act_rk, act_lvl = rank, lvl
        conn.execute(
            '''UPDATE trainee_level_monthly
               SET best_level=?, best_rank=?, last_week_level=?, last_daily_task_count=?, last_queried_at=?, last_retained=?,
                   best_rank_active=?, best_level_active=?, prev_week_tasks=COALESCE(?, prev_week_tasks)
               WHERE id=?''', (best_lvl, best_rk, lvl, tasks, now, retained, act_rk, act_lvl, prev_tasks, row['id']))
    else:
        act_rk, act_lvl = (rank, lvl) if sched_days > 0 else (0, '')
        conn.execute(
            '''INSERT INTO trainee_level_monthly
               (trainee_uid, month, best_level, best_rank, last_week_level, last_daily_task_count, last_queried_at, last_retained,
                best_rank_active, best_level_active, prev_week_tasks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (uid, month, lvl, rank, lvl, tasks, now, retained, act_rk, act_lvl, prev_tasks))
    # 保护期结束时间同步到档案（空值不覆盖旧值）
    prot = (data.get('protection_end') or '').strip()
    if prot and prot != '-':
        conn.execute('UPDATE trainees SET protection_end=? WHERE uid=?', (prot, uid))
    conn.commit()
    return retained, prev


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


def side_retained(conn, side_uid):
    """侧方（培训师/姐姐）留存状态：取最近一次月度记录的判定。None=未查询过（不拦截）"""
    r = conn.execute(
        'SELECT last_retained FROM trainee_level_monthly WHERE trainee_uid=? ORDER BY month DESC, last_queried_at DESC LIMIT 1',
        (side_uid,)).fetchone()
    return r['last_retained'] if r else None


def reward_metrics(conn, b):
    """奖励判定指标：(绑定当月起至今的最高等级 rank, 上周任务次数)。
    等级含跨月；任务取最近一次有上周记录的值，没有则退回当周任务数。"""
    bind_month = (_parse_ts(b['bound_at']) + timedelta(hours=8)).strftime('%Y-%m')
    recs = conn.execute(
        'SELECT best_rank, last_daily_task_count, prev_week_tasks, last_queried_at FROM trainee_level_monthly WHERE trainee_uid=? AND month>=?',
        (b['trainee_uid'], bind_month)).fetchall()
    best_rank = max((r['best_rank'] for r in recs), default=0)
    last_week_tasks = 0
    for r in sorted(recs, key=lambda x: x['last_queried_at'] or '', reverse=True):
        if r['prev_week_tasks'] is not None:
            last_week_tasks = r['prev_week_tasks']
            break
        if r['last_daily_task_count'] is not None:
            last_week_tasks = r['last_daily_task_count']
            break
    return best_rank, last_week_tasks


def sync_pending_rewards(conn, trainee_id):
    """为每条生效绑定生成 pending 奖励（窗口内；侧方未留存不生成）。
    晋升档只发最高达成档（不覆盖发放更低档）。"""
    bindings = conn.execute(
        '''SELECT b.*, t.uid AS trainee_uid, tr.uid AS side_uid FROM bindings b
           JOIN trainees t ON t.id=b.trainee_id JOIN trainers tr ON tr.id=b.trainer_id
           WHERE b.trainee_id=? AND b.unbound_at IS NULL''', (trainee_id,)).fetchall()
    level_tiers = [t for t in REWARD_TIERS if not t.get('need_tasks')]
    level_keys = tuple(t['key'] for t in level_tiers)
    for b in bindings:
        if reward_window_status(b['bound_at'])[2] != 'in_window':
            continue
        if side_retained(conn, b['side_uid']) == 0:
            continue
        best_rank, last_week_tasks = reward_metrics(conn, b)
        # 任务档：上周任务≥6次 + 当周铜牌及以上
        task_tier = next(t for t in REWARD_TIERS if t.get('need_tasks'))
        if best_rank >= 1 and last_week_tasks >= 6:
            conn.execute(
                '''INSERT OR IGNORE INTO reward_grants
                   (binding_id, trainee_uid, trainer_id, reward_key, reward_label, amount)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (b['id'], b['trainee_uid'], b['trainer_id'], task_tier['key'], task_tier['label'], task_tier['amount']))
        # 晋升档：只发最高达成档
        achieved = None
        for t in level_tiers:
            if best_rank >= t['min_rank']:
                achieved = t
        if achieved:
            conn.execute(
                '''INSERT OR IGNORE INTO reward_grants
                   (binding_id, trainee_uid, trainer_id, reward_key, reward_label, amount)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (b['id'], b['trainee_uid'], b['trainer_id'], achieved['key'], achieved['label'], achieved['amount']))
            # 清理其它晋升档的待发放（已被更高档覆盖；已发放的不动）
            marks = ','.join('?' * len(level_keys))
            conn.execute(
                f"DELETE FROM reward_grants WHERE binding_id=? AND status='pending' AND reward_key IN ({marks}) AND reward_key != ?",
                (b['id'], *level_keys, achieved['key']))
    conn.commit()


def build_slots_panel(conn, trainer_id):
    """名额面板：基础名额 + 生效绑定学员有效等级贡献（当月最高，月初无记录用上月兜底），上限 5"""
    tr = conn.execute('SELECT * FROM trainers WHERE id=?', (trainer_id,)).fetchone()
    if not tr:
        return None
    month = _current_month()
    rows = conn.execute(
        '''SELECT t.uid, t.nickname, b.bound_at, b.id AS binding_id, b.weeks_consumed
           FROM bindings b JOIN trainees t ON t.id = b.trainee_id
           WHERE b.trainer_id = ? AND b.bind_type='trainer' AND b.unbound_at IS NULL
           ORDER BY b.bound_at''', (trainer_id,)).fetchall()
    levels = get_effective_levels(conn, [r['uid'] for r in rows])
    trainees = []
    extra = 0
    for r in rows:
        lv = levels.get(r['uid'])
        rank = lv['best_rank'] if lv else 0
        plus = slot_plus(rank)
        extra += plus
        label = lv['best_level'] if lv else '（本月未查询）'
        if lv and lv['from_last_month']:
            label += '（上月兜底）'
        # 每条绑定附奖励窗口与剩余周数
        start, end, wstatus = reward_window_status(r['bound_at'])
        if wstatus == 'in_window':
            # 剩余周数 = 窗口周数 - 已发放周数（人工计数，不再重复扣日历时间）
            weeks_left = max(REWARD_WINDOW_WEEKS - (r['weeks_consumed'] or 0), 0)
        elif wstatus == 'not_started':
            weeks_left = REWARD_WINDOW_WEEKS
        else:
            weeks_left = 0
        trainees.append({
            'uid': r['uid'], 'nickname': r['nickname'], 'bound_at': r['bound_at'],
            'binding_id': r['binding_id'],
            'best_level': label, 'slot_plus': plus,
            'from_last_month': lv['from_last_month'] if lv else False,
            'last_queried_at': lv['last_queried_at'] if lv else None,
            'window_status': wstatus, 'weeks_left': weeks_left,
            'window_start': start.strftime('%Y-%m-%d'), 'window_end': end.strftime('%Y-%m-%d'),
        })
    base = tr['base_slots']
    total = min(base + extra, SLOT_CAP)
    # 扩充有效期：当月达标当月生效，次月按新月等级重算 → 截至本月底
    first_of_month = datetime.now().replace(day=1)
    next_month = first_of_month + timedelta(days=32)
    month_end = (next_month.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
    return {
        'trainer': {'id': tr['id'], 'uid': tr['uid'], 'nickname': tr['nickname']},
        'month': month,
        'base_slots': base, 'extra_slots': extra, 'total_slots': total,
        'used_slots': len(rows), 'over': len(rows) > total,
        'slot_cap': SLOT_CAP,
        'extra_valid_until': month_end,
        'trainees': trainees,
    }


def build_rewards_panel(conn, trainee_id):
    """奖励面板：每条生效绑定（培训师/姐妹团）各一组窗口 + 五档奖励状态"""
    t = conn.execute('SELECT * FROM trainees WHERE id=?', (trainee_id,)).fetchone()
    if not t:
        return None
    bindings = conn.execute(
        '''SELECT b.*, tr.nickname AS side_nickname, tr.uid AS side_uid, t.uid AS trainee_uid
           FROM bindings b
           JOIN trainers tr ON tr.id = b.trainer_id
           JOIN trainees t ON t.id = b.trainee_id
           WHERE b.trainee_id=? AND b.unbound_at IS NULL
           ORDER BY b.bind_type, b.bound_at''', (trainee_id,)).fetchall()
    grants = conn.execute(
        'SELECT * FROM reward_grants WHERE trainee_uid=? ORDER BY id', (t['uid'],)).fetchall()
    mrec = conn.execute(
        'SELECT last_retained, last_queried_at FROM trainee_level_monthly WHERE trainee_uid=? AND month=?',
        (t['uid'], _current_month())).fetchone()

    panels = []
    for b in bindings:
        start, end, status = reward_window_status(b['bound_at'])
        bg = {g['reward_key']: g for g in grants if g['binding_id'] == b['id']}
        best_rank, last_week_tasks = reward_metrics(conn, b)
        rewards = []
        for tier in REWARD_TIERS:
            g = bg.get(tier['key'])
            if g and g['status'] == 'granted':
                st = 'granted'
            elif tier.get('need_tasks'):
                st = 'pending' if g else 'ineligible'
            elif best_rank > tier['min_rank']:
                st = 'achieved'      # 已被更高档覆盖，不单独发
            elif best_rank == tier['min_rank'] and g:
                st = 'pending'
            elif best_rank == tier['min_rank']:
                st = 'achieved'      # 已达但未生成（窗口未开始/已过期）
            else:
                st = 'ineligible'
            rewards.append({
                'key': tier['key'], 'label': tier['label'], 'amount': tier['amount'],
                'status': st,
                'grant_id': g['id'] if g else None,
                'granted_at': g['granted_at'] if g else None,
            })
        panels.append({
            'bind_type': b['bind_type'],
            'type_label': '姐妹团三胎' if b['bind_type'] == 'sister' else '培训师',
            'side_label': '姐姐' if b['bind_type'] == 'sister' else '培训师',
            'side_retained': side_retained(conn, b['side_uid']),  # 0=未留存 → 暂停发奖
            'best_rank': best_rank,
            'last_week_tasks': last_week_tasks,
            'binding': {
                'id': b['id'], 'bound_at': b['bound_at'],
                'side_nickname': b['side_nickname'], 'side_uid': b['side_uid'],
            },
            'window_status': status,
            'in_window': status == 'in_window',
            'window_start': start.strftime('%Y-%m-%d'),
            'window_end': end.strftime('%Y-%m-%d'),
            'days_left': max((end - datetime.now()).days, 0) if status == 'in_window' else None,
            'rewards': rewards,
        })
    panel = {
        'trainee': {'id': t['id'], 'uid': t['uid'], 'nickname': t['nickname']},
        'window_weeks': REWARD_WINDOW_WEEKS,
        'retained': mrec['last_retained'] if mrec else None,
        'panels': panels,
    }
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

import gzip
from io import BytesIO

GZIP_TYPES = ('text/html', 'text/css', 'application/javascript', 'text/javascript', 'application/json')
CACHE_LONG = {'/logo.jpg', '/wutong.png', '/ludeng.png'}
CACHE_SHORT = {'/app.js', '/style.css', '/brand.css', '/portal.js'}


@app.after_request
def _no_cache_static(resp):
    """页面/静态资源缓存与压缩优化：HTML 不缓存，JS/CSS 短缓存协商，图片长缓存，文本 gzip"""
    path = request.path
    if path in CACHE_LONG:
        resp.headers['Cache-Control'] = 'public, max-age=86400'
    elif path in CACHE_SHORT:
        resp.headers['Cache-Control'] = 'no-cache'  # 有修改才全量下载，否则 304
    elif path in ('/', '/login', '/portal'):
        resp.headers['Cache-Control'] = 'no-store'

    # 文本响应 gzip（>500 字节且客户端支持）
    if (resp.status_code == 200 and not resp.is_streamed and resp.content_length and resp.content_length > 500
            and resp.mimetype in GZIP_TYPES and 'gzip' in request.headers.get('Accept-Encoding', '')):
        raw = resp.get_data()
        buf = BytesIO()
        with gzip.GzipFile(fileobj=buf, mode='wb') as f:
            f.write(raw)
        resp.set_data(buf.getvalue())
        resp.headers['Content-Encoding'] = 'gzip'
        resp.headers['Vary'] = 'Accept-Encoding'
        resp.content_length = len(resp.get_data())
    return resp


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
    # 附带当前带的妹妹数与名额（只统计培训师类型绑定；有效等级 = 当月最高，月初用上月兜底）
    counts = dict(conn.execute(
        "SELECT trainer_id, COUNT(*) FROM bindings WHERE unbound_at IS NULL AND bind_type='trainer' GROUP BY trainer_id"
    ).fetchall())
    bound_rows = conn.execute(
        '''SELECT b.trainer_id, t.uid FROM bindings b
           JOIN trainees t ON t.id = b.trainee_id
           WHERE b.unbound_at IS NULL AND b.bind_type='trainer' ''').fetchall()
    levels = get_effective_levels(conn, [r['uid'] for r in bound_rows])
    extras = {}
    for r in bound_rows:
        lv = levels.get(r['uid'])
        extras[r['trainer_id']] = extras.get(r['trainer_id'], 0) + slot_plus(lv['best_rank'] if lv else 0)
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
            # 已存在但是姐姐角色（先作为姐妹团姐姐建档）：转换为培训师
            row = conn.execute('SELECT id, role FROM trainers WHERE uid=?', (person['uid'],)).fetchone()
            if row and row['role'] != 'trainer':
                conn.execute("UPDATE trainers SET role='trainer', updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['id'],))
                conn.commit()
                return ok({'id': row['id'], 'converted': True})
            return err(f"UID {person['uid']} 的培训师已存在", 409)
        raise
    finally:
        conn.close()


@app.post('/api/trainers/bulk-import')
def bulk_import_trainers():
    """批量录入培训师：uids 为逗号/空格/换行分隔的 UID 文本，默认基础名额 2，重复跳过。
    新增的成功后自动用 UID 查询补全昵称/大厅（查不到的保留 UID 当昵称）"""
    data = request.get_json(force=True)
    raw = str(data.get('uids', ''))
    uids = [u.strip() for u in re.split(r'[,\s，、;；\n\r]+', raw) if u.strip()]
    if not uids:
        return err('请输入至少一个 UID（逗号分隔）')
    conn = get_db()
    created, skipped = [], []
    for uid in dict.fromkeys(uids):  # 保序去重
        try:
            conn.execute('INSERT INTO trainers (uid, nickname, base_slots) VALUES (?, ?, 2)', (uid, uid))
            created.append(uid)
        except Exception as e:
            if 'UNIQUE' in str(e):
                # 已存在但角色不是 trainer（如先作为姐姐建档）：更新角色而不是跳过
                conn.execute("UPDATE trainers SET role='trainer' WHERE uid=? AND role != 'trainer'", (uid,))
                skipped.append(uid)
            else:
                conn.rollback()
                conn.close()
                raise
    conn.commit()
    conn.close()

    # 逐个补全昵称/大厅（有间隔，失败自动重登一次）
    filled = 0
    if created:
        crawler = UIDCrawler()
        healed = False
        for i, uid in enumerate(created):
            if i:
                time.sleep(0.6)
            try:
                r = crawler.query(uid, 'game')
                if not r.get('found'):
                    continue
                nick = (r.get('nickname') or '').strip()
                hall = (r.get('schedule_hall') or r.get('auth_hall') or '').strip()
                if hall == '-':
                    hall = ''
                conn = get_db()
                conn.execute(
                    """UPDATE trainers SET nickname=COALESCE(NULLIF(?, ''), nickname),
                       hall_name=COALESCE(NULLIF(?, ''), hall_name) WHERE uid=?""",
                    (nick, hall, uid))
                conn.commit()
                conn.close()
                if nick or hall:
                    filled += 1
            except CookieExpiredError:
                if healed:
                    break
                healed = True
                try:
                    _heal_uid_cookie()
                    crawler = UIDCrawler()
                except Exception:
                    break
            except Exception:
                continue
    return ok({'created': created, 'skipped': skipped, 'created_count': len(created), 'filled': filled})


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
        '''SELECT b.id, b.bind_type, b.bound_at, b.unbound_at, b.note, b.weeks_consumed,
                  tr.id AS trainer_id, tr.uid AS trainer_uid, tr.nickname AS trainer_nickname, tr.role AS side_role,
                  te.id AS trainee_id, te.uid AS trainee_uid, te.nickname AS trainee_nickname, te.hall_name, te.protection_end
           FROM bindings b
           JOIN trainers tr ON tr.id = b.trainer_id
           JOIN trainees te ON te.id = b.trainee_id
           WHERE b.unbound_at IS {} NULL
           ORDER BY b.id DESC'''.format('' if active else 'NOT')).fetchall()
    items = rows_to_dicts(rows)
    btype = request.args.get('bind_type', '').strip()
    if btype in BIND_TYPES:
        items = [b for b in items if b['bind_type'] == btype]
    kw = request.args.get('kw', '').strip()
    if kw:
        k = kw.lower()
        items = [b for b in items if k in str(b['trainer_nickname']).lower()
                 or k in str(b['trainee_nickname']).lower()
                 or k in str(b['trainer_uid']) or k in str(b['trainee_uid'])]
    # 每行附奖励窗口信息：结束日期 / 状态 / 剩余周数
    month = _current_month()
    retained_map = {r['trainee_uid']: r['last_retained'] for r in conn.execute(
        'SELECT trainee_uid, last_retained FROM trainee_level_monthly WHERE month=?', (month,)).fetchall()}
    for b in items:
        start, end, status = reward_window_status(b['bound_at'])
        b['window_start'] = start.strftime('%Y-%m-%d')
        b['window_end'] = end.strftime('%Y-%m-%d')
        b['window_status'] = status
        b['retained'] = retained_map.get(b['trainee_uid'])  # None=本月未查询
        if status == 'in_window':
            # 剩余周数 = 窗口周数 - 已发放周数（人工计数，不再重复扣日历时间）
            b['weeks_left'] = max(REWARD_WINDOW_WEEKS - (b['weeks_consumed'] or 0), 0)
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

    # 培训师绑定门槛：妹妹须在保护期内
    if bind_type == 'trainer':
        allowed, gate_msg, gate_warn = _protection_gate(trainee_uid)
        if not allowed:
            return jsonify({'ok': False, 'msg': gate_msg, 'gate': True}), 422
    else:
        gate_msg, gate_warn = None, False

    conn = get_db()
    try:
        if bind_type == 'trainer':
            ok2, msg2, _, _, _ = live_sister_conflict(conn, trainee_uid, trainer_uid)
            if not ok2:
                conn.close()
                return jsonify({'ok': False, 'msg': msg2, 'gate': True, 'conflict_sister': True}), 409
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
            if gate_msg:
                payload['gate_msg'] = gate_msg
                payload['gate_warn'] = gate_warn
            conn.commit()
            log_operation('admin', None, 'bind', bind_type, trainer_uid, trainee_uid,
                          '强制换绑' if payload.get('rebound') else '新建绑定')
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
    if cur.rowcount == 0:
        conn.close()
        return err('绑定不存在或已解绑', 404)
    info = conn.execute(
        '''SELECT b.bind_type, tr.uid AS trainer_uid, te.uid AS trainee_uid FROM bindings b
           JOIN trainers tr ON tr.id=b.trainer_id JOIN trainees te ON te.id=b.trainee_id WHERE b.id=?''',
        (bid,)).fetchone()
    conn.close()
    log_operation('admin', None, 'unbind', info['bind_type'], info['trainer_uid'], info['trainee_uid'], '管理员解绑')
    return ok()


@app.post('/api/bindings/<int:bid>/restore')
def restore_binding(bid):
    """从历史记录恢复绑定（置回生效）。与现有唯一约束冲突时 409"""
    conn = get_db()
    b = conn.execute('SELECT * FROM bindings WHERE id=?', (bid,)).fetchone()
    if not b:
        conn.close()
        return err('绑定不存在', 404)
    if b['unbound_at'] is None:
        conn.close()
        return err('该绑定已是生效状态，无需恢复', 409)
    conflict = conn.execute(
        'SELECT id FROM bindings WHERE trainee_id=? AND bind_type=? AND unbound_at IS NULL AND id != ?',
        (b['trainee_id'], b['bind_type'], bid)).fetchone()
    if conflict:
        conn.close()
        return err('该妹妹当前已有同类型生效绑定，请先解绑再恢复', 409)
    if b['bind_type'] == 'sister':
        busy = conn.execute(
            "SELECT id FROM bindings WHERE trainer_id=? AND bind_type='sister' AND unbound_at IS NULL AND id != ?",
            (b['trainer_id'], bid)).fetchone()
        if busy:
            conn.close()
            return err('该姐姐当前已有生效的三胎绑定（一对一），请先解绑再恢复', 409)
    conn.execute('UPDATE bindings SET unbound_at=NULL WHERE id=?', (bid,))
    conn.execute("UPDATE trainees SET status='active', updated_at=CURRENT_TIMESTAMP WHERE id=?", (b['trainee_id'],))
    conn.commit()
    info = conn.execute(
        '''SELECT b.bind_type, tr.uid AS trainer_uid, te.uid AS trainee_uid FROM bindings b
           JOIN trainers tr ON tr.id=b.trainer_id JOIN trainees te ON te.id=b.trainee_id WHERE b.id=?''',
        (bid,)).fetchone()
    conn.close()
    log_operation('admin', None, 'restore', info['bind_type'], info['trainer_uid'], info['trainee_uid'], '从历史恢复')
    return ok()


@app.post('/api/rewards/grant-week')
def grant_week():
    """「奖励已发放」：窗口内的生效绑定 已发放周数+1，且其待发放奖励全部标记已发。
    窗口未开始的绑定不动。可选 binding_ids 限定范围（默认全部窗口内绑定）。"""
    data = request.get_json(force=True, silent=True) or {}
    id_filter = data.get('binding_ids')
    conn = get_db()
    bindings = conn.execute(
        'SELECT id, bound_at, weeks_consumed FROM bindings WHERE unbound_at IS NULL').fetchall()
    touched_ids = []
    for b in bindings:
        if id_filter and b['id'] not in id_filter:
            continue
        if reward_window_status(b['bound_at'])[2] != 'in_window':
            continue
        conn.execute(
            'UPDATE bindings SET weeks_consumed = MIN(weeks_consumed + 1, ?) WHERE id=?',
            (REWARD_WINDOW_WEEKS, b['id']))
        touched_ids.append(b['id'])
    granted = 0
    if touched_ids:
        marks = ','.join('?' * len(touched_ids))
        granted = conn.execute(
            f"""UPDATE reward_grants SET status='granted', granted_at=CURRENT_TIMESTAMP
                WHERE status='pending' AND binding_id IN ({marks})""", touched_ids).rowcount
    conn.commit()
    conn.close()
    return ok({'bindings': len(touched_ids), 'granted': granted})


@app.post('/api/bindings/<int:bid>/set-remaining')
def set_remaining(bid):
    """手动修改某条绑定的剩余奖励周数（0~4）"""
    data = request.get_json(force=True)
    try:
        remaining = int(data.get('remaining'))
    except (TypeError, ValueError):
        return err('remaining 必须是 0~4 的整数')
    if not 0 <= remaining <= REWARD_WINDOW_WEEKS:
        return err(f'remaining 必须在 0~{REWARD_WINDOW_WEEKS} 之间')
    conn = get_db()
    b = conn.execute('SELECT * FROM bindings WHERE id=?', (bid,)).fetchone()
    if not b or b['unbound_at'] is not None:
        conn.close()
        return err('绑定不存在或已解绑', 404)
    start, end, status = reward_window_status(b['bound_at'])
    if status != 'in_window':
        conn.close()
        return err('只能修改窗口内的绑定（未开始/已结束不可改）', 409)
    consumed = max(REWARD_WINDOW_WEEKS - remaining, 0)
    conn.execute('UPDATE bindings SET weeks_consumed=? WHERE id=?', (consumed, bid))
    conn.commit()
    conn.close()
    return ok({'weeks_consumed': consumed, 'weeks_left': remaining})


# ────────────────────────────────────────────── 操作日志查看

@app.get('/api/operations')
def list_operations():
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM operation_log ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    return ok({'items': rows_to_dicts(rows)})


# ────────────────────────────────────────────── 数据看板

def _local_date(utc_str):
    return (_parse_ts(utc_str) + timedelta(hours=8)).date()


def _week_monday(d):
    return d - timedelta(days=d.weekday())


@app.get('/api/dashboard/summary')
def dashboard_summary():
    conn = get_db()
    bindings = conn.execute(
        'SELECT bind_type, bound_at, unbound_at, note FROM bindings').fetchall()
    conn.close()

    # 周选择：week=YYYY-MM-DD（该周任意一天），默认本周
    today = datetime.now().date()
    try:
        anchor = datetime.strptime(request.args.get('week', ''), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        anchor = today
    this_monday = _week_monday(anchor)
    trend_anchor = _week_monday(today)
    weeks = [trend_anchor - timedelta(weeks=i) for i in range(7, -1, -1)]  # 近 8 周（含本周）
    weekly = {w: {'bound': 0, 'unbound': 0} for w in weeks}

    active_trainer = active_sister = 0
    reasons = {}
    reasons_week = {}
    sel_bound = sel_unbound = 0
    cohort_retained = cohort_dissolved = 0
    cutoff = today - timedelta(days=28)
    for b in bindings:
        bd = _local_date(b['bound_at'])
        w = _week_monday(bd)
        if w in weekly:
            weekly[w]['bound'] += 1
        if w == this_monday:
            sel_bound += 1
        ud = _local_date(b['unbound_at']) if b['unbound_at'] else None
        if ud is None:
            if b['bind_type'] == 'sister':
                active_sister += 1
            else:
                active_trainer += 1
        else:
            uw = _week_monday(ud)
            if uw in weekly:
                weekly[uw]['unbound'] += 1
            if uw == this_monday:
                sel_unbound += 1
        # 4 周留存/解散：成团满 28 天的绑定，仍在档或满 28 天才解散 = 留存
        if bd <= cutoff:
            if ud is None or (ud - bd).days >= 28:
                cohort_retained += 1
            else:
                cohort_dissolved += 1
        if ud is None:
            continue
        # 解散原因归类（从备注解析）
        note = b['note'] or ''
        if '系统判定解散：留存字段为空' in note:
            reason = '妹妹未留存（系统）'
        elif '系统判定解散：培训师未留存' in note:
            reason = '培训师未留存（系统）'
        elif '系统判定解散：姐姐未留存' in note:
            reason = '姐姐未留存（系统）'
        elif '人工确认解散' in note:
            reason = '人工确认解散'
        else:
            reason = '手动解绑'
        reasons[reason] = reasons.get(reason, 0) + 1
        if uw == this_monday:
            reasons_week[reason] = reasons_week.get(reason, 0) + 1

    conn = get_db()
    pending_rewards = conn.execute(
        "SELECT COUNT(*) FROM reward_grants WHERE status='pending'").fetchone()[0]
    granted_rewards = conn.execute(
        "SELECT COUNT(*) FROM reward_grants WHERE status='granted'").fetchone()[0]
    conn.close()

    cohort = cohort_retained + cohort_dissolved
    retention_rate = round(cohort_retained / cohort * 100, 1) if cohort else 0.0
    dissolution_rate = round(cohort_dissolved / cohort * 100, 1) if cohort else 0.0

    return ok({
        'this_week': {
            'bound': sel_bound,
            'unbound': sel_unbound,
            'label': f'{this_monday:%m-%d} ~ {this_monday + timedelta(days=6):%m-%d}',
        },
        'active': {'trainer': active_trainer, 'sister': active_sister,
                   'total': active_trainer + active_sister},
        'weekly': [{
            'week_start': f'{w:%m-%d}',
            'label': f'{w:%m-%d}~{w + timedelta(days=6):%m-%d}',
            'bound': weekly[w]['bound'], 'unbound': weekly[w]['unbound'],
        } for w in weeks],
        'dissolve_reasons': [{'reason': k, 'count': v} for k, v in
                             sorted(reasons.items(), key=lambda x: -x[1])],
        'dissolve_reasons_week': [{'reason': k, 'count': v} for k, v in
                                  sorted(reasons_week.items(), key=lambda x: -x[1])],
        'retention_4w': {
            'cohort': cohort, 'retained': cohort_retained, 'dissolved': cohort_dissolved,
            'retention_rate': retention_rate, 'dissolution_rate': dissolution_rate,
        },
        'rewards': {'pending': pending_rewards, 'granted': granted_rewards},
    })


# ────────────────────────────────────────────── 周奖励导出（XLSX）

# 导出金额口径（与参考文件一致）：任务奖固定 12.8（周任务≥6次且当周铜牌及以上）；等级奖按牌子
TASK_REWARD_MIN = 6
TASK_REWARD_AMOUNT = 12.8
LEVEL_REWARD = {'初级银牌': 12.8, '银牌': 23.3, '金牌': 52.0, '王牌': 131.4}


@app.post('/api/export/rewards')
@serialized_query
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
    # 只导「在档且正处于奖励窗口内」的绑定；窗口未开始的（如周一刚绑的）轮到下周一，已过期的剔除
    bindings = [b for b in all_bindings
                if reward_window_status(b['bound_at'])[2] == 'in_window']

    crawler = UIDCrawler()
    healed = False
    side_cache = {}   # 侧方留存缓存：同一培训师/姐姐只查一次
    rows, errors = [], []
    for i, b in enumerate(bindings):
        if i:
            time.sleep(0.6)  # server1 会话 TTL 短，控制频率
        try:
            cur = crawler.query(b['trainee_uid'], 'game', *this_range)
            last = crawler.query(b['trainee_uid'], 'game', *last_range)
            if b['side_uid'] not in side_cache:
                side_cache[b['side_uid']] = crawler.query(b['side_uid'], 'game', *this_range)
        except CookieExpiredError:
            if healed:
                return err(f'导出到第 {i + 1} 行时 Cookie 再次过期，请稍后重试', 401)
            healed = True
            try:
                _heal_uid_cookie()
                crawler = UIDCrawler()
                cur = crawler.query(b['trainee_uid'], 'game', *this_range)
                last = crawler.query(b['trainee_uid'], 'game', *last_range)
                if b['side_uid'] not in side_cache:
                    side_cache[b['side_uid']] = crawler.query(b['side_uid'], 'game', *this_range)
            except Exception as e:
                return err(f'自动重登后查询仍失败: {e}', 502)
        except Exception as e:
            errors.append(f"{b['trainee_nickname']}({b['trainee_uid']}): {e}")
            continue

        # 侧方（培训师/姐姐）未留存 → 不发奖
        side_ok = True
        sc = side_cache.get(b['side_uid'])
        if sc and sc.get('found'):
            conn = get_db()
            record_trainee_query(conn, b['side_uid'], sc, side=True)
            conn.close()
            side_ok = judge_side_retained(sc) is not False

        level = (cur.get('week_level') or '').strip() if cur.get('found') else ''
        tasks = int(last.get('daily_task_count') or 0) if last.get('found') else 0
        revenue = float(last.get('week_revenue') or 0) if last.get('found') else 0
        hall = (cur.get('schedule_hall') or cur.get('auth_hall')
                or last.get('schedule_hall') or last.get('auth_hall') or b['hall_name'] or '')
        if side_ok:
            task_reward = TASK_REWARD_AMOUNT if (tasks >= TASK_REWARD_MIN and level_rank(level) >= 1) else '无'
            level_reward = LEVEL_REWARD.get(level, '无')
        else:
            task_reward = level_reward = '无'
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
@serialized_query
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
    last_start, last_end = _last_week_range()
    queried, errors = [], []
    for i, b in enumerate(bindings):
        if i:
            time.sleep(0.6)  # server1 会话 TTL 短，控制频率
        try:
            r = crawler.query(b['uid'], 'game')
            r_last = crawler.query(b['uid'], 'game', last_start, last_end)
        except CookieExpiredError as e:
            if healed:
                return err(f'已刷新 {len(queried)}/{len(bindings)} 人时 Cookie 再次过期: {e}', 401)
            healed = True
            try:
                _heal_uid_cookie()
                crawler = UIDCrawler()
                r = crawler.query(b['uid'], 'game')
                r_last = crawler.query(b['uid'], 'game', last_start, last_end)
            except CookieExpiredError as e2:
                return err(f'自动重登后 Cookie 仍无效: {e2}', 401)
            except Exception as e2:
                return err(f'自动重登失败: {e2}', 502)
        except Exception as e:
            errors.append({'uid': b['uid'], 'nickname': b['nickname'], 'msg': str(e)})
            continue
        conn = get_db()
        retained, prev = record_trainee_query(conn, b['uid'], r, r_last)
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


@app.post('/api/trainees/<int:tid>/refresh')
@serialized_query
def refresh_trainee(tid):
    """实时查询该学员并更新档案（大厅/昵称）+ 当月等级记录 + 留存判定"""
    conn = get_db()
    t = conn.execute('SELECT * FROM trainees WHERE id=?', (tid,)).fetchone()
    conn.close()
    if not t:
        return err('妹妹不存在', 404)
    try:
        last_start, last_end = _last_week_range()
        r = UIDCrawler().query(t['uid'], 'game')
        r_last = UIDCrawler().query(t['uid'], 'game', last_start, last_end)
    except CookieExpiredError:
        try:
            _heal_uid_cookie()
            r = UIDCrawler().query(t['uid'], 'game')
            r_last = UIDCrawler().query(t['uid'], 'game', last_start, last_end)
        except CookieExpiredError as e:
            return err(str(e), 401)
        except Exception as e:
            return err(f'自动重登后查询仍失败: {e}', 502)
    except Exception as e:
        return err(f'查询失败: {e}', 502)
    if not r.get('found'):
        return err(r.get('msg', '未查到数据'), 502)

    hall = (r.get('schedule_hall') or '').strip()
    if hall in ('', '-'):
        hall = (r.get('auth_hall') or '').strip()
    if hall == '-':
        hall = ''
    nick = (r.get('nickname') or '').strip()
    conn = get_db()
    if hall or nick:
        conn.execute(
            """UPDATE trainees SET hall_name=COALESCE(NULLIF(?, ''), hall_name),
               nickname=COALESCE(NULLIF(?, ''), nickname), updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (hall, nick, tid))
    retained, prev = record_trainee_query(conn, t['uid'], r, r_last)
    # 妹妹不再由系统自动解散（由用户自行解散）
    sync_pending_rewards(conn, tid)
    conn.commit()
    conn.close()
    return ok({'info': {'nickname': nick, 'hall_name': hall, 'week_level': r.get('week_level', '')},
               'retained': retained, 'dissolved': False})


@app.post('/api/rewards/grant-all')
def grant_all_rewards():
    """一键标记某条绑定的全部待发放奖励为已发"""
    data = request.get_json(force=True)
    binding_id = data.get('binding_id')
    if not binding_id:
        return err('binding_id 不能为空')
    conn = get_db()
    cur = conn.execute(
        "UPDATE reward_grants SET status='granted', granted_at=CURRENT_TIMESTAMP WHERE binding_id=? AND status='pending'",
        (binding_id,))
    conn.commit()
    conn.close()
    return ok({'granted': cur.rowcount})


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
@serialized_query
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
    if week_data.get('found'):
        retained = judge_retained(week_data)
        payload['retention'] = {
            'retained': retained,
            'msg': '留存正常' if retained else '未留存：排档大厅 / 当周等级均为空，可判定团队解散',
        }
    conn = get_db()
    try:
        tr = conn.execute('SELECT id FROM trainers WHERE uid=?', (uid,)).fetchone()
        if tr:
            if week_data.get('found'):
                record_trainee_query(conn, uid, week_data, side=True)  # 侧方留存判定（只标记，不自动解散）
            payload['slots'] = build_slots_panel(conn, tr['id'])
        te = conn.execute('SELECT id FROM trainees WHERE uid=?', (uid,)).fetchone()
        if te:
            if week_data.get('found'):
                record_trainee_query(
                    conn, uid, week_data, result.get('last_week', {}).get('data'))
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
        'protection_end': (r.get('protection_end') or '').strip(),
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


@serialized_query
def refresh_all_bound_trainees():
    """逐个实时查询所有生效绑定的学员+侧方（培训师/姐姐），落库当月等级、留存并重算奖励"""
    conn = get_db()
    rows = conn.execute(
        '''SELECT DISTINCT t.id AS trainee_id, t.uid, t.nickname
           FROM bindings b JOIN trainees t ON t.id = b.trainee_id
           WHERE b.unbound_at IS NULL ORDER BY t.uid''').fetchall()
    sides = conn.execute(
        '''SELECT DISTINCT tr.uid, tr.nickname
           FROM bindings b JOIN trainers tr ON tr.id = b.trainer_id
           WHERE b.unbound_at IS NULL ORDER BY tr.uid''').fetchall()
    conn.close()

    crawler = UIDCrawler()
    healed = False

    def _query_with_heal(uid):
        nonlocal crawler, healed
        try:
            return crawler.query(uid, 'game'), None
        except CookieExpiredError:
            if healed:
                return None, 'Cookie 再次过期，中止'
            healed = True
            try:
                _heal_uid_cookie()
                crawler = UIDCrawler()
                return crawler.query(uid, 'game'), None
            except Exception as e:
                return None, f'自动重登失败: {e}'
        except Exception as e:
            return None, str(e)

    queried, errors = [], []
    last_start, last_end = _last_week_range()

    # 先刷侧方（留存判定供奖励拦截用）
    for i, s in enumerate(sides):
        if i:
            time.sleep(0.6)
        r, errmsg = _query_with_heal(s['uid'])
        if r is None:
            errors.append({'uid': s['uid'], 'nickname': s['nickname'], 'msg': errmsg})
            if '中止' in errmsg or '重登失败' in errmsg:
                return queried, errors
            continue
        conn = get_db()
        record_trainee_query(conn, s['uid'], r, side=True)   # 侧方留存判定（只标记，不自动解散）
        conn.close()

    for i, b in enumerate(rows):
        if i or sides:
            time.sleep(0.6)  # server1 会话 TTL 短，控制频率
        r, errmsg = _query_with_heal(b['uid'])
        if r is None:
            errors.append({'uid': b['uid'], 'nickname': b['nickname'], 'msg': errmsg})
            if '中止' in errmsg or '重登失败' in errmsg:
                break
            continue
        try:
            r_last = crawler.query(b['uid'], 'game', last_start, last_end)
        except Exception:
            r_last = None
        conn = get_db()
        retained, prev = record_trainee_query(conn, b['uid'], r, r_last)
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
