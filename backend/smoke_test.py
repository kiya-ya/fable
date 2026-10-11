# -*- coding: utf-8 -*-
"""API 冒烟测试（自清理测试数据）。运行: .venv/Scripts/python.exe -X utf8 backend/smoke_test.py"""
import os
import sqlite3
import sys
from datetime import datetime

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


def db_exec(sql, params=()):
    conn = sqlite3.connect(DB)
    conn.execute(sql, params)
    conn.commit()
    conn.close()


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
r = requests.post(f'{B}/api/trainers', json={'nickname': '缺UID'})
check('缺 UID 400', r.status_code == 400, f'got {r.status_code}')
r = requests.put(f'{B}/api/trainers/{tr_b}', json={'uid': '90002', 'nickname': '测试培训师B改', 'status': 'active', 'note': '备注', 'base_slots': 3})
check('编辑培训师B', r.ok, r.text)
r = requests.get(f'{B}/api/trainers', params={'kw': 'B改'})
check('搜索培训师', r.ok and len(r.json()['items']) == 1, r.text)
r = requests.get(f'{B}/api/trainers')
item_a = next((t for t in r.json()['items'] if t['uid'] == '90001'), None)
check('列表带名额字段 total_slots=2', item_a and item_a['total_slots'] == 2, str(item_a))

print('== 妹妹 CRUD ==')
r = requests.post(f'{B}/api/trainees', json={'uid': '80001', 'nickname': '测试妹妹甲', 'hall_name': '游戏一厅'})
check('新增妹妹甲', r.ok, r.text)
te_a = r.json().get('id')
r = requests.post(f'{B}/api/trainees', json={'uid': '80002', 'nickname': '测试妹妹乙'})
check('新增妹妹乙', r.ok, r.text)
te_b = r.json().get('id')

print('== 绑定流程 ==')
r = requests.post(f'{B}/api/bindings', json={'trainer_id': tr_a, 'trainee_id': te_a, 'note': '首绑'})
check('绑定 A<-甲', r.ok and r.json().get('id'), r.text)
r = requests.post(f'{B}/api/bindings', json={'trainer_id': tr_b, 'trainee_id': te_a})
check('重复绑定冲突 409', r.status_code == 409 and r.json().get('conflict'), f'got {r.status_code} {r.text}')
r = requests.post(f'{B}/api/bindings', json={'trainer_id': tr_b, 'trainee_id': te_a, 'force': True})
check('强制换绑 B<-甲', r.ok and r.json().get('rebound'), r.text)
r = requests.get(f'{B}/api/bindings', params={'active': 1})
items = [b for b in r.json()['items'] if b['trainee_uid'] == '80001']
check('生效绑定仅 1 条且是 B<-甲', len(items) == 1 and items[0]['trainer_uid'] == '90002', str(items))
r = requests.get(f'{B}/api/bindings', params={'active': 0})
check('历史含解绑记录', any(b['trainee_uid'] == '80001' and b['unbound_at'] for b in r.json()['items']), r.text)
r = requests.get(f'{B}/api/trainers/{tr_b}/trainees')
check('查 B 在带妹妹', len(r.json()['items']) == 1 and r.json()['items'][0]['uid'] == '80001', r.text)
r = requests.delete(f'{B}/api/trainers/{tr_b}')
check('有生效绑定禁止删除 409', r.status_code == 409, f'got {r.status_code}')

print('== 名额判定 ==')
r = requests.post(f'{B}/api/bindings', json={'trainer_id': tr_a, 'trainee_id': te_b})
check('绑定 A<-乙', r.ok, r.text)
r = requests.get(f'{B}/api/trainers/{tr_a}/slots')
s = r.json()['slots']
check('无等级记录时 总名额=基础2', s['base_slots'] == 2 and s['extra_slots'] == 0 and s['total_slots'] == 2, str(s))
# 直接落库月度等级：乙 当月金牌（rank4 → +3）
db_exec('''INSERT INTO trainee_level_monthly (trainee_uid, month, best_level, best_rank, last_week_level, last_daily_task_count, last_queried_at)
           VALUES ('80002', ?, '金牌', 4, '金牌', 7, ?)''', (MONTH, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
r = requests.get(f'{B}/api/trainers/{tr_a}/slots')
s = r.json()['slots']
check('金牌学员 +3 → 总名额 5（封顶）', s['extra_slots'] == 3 and s['total_slots'] == 5, str(s))
check('名额面板含学员明细', len(s['trainees']) == 1 and s['trainees'][0]['slot_plus'] == 3, str(s))

print('== 奖励判定 ==')
r = requests.get(f'{B}/api/trainees/{te_b}/rewards')
rw = r.json()['rewards_panel']
check('奖励面板在窗口期内', rw['in_window'] and rw['days_left'] <= 28, str(rw))
st = {x['key']: x['status'] for x in rw['rewards']}
check('金牌+任务7次 → 四档待发放', st.get('task6_bronze') == 'pending' and st.get('lv_junior_silver') == 'pending'
      and st.get('lv_silver') == 'pending' and st.get('lv_gold') == 'pending', str(st))
check('王牌未达标', st.get('lv_ace') == 'ineligible', str(st))
grant_id = next(x['grant_id'] for x in rw['rewards'] if x['key'] == 'lv_gold')
r = requests.post(f'{B}/api/rewards/{grant_id}/grant')
check('标记已发', r.ok, r.text)
r = requests.post(f'{B}/api/rewards/{grant_id}/grant')
check('重复标记 404', r.status_code == 404, f'got {r.status_code}')
r = requests.get(f'{B}/api/trainees/{te_b}/rewards')
st = {x['key']: x['status'] for x in r.json()['rewards_panel']['rewards']}
check('金牌档已发放且不重生成', st.get('lv_gold') == 'granted', str(st))
r = requests.post(f'{B}/api/rewards/{grant_id}/revoke')
check('撤销发放', r.ok, r.text)

print('== 解绑与删除 ==')
r = requests.get(f'{B}/api/bindings', params={'active': 1})
bid_a = next(b['id'] for b in r.json()['items'] if b['trainee_uid'] == '80002')
r = requests.post(f'{B}/api/bindings/{bid_a}/unbind')
check('解绑 A<-乙', r.ok, r.text)
r = requests.post(f'{B}/api/bindings/{bid_a}/unbind')
check('重复解绑 404', r.status_code == 404, f'got {r.status_code}')
r = requests.delete(f'{B}/api/trainers/{tr_a}')
check('解绑后可删除培训师A', r.ok, r.text)
bid_b = next(b['id'] for b in requests.get(f'{B}/api/bindings', params={'active': 1}).json()['items'] if b['trainee_uid'] == '80001')
requests.post(f'{B}/api/bindings/{bid_b}/unbind')
r = requests.delete(f'{B}/api/trainers/{tr_b}')
check('解绑后可删除培训师B', r.ok, r.text)

print('== 历史导入 ==')
r = requests.get(f'{B}/api/trainees/import-candidates')
check('导入候选接口', r.ok and 'snapshot_date' in r.json(), r.text[:200])
cands = [c for c in r.json()['items'] if not c['already']][:2]
if cands:
    r = requests.post(f'{B}/api/trainees/import', json={'uids': [c['uid'] for c in cands]})
    check('批量导入', r.ok and r.json()['imported'] == len(cands), r.text)
    for c in cands:
        tid = next((t['id'] for t in requests.get(f'{B}/api/trainees', params={'kw': c['uid']}).json()['items'] if t['uid'] == c['uid']), None)
        if tid:
            requests.delete(f'{B}/api/trainees/{tid}')
else:
    check('批量导入（无可导入候选，跳过）', True)

print('== UID 速查 ==')
r = requests.get(f'{B}/api/uid-query/types')
check('类型列表', r.ok and len(r.json()['items']) == 4, r.text)

print(f'\n结果: {passed} passed, {failed} failed')

# 清理测试数据（含月度等级与奖励记录）
for tid in (te_a, te_b):
    requests.delete(f'{B}/api/trainees/{tid}')
for uid in ('80001', '80002'):
    db_exec('DELETE FROM trainee_level_monthly WHERE trainee_uid=?', (uid,))
    db_exec('DELETE FROM reward_grants WHERE trainee_uid=?', (uid,))
print('测试数据已清理')
sys.exit(1 if failed else 0)
