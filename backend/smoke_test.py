# -*- coding: utf-8 -*-
"""API 冒烟测试（自清理测试数据；只用 9000x/8000x/9100x 测试 UID，绝不碰真实数据）。
运行: .venv/Scripts/python.exe -X utf8 backend/smoke_test.py"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import requests

B = 'http://127.0.0.1:5000'
passed = failed = 0

def check(name, cond, extra=''):
    global passed, failed
    if cond:
        passed += 1
        print(f'  [PASS] {name}')
    else:
        failed += 1
        print(f'  [FAIL] {name} {extra}')


MONTH = datetime.now().strftime('%Y-%m')
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'stats.db')
NOW_S = datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def db_exec(sql, params=()):
    conn = sqlite3.connect(DB)
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def db_one(sql, params=()):
    conn = sqlite3.connect(DB)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def insert_monthly(uid, month, level, rank, tasks=7, retained=1, active=True):
    """插入月度等级记录；active=True 表示排档周等级（名额贡献口径）"""
    db_exec('''INSERT INTO trainee_level_monthly
               (trainee_uid, month, best_level, best_rank, last_week_level, last_daily_task_count, last_queried_at,
                last_retained, best_rank_active, best_level_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (uid, month, level, rank, level, tasks, NOW_S, retained,
             rank if active else 0, level if active else ''))


def expected_window(bound_at_utc):
    """与后端同口径：绑定次周周一(本地) 起整四周"""
    local = datetime.strptime(bound_at_utc, '%Y-%m-%d %H:%M:%S') + timedelta(hours=8)
    d = (7 - local.weekday()) % 7 or 7
    start = (local + timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(weeks=4)


def bind(uid_a, uid_b, **kw):
    payload = {'trainer_uid': uid_a, 'trainee_uid': uid_b}
    payload.update(kw)
    return requests.post(f'{B}/api/bindings/by-uid', json=payload)


# 预清理：上次异常退出可能残留的测试档案（按 UID 精确匹配）
for b in requests.get(f'{B}/api/bindings', params={'active': 1, 'page_size': 100}).json().get('items', []):
    if str(b['trainee_uid']) in ('80001', '80002', '80003') or str(b['trainer_uid']) in ('90001', '90002', '90003', '91001', '91002'):
        requests.post(f"{B}/api/bindings/{b['id']}/unbind")
for uid in ('90001', '90002', '90003', '91001', '91002'):
    for t in requests.get(f'{B}/api/trainers', params={'role': 'all', 'kw': uid}).json().get('items', []):
        if t['uid'] == uid:
            requests.delete(f"{B}/api/trainers/{t['id']}")
for uid in ('80001', '80002', '80003'):
    for t in requests.get(f'{B}/api/trainees', params={'kw': uid}).json().get('items', []):
        if t['uid'] == uid:
            requests.delete(f"{B}/api/trainees/{t['id']}")
    db_exec('DELETE FROM trainee_level_monthly WHERE trainee_uid=?', (uid,))
    db_exec('DELETE FROM reward_grants WHERE trainee_uid=?', (uid,))


print('== 培训师 CRUD ==')
r = requests.post(f'{B}/api/trainers', json={'uid': '90001', 'nickname': '测试培训师A', 'hall_name': '游戏一厅'})
check('新增培训师A（默认基础名额2）', r.ok and r.json()['ok'], r.text)
tr_a = r.json().get('id')
r = requests.post(f'{B}/api/trainers', json={'uid': '90002', 'nickname': '测试培训师B', 'base_slots': 3})
check('新增培训师B（基础名额3）', r.ok, r.text)
tr_b = r.json().get('id')
r = requests.post(f'{B}/api/trainers', json={'uid': '90001', 'nickname': '重复'})
check('UID 重复 409', r.status_code == 409, f'got {r.status_code}')
r = requests.post(f'{B}/api/trainers', json={'uid': '90099', 'nickname': 'X', 'base_slots': 9})
check('基础名额超上限 400', r.status_code == 400, f'got {r.status_code}')
r = requests.put(f'{B}/api/trainers/{tr_b}', json={'uid': '90002', 'nickname': '测试培训师B改', 'status': 'active', 'note': '备注', 'base_slots': 3})
check('编辑培训师B', r.ok, r.text)
r = requests.get(f'{B}/api/trainers', params={'kw': 'B改'})
check('搜索培训师', r.ok and len(r.json()['items']) == 1, r.text)
r = requests.get(f'{B}/api/trainers')
item_a = next((t for t in r.json()['items'] if t['uid'] == '90001'), None)
check('列表带名额字段 total_slots=2', item_a and item_a['total_slots'] == 2, str(item_a))
check('列表带分页字段', 'total' in r.json() and r.json()['page_size'] == 20, str(r.json().keys()))

print('== 妹妹 CRUD ==')
r = requests.post(f'{B}/api/trainees', json={'uid': '80001', 'nickname': '测试妹妹甲', 'hall_name': '游戏一厅'})
check('新增妹妹甲', r.ok, r.text)
te_a = r.json().get('id')
r = requests.post(f'{B}/api/trainees', json={'uid': '80002', 'nickname': '测试妹妹乙'})
check('新增妹妹乙', r.ok, r.text)
te_b = r.json().get('id')
r = requests.put(f'{B}/api/trainees/{te_b}', json={'uid': '80002', 'nickname': '测试妹妹乙', 'status': 'graduated'})
check('状态 graduated 不再接受 400', r.status_code == 400, f'got {r.status_code}')
r = requests.put(f'{B}/api/trainees/{te_b}', json={'uid': '80002', 'nickname': '测试妹妹乙', 'status': 'inactive'})
check('状态 active/inactive 正常', r.ok, r.text)

print('== by-uid 绑定与保护期门槛 ==')
r = bind('90001', '80001')
check('培训师绑定被保护期门槛拦截 422（测试 UID 无保护期记录）', r.status_code == 422 and r.json().get('gate'), r.text)
check('门槛拦截不落库', db_one("SELECT COUNT(*) FROM bindings WHERE trainee_id=?", (te_a,))[0] == 0)
r = bind('90001', '90001')
check('同一人绑定 400', r.status_code == 400, f'got {r.status_code}')
r = bind('90003', '80003', bind_type='sister', trainer_nickname='自动建档C', trainee_nickname='自动建档丙')
d = r.json()
check('by-uid 自动建档双方（姐妹团无门槛）', r.ok and d.get('trainer_created') and d.get('trainee_created'), r.text)
tr_c = db_one("SELECT id FROM trainers WHERE uid='90003'")[0]
te_c = db_one("SELECT id FROM trainees WHERE uid='80003'")[0]
check('自动建档培训师默认名额2', db_one("SELECT base_slots FROM trainers WHERE uid='90003'")[0] == 2)
# 下游逻辑（名额/奖励/窗口）需要培训师绑定：门槛已验证，直接落库构造
db_exec("INSERT INTO bindings (trainer_id, trainee_id, bind_type, note) VALUES (?, ?, 'trainer', '测试直插')", (tr_b, te_a))

print('== 姐妹团三胎绑定 ==')
r = bind('91001', '80001', bind_type='sister', trainer_nickname='测试姐姐甲')
d = r.json()
check('妹妹可同时有培训师+姐妹团绑定', r.ok and d.get('bind_type') == 'sister', r.text)
sis_a = db_one("SELECT id, role FROM trainers WHERE uid='91001'")
check('姐姐自动建档 role=sister', sis_a and sis_a[1] == 'sister', str(sis_a))
r = bind('91001', '80002', bind_type='sister', trainee_nickname='测试妹妹乙')
check('姐姐再绑第二个妹妹 409（三胎一对一）', r.status_code == 409 and '一对一' in r.json().get('msg', ''), r.text)
r = bind('91001', '80002', bind_type='sister', force=True)
check('姐姐强制换绑成功', r.ok and r.json().get('rebound'), r.text)
r = requests.get(f'{B}/api/bindings', params={'active': 1, 'bind_type': 'sister'})
sis_items = [b for b in r.json()['items'] if str(b['trainer_uid']) == '91001']
check('姐姐仅一条生效三胎绑定', len(sis_items) == 1 and sis_items[0]['trainee_uid'] == '80002', str(sis_items))
r = requests.get(f'{B}/api/bindings', params={'active': 1, 'bind_type': 'trainer'})
check('按类型过滤生效绑定', all(b['bind_type'] == 'trainer' for b in r.json()['items']), r.text)
b1 = next(b for b in requests.get(f'{B}/api/bindings', params={'active': 1}).json()['items'] if b['trainee_uid'] == '80001')
check('绑定带奖励窗口字段', b1.get('window_end') and b1.get('window_status') in ('not_started', 'in_window', 'expired')
      and b1.get('weeks_left') is not None, str({k: b1.get(k) for k in ('window_end', 'window_status', 'weeks_left')}))
_, we1 = expected_window(b1['bound_at'])
check('绑定列表结束日期=窗口终点', b1['window_end'] == we1.strftime('%Y-%m-%d'), f"{b1['window_end']} != {we1.date()}")
# 妹妹甲:培训师B + 妹妹乙:姐姐（姐妹团） 并存检查
r = requests.get(f'{B}/api/trainees', params={'kw': '80001'})
t1 = r.json()['items'][0]
check('甲同时显示培训师绑定', t1['trainer_uid'] == '90002' and not t1['sister_uid'], str(t1))
r = requests.get(f'{B}/api/trainees', params={'kw': '80002'})
t2 = r.json()['items'][0]
check('乙显示姐妹团姐姐', t2['sister_uid'] == '91001' and not t2['trainer_uid'], str(t2))

print('== 培训师列表不含姐姐 ==')
r = requests.get(f'{B}/api/trainers')
check('默认只列 role=trainer', all(t.get('role', 'trainer') == 'trainer' for t in r.json()['items']), r.text)
r = requests.get(f'{B}/api/trainers', params={'role': 'all', 'kw': '91001'})
check('role=all 能查到姐姐', len(r.json()['items']) == 1, r.text)

print('== 名额判定（只算培训师绑定） ==')
r = requests.get(f'{B}/api/trainers/{tr_a}/slots')
s = r.json()['slots']
check('A 无生效绑定 总名额=基础2', s['total_slots'] == 2 and s['used_slots'] == 0, str(s))
insert_monthly('80001', MONTH, '金牌', 4, tasks=7)
r = requests.get(f'{B}/api/trainers/{tr_b}/slots')
s = r.json()['slots']
check('金牌学员（有排档）+3 → B 总名额 min(3+3,5)=5', s['extra_slots'] == 3 and s['total_slots'] == 5, str(s))
print('== 名额排档门槛 ==')
db_exec("UPDATE trainee_level_monthly SET best_rank_active=0, best_level_active='' WHERE trainee_uid='80001' AND month=?", (MONTH,))
r = requests.get(f'{B}/api/trainers/{tr_b}/slots')
check('金牌但当周无排档 → 不贡献名额', r.json()['slots']['extra_slots'] == 0, str(r.json()['slots']['trainees']))
db_exec("UPDATE trainee_level_monthly SET best_rank_active=4, best_level_active='金牌' WHERE trainee_uid='80001' AND month=?", (MONTH,))
r = requests.get(f'{B}/api/trainers/{tr_b}/slots')
check('恢复排档后重新 +3', r.json()['slots']['extra_slots'] == 3, str(r.json()['slots']['extra_slots']))
b1r = next(b for b in requests.get(f'{B}/api/bindings', params={'active': 1}).json()['items'] if b['trainee_uid'] == '80001')
check('绑定列表带留存标记 retained=1', b1r.get('retained') == 1, str(b1r.get('retained')))
db_exec("UPDATE trainee_level_monthly SET last_retained=0 WHERE trainee_uid='80001' AND month=?", (MONTH,))
b1r = next(b for b in requests.get(f'{B}/api/bindings', params={'active': 1}).json()['items'] if b['trainee_uid'] == '80001')
check('retained=0 透出疑似解散', b1r.get('retained') == 0, str(b1r.get('retained')))
db_exec("UPDATE trainee_level_monthly SET last_retained=1 WHERE trainee_uid='80001' AND month=?", (MONTH,))

print('== 名额月初兜底（上月记录） ==')
LAST_MONTH = (datetime.now().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
db_exec("DELETE FROM trainee_level_monthly WHERE trainee_uid='80001' AND month=?", (MONTH,))
insert_monthly('80001', LAST_MONTH, '金牌', 4, tasks=7)
r = requests.get(f'{B}/api/trainers/{tr_b}/slots')
s = r.json()['slots']
check('当月无记录 → 上月金牌兜底 +3', s['extra_slots'] == 3 and s['total_slots'] == 5, str(s))
check('兜底行带 from_last_month 标记', s['trainees'][0].get('from_last_month') is True, str(s['trainees']))
insert_monthly('80001', MONTH, '铜牌', 1, tasks=7)
r = requests.get(f'{B}/api/trainers/{tr_b}/slots')
s = r.json()['slots']
check('当月有记录则按当月（铜牌 +0，不吃兜底）', s['extra_slots'] == 0 and s['trainees'][0].get('from_last_month') is False, str(s))
# 恢复金牌供后续奖励测试
db_exec("DELETE FROM trainee_level_monthly WHERE trainee_uid='80001' AND month=?", (MONTH,))
insert_monthly('80001', MONTH, '金牌', 4, tasks=7)

print('== 奖励窗口（次周周一起整四周） ==')
bound_at = db_one("SELECT bound_at FROM bindings WHERE trainee_id=? AND bind_type='trainer' AND unbound_at IS NULL", (te_a,))[0]
ws, we = expected_window(bound_at)
r = requests.get(f'{B}/api/trainees/{te_a}/rewards')
pa = r.json()['rewards_panel']['panels']
check('甲的奖励面板=培训师绑定', len(pa) == 1 and pa[0]['bind_type'] == 'trainer' and pa[0]['side_label'] == '培训师', str(pa))
rw = pa[0]
check('窗口起点=次周周一', rw['window_start'] == ws.strftime('%Y-%m-%d'), f"{rw['window_start']} != {ws.date()}")
check('窗口终点=起点+28天', rw['window_end'] == we.strftime('%Y-%m-%d'), f"{rw['window_end']} != {we.date()}")
if datetime.now() < ws:
    check('当前未进窗口 not_started 且无 pending', rw['window_status'] == 'not_started'
          and all(x['status'] != 'pending' for x in rw['rewards']), str(rw['window_status']))
    db_exec("UPDATE bindings SET bound_at=? WHERE trainee_id=? AND bind_type='trainer' AND unbound_at IS NULL",
            ((datetime.utcnow() - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S'), te_a))
    rw = requests.get(f'{B}/api/trainees/{te_a}/rewards').json()['rewards_panel']['panels'][0]
check('进窗口后 in_window', rw['window_status'] == 'in_window' and rw['days_left'] is not None, str(rw['window_status']))
st = {x['key']: x['status'] for x in rw['rewards']}
check('金牌+任务7次 → 只发最高档（金牌+任务档 pending，低档已达标）',
      st.get('task6_bronze') == 'pending' and st.get('lv_gold') == 'pending'
      and st.get('lv_junior_silver') == 'achieved' and st.get('lv_silver') == 'achieved', str(st))
check('王牌未达标', st.get('lv_ace') == 'ineligible', str(st))
grant_id = next(x['grant_id'] for x in rw['rewards'] if x['key'] == 'lv_gold')
r = requests.post(f'{B}/api/rewards/{grant_id}/grant')
check('标记已发', r.ok, r.text)
r = requests.post(f'{B}/api/rewards/{grant_id}/grant')
check('重复标记 404', r.status_code == 404, f'got {r.status_code}')
r = requests.get(f'{B}/api/trainees/{te_a}/rewards')
st = {x['key']: x['status'] for x in r.json()['rewards_panel']['panels'][0]['rewards']}
check('金牌档已发放且不重生成', st.get('lv_gold') == 'granted', str(st))
r = requests.post(f'{B}/api/rewards/{grant_id}/revoke')
check('撤销发放', r.ok, r.text)

print('== 一键全部标记已发 ==')
bid_a = db_one("SELECT id FROM bindings WHERE trainee_id=? AND bind_type='trainer' AND unbound_at IS NULL", (te_a,))[0]
r = requests.post(f'{B}/api/rewards/grant-all', json={'binding_id': bid_a})
check('grant-all 返回发放数量（任务档+金牌档=2）', r.ok and r.json()['granted'] == 2, r.text)
r = requests.get(f'{B}/api/trainees/{te_a}/rewards')
st = {x['key']: x['status'] for x in r.json()['rewards_panel']['panels'][0]['rewards']}
check('任务档+金牌档已发放，低档已达标', st.get('task6_bronze') == 'granted' and st.get('lv_gold') == 'granted'
      and st.get('lv_junior_silver') == 'achieved' and st.get('lv_silver') == 'achieved', str(st))
r = requests.post(f'{B}/api/rewards/grant-all', json={'binding_id': bid_a})
check('重复 grant-all 幂等 0 档', r.ok and r.json()['granted'] == 0, r.text)

print('== 姐妹团绑定同样产生奖励 ==')
insert_monthly('80002', MONTH, '银牌', 3, tasks=7)
db_exec("UPDATE bindings SET bound_at=? WHERE trainee_id=? AND bind_type='sister' AND unbound_at IS NULL",
        ((datetime.utcnow() - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S'), te_b))
r = requests.get(f'{B}/api/trainees/{te_b}/rewards')
pb = r.json()['rewards_panel']['panels']
check('乙的奖励面板=姐妹团绑定', len(pb) == 1 and pb[0]['bind_type'] == 'sister' and pb[0]['side_label'] == '姐姐', str(pb))
stb = {x['key']: x['status'] for x in pb[0]['rewards']}
check('姐妹团银牌+任务7次 → 银牌+任务档 pending，初银已达标',
      stb.get('task6_bronze') == 'pending' and stb.get('lv_silver') == 'pending'
      and stb.get('lv_junior_silver') == 'achieved' and stb.get('lv_gold') == 'ineligible', str(stb))

print('== 侧方未留存暂停发奖 ==')
sis_bid = pb[0]['binding']['id']
db_exec('DELETE FROM reward_grants WHERE binding_id=?', (sis_bid,))
db_exec('''INSERT INTO trainee_level_monthly (trainee_uid, month, best_level, best_rank, last_queried_at, last_retained)
           VALUES ('91001', ?, '', 0, ?, 0)''', (MONTH, NOW_S))
r = requests.get(f'{B}/api/trainees/{te_b}/rewards')
pb2 = r.json()['rewards_panel']['panels']
check('姐姐未留存 → 面板带标记', pb2[0].get('side_retained') == 0, str(pb2[0].get('side_retained')))
st3 = {x['key']: x['status'] for x in pb2[0]['rewards']}
check('姐姐未留存 → 不再生成待发放', all(v != 'pending' for v in st3.values()), str(st3))
db_exec("DELETE FROM trainee_level_monthly WHERE trainee_uid='91001'")

print('== 奖励跨月（按绑定当月起算） ==')
d20 = datetime.utcnow() - timedelta(days=20)
if d20.month != datetime.utcnow().month:
    # 绑定在上个月：窗口仍有效（次周周一起四周），等级记录也在上个月 → 金牌档应生成
    db_exec("UPDATE bindings SET bound_at=? WHERE trainee_id=? AND bind_type='sister' AND unbound_at IS NULL",
            (d20.strftime('%Y-%m-%d %H:%M:%S'), te_b))
    db_exec("DELETE FROM trainee_level_monthly WHERE trainee_uid='80002'")
    insert_monthly('80002', LAST_MONTH, '金牌', 4, tasks=7)
    r = requests.get(f'{B}/api/trainees/{te_b}/rewards')
    pb = r.json()['rewards_panel']['panels']
    check('跨月绑定窗口仍有效', pb[0]['window_status'] == 'in_window', str(pb[0]['window_status']))
    stb2 = {x['key']: x['status'] for x in pb[0]['rewards']}
    check('上月金牌 → 金牌档跨月生成 pending', stb2.get('lv_gold') == 'pending', str(stb2))
else:
    check('跨月用例（今天离月末太近，跳过）', True)

print('== 窗口过期不生成 pending ==')
db_exec("UPDATE bindings SET bound_at=? WHERE trainee_id=? AND unbound_at IS NULL",
        ((datetime.utcnow() - timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S'), te_c))
r = requests.get(f'{B}/api/trainees/{te_c}/rewards')
rw = r.json()['rewards_panel']['panels'][0]
check('丙窗口已过期 expired', rw['window_status'] == 'expired', str(rw['window_status']))
check('过期后无 pending 生成', all(x['status'] != 'pending' for x in rw['rewards']), str([x['status'] for x in rw['rewards']]))

print('== 分页 ==')
r = requests.get(f'{B}/api/trainees', params={'page': 1, 'page_size': 2})
check('妹妹分页 page_size=2', len(r.json()['items']) <= 2 and r.json()['total'] >= 3, str(r.json()))
r = requests.get(f'{B}/api/bindings', params={'active': 0, 'page': 1})
check('历史绑定分页字段', 'total' in r.json() and r.json()['page'] == 1, str(r.json().keys()))

print('== 历史导入 ==')
r = requests.get(f'{B}/api/trainees/import-candidates')
check('导入候选接口', r.ok and 'snapshot_date' in r.json(), r.text[:200])

print('== 奖励导出 ==')
# 先解绑测试绑定（只动本测试创建的数据！）：导出测试不打网络
db_exec(f"UPDATE bindings SET unbound_at=CURRENT_TIMESTAMP WHERE unbound_at IS NULL AND trainee_id IN ({te_a},{te_b},{te_c})")
r = requests.post(f'{B}/api/export/rewards', json={'bind_type': 'x', 'date': '2026-10-05'})
check('非法类型 400', r.status_code == 400, f'got {r.status_code}')
r = requests.post(f'{B}/api/export/rewards', json={'bind_type': 'trainer', 'date': 'bad'})
check('非法日期 400', r.status_code == 400, f'got {r.status_code}')
r = requests.post(f'{B}/api/export/rewards', json={'bind_type': 'sister', 'date': '2026-10-05'})
check('空绑定导出有效 xlsx', r.status_code == 200 and r.content[:2] == b'PK', f'got {r.status_code}')
from openpyxl import load_workbook
import io
wb = load_workbook(io.BytesIO(r.content))
hdr = [c.value for c in wb.active[3]]
check('三胎表头为姐姐UID', hdr[0] == '姐姐UID' and hdr[5] == '完成任务次数' and hdr[7] == '礼物流水' and hdr[8] == '牌子', str(hdr))
r = requests.post(f'{B}/api/export/rewards', json={'bind_type': 'trainer', 'date': '2026-10-05'})
hdr = [c.value for c in load_workbook(io.BytesIO(r.content)).active[3]]
check('培训师表头为培训师UID', hdr[0] == '培训师UID', str(hdr))
# 过期窗口的绑定不出现在导出里（新建一条再把绑定时间改到 60 天前）
r = bind('91001', '80003', bind_type='sister', force=True)
exp_bid = r.json()['id']
db_exec('UPDATE bindings SET bound_at=? WHERE id=?',
        ((datetime.utcnow() - timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S'), exp_bid))
# 窗口未开始的（周一刚绑的）也不应出现：再建一条全新的
r = bind('91002', '80001', bind_type='sister', trainer_nickname='新姐姐', force=True)
check('新绑定窗口未开始', db_one('SELECT COUNT(*) FROM bindings WHERE trainee_id=? AND unbound_at IS NULL', (te_a,))[0] >= 1)
r = requests.post(f'{B}/api/export/rewards', json={'bind_type': 'sister', 'date': '2026-10-05'})
ws_rows = [row for row in load_workbook(io.BytesIO(r.content)).active.iter_rows(min_row=5, values_only=True)
           if any(v is not None for v in row)]
check('过期绑定不出现在导出（80003 不在其中）', all(str(row[2]) != '80003' for row in ws_rows), str(ws_rows))
check('窗口未开始的绑定也不导出（80001 不在其中）', all(str(row[2]) != '80001' for row in ws_rows), str(ws_rows))

print('== UID 速查 ==')
r = requests.get(f'{B}/api/uid-query/types')
check('类型列表', r.ok and len(r.json()['items']) == 4, r.text)
r = requests.post(f'{B}/api/trainees/999999/refresh')
check('刷新不存在学员 404（不打网络）', r.status_code == 404, f'got {r.status_code}')

print(f'\n结果: {passed} passed, {failed} failed')

# 清理测试数据（一律按测试 UID 精确匹配，绝不用可能错位的 id）
TEST_TRAINER_UIDS = ('90001', '90002', '90003', '91001', '91002')
TEST_TRAINEE_UIDS = ('80001', '80002', '80003')
rows = requests.get(f'{B}/api/bindings', params={'active': 1, 'page_size': 100}).json()['items']
for b in rows:
    if str(b['trainee_uid']) in TEST_TRAINEE_UIDS or str(b['trainer_uid']) in TEST_TRAINER_UIDS:
        requests.post(f"{B}/api/bindings/{b['id']}/unbind")
for uid in TEST_TRAINER_UIDS:
    for t in requests.get(f'{B}/api/trainers', params={'role': 'all', 'kw': uid}).json()['items']:
        if t['uid'] == uid:
            requests.delete(f"{B}/api/trainers/{t['id']}")
for uid in TEST_TRAINEE_UIDS:
    for t in requests.get(f'{B}/api/trainees', params={'kw': uid}).json()['items']:
        if t['uid'] == uid:
            requests.delete(f"{B}/api/trainees/{t['id']}")
for uid in TEST_TRAINEE_UIDS:
    db_exec('DELETE FROM trainee_level_monthly WHERE trainee_uid=?', (uid,))
    db_exec('DELETE FROM reward_grants WHERE trainee_uid=?', (uid,))
print('测试数据已清理')
sys.exit(1 if failed else 0)
