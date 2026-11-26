#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

try:
    from db import get_db
except ImportError:
    from crawler.db import get_db

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, 'data', 'ecology_config.json')
API_BASE = 'https://dd-manage-ui.tuwan.com/captain-manage/captainContribution'
LOGIN_BASE = 'https://dd-manage-ui.tuwan.com/backend'
AUTH_LOCK = threading.Lock()


def _load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def config_status():
    cfg = _load_config()
    return {
        'configured': bool(cfg.get('admin_token') or os.environ.get('ECOLOGY_ADMIN_TOKEN')),
        'auto_login': bool((cfg.get('username') and cfg.get('password')) or
                           (os.environ.get('ECOLOGY_USERNAME') and os.environ.get('ECOLOGY_PASSWORD'))),
        'updated_at': cfg.get('updated_at', ''),
        'source': cfg.get('source', ''),
    }


def save_admin_token(token, source='管理员后台更新'):
    token = str(token or '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise ValueError('请输入 Admin-Token')
    cfg = _load_config()
    cfg.update({
        'admin_token': token,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': source,
    })
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return config_status()


def _token():
    token = _load_config().get('admin_token') or os.environ.get('ECOLOGY_ADMIN_TOKEN')
    if not token:
        raise RuntimeError('未配置生态分接口 Admin-Token，请在生态分页面更新登录态')
    return token


def _captcha_answer(image_base64):
    import ddddocr
    text = ddddocr.DdddOcr(show_ad=False).classification(base64.b64decode(image_base64))
    match = re.search(r'(\d+)\s*([+\-*/×xX])\s*(\d+)', text)
    if not match:
        return None
    left, operator, right = match.groups()
    if operator == '+':
        return str(int(left) + int(right))
    if operator == '-':
        return str(int(left) - int(right))
    if operator in ('*', '×', 'x', 'X'):
        return str(int(left) * int(right))
    return str(int(left) // int(right))


def refresh_admin_token():
    cfg = _load_config()
    username = cfg.get('username') or os.environ.get('ECOLOGY_USERNAME')
    password = cfg.get('password') or os.environ.get('ECOLOGY_PASSWORD')
    if not username or not password:
        raise RuntimeError('生态分登录态已失效，且未配置自动登录账号')
    session = requests.Session()
    last_message = '验证码识别失败'
    for _ in range(6):
        captcha_resp = session.get(f'{LOGIN_BASE}/captchaImage', timeout=30)
        captcha_resp.raise_for_status()
        captcha = captcha_resp.json()
        answer = _captcha_answer(captcha.get('img', ''))
        if answer is None:
            continue
        response = session.post(f'{LOGIN_BASE}/login', json={
            'username': username, 'password': password, 'code': answer, 'uuid': captcha.get('uuid'),
        }, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get('token'):
            return save_admin_token(payload['token'], source='自动登录刷新')
        last_message = payload.get('msg') or '登录失败'
        if '验证码' not in last_message:
            break
    raise RuntimeError(f'生态分自动登录失败：{last_message}')


def _fetch_weeks_once(uid, week=None):
    params = {'week': week} if week else {}
    response = requests.get(
        f'{API_BASE}/weeks/{uid}',
        params=params,
        headers={
            'Authorization': f'Bearer {_token()}',
            'Accept': 'application/json',
            'Referer': 'https://dd-manage-ui.tuwan.com/',
            'User-Agent': 'Mozilla/5.0',
        },
        timeout=30,
    )
    if response.status_code in (401, 403):
        raise RuntimeError('生态分接口登录态已失效，请更新 Admin-Token')
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as e:
        raise RuntimeError('生态分接口返回异常，可能需要更新登录态') from e
    if payload.get('code') != 200:
        message = payload.get('msg') or payload.get('message') or '生态分查询失败'
        if 'token' in message.lower() or '登录' in message:
            raise RuntimeError('生态分接口登录态已失效，请更新 Admin-Token')
        raise RuntimeError(message)
    data = payload.get('data') or {}
    rows = data.get('rows') or []
    if not isinstance(rows, list):
        raise RuntimeError('生态分接口未返回有效周数据')
    return rows


def fetch_weeks(uid, week=None):
    failed_token = _load_config().get('admin_token', '')
    try:
        return _fetch_weeks_once(uid, week)
    except RuntimeError as e:
        if '登录态' not in str(e) and 'token' not in str(e).lower():
            raise
        with AUTH_LOCK:
            if _load_config().get('admin_token', '') == failed_token:
                refresh_admin_token()
        return _fetch_weeks_once(uid, week)


def normalize_row(uid, row):
    hints = row.get('hints') or []
    hint_items = row.get('hintItems') or []
    return {
        'uid': str(uid),
        'week_start': str(row.get('week') or '')[:10],
        'nickname': row.get('nickname') or '',
        'hall_name': row.get('hall') or '',
        'captain_type': row.get('captainType') or '',
        'level': row.get('level') or '',
        'level_change': row.get('levelChange') or 0,
        'eco_grade': row.get('ecoGrade') or '',
        'eco_grade_change': row.get('ecoGradeChange') or 0,
        'score': row.get('bonus'),
        'flow': row.get('flow'),
        'expense_ratio': row.get('expenseRatio'),
        'active_hall': row.get('bonusAtmos'),
        'event_score': row.get('bonusEvent'),
        'board_score': row.get('bonusBoard'),
        'acquire_score': row.get('bonusAcquire'),
        'arpu_score': row.get('bonusArpu'),
        'maintain_score': row.get('bonusMaintain'),
        'back_score': row.get('bonusBack'),
        'home_score': row.get('bonusHome'),
        'hints_json': json.dumps(hints, ensure_ascii=False),
        'eco_items_json': json.dumps(row.get('ecoItems') or {}, ensure_ascii=False),
        'raw_json': json.dumps(row, ensure_ascii=False),
        'hint_items': hint_items,
    }


def save_rows(uid, rows):
    columns = (
        'uid', 'week_start', 'nickname', 'hall_name', 'captain_type', 'level', 'level_change',
        'eco_grade', 'eco_grade_change', 'score', 'flow', 'expense_ratio', 'active_hall',
        'event_score', 'board_score', 'acquire_score', 'arpu_score', 'maintain_score',
        'back_score', 'home_score', 'hints_json', 'eco_items_json', 'raw_json',
    )
    normalized = [normalize_row(uid, row) for row in rows]
    conn = get_db()
    try:
        for item in normalized:
            if not item['week_start']:
                continue
            values = [item[column] for column in columns]
            updates = ','.join(f'{column}=excluded.{column}' for column in columns[2:])
            conn.execute(
                f'''INSERT INTO ecology_weekly ({','.join(columns)}, queried_at)
                    VALUES ({','.join('?' for _ in columns)}, CURRENT_TIMESTAMP)
                    ON CONFLICT(uid, week_start) DO UPDATE SET {updates}, queried_at=CURRENT_TIMESTAMP''',
                values,
            )
        conn.commit()
    finally:
        conn.close()
    return normalized


def sync_uid(uid, weeks=2, week=None):
    rows = fetch_weeks(uid, week=week)
    normalized = save_rows(uid, rows[:weeks])
    return {
        'uid': str(uid),
        'saved': len(normalized),
        'latest': normalized[0] if normalized else None,
    }


def sync_many(uids, weeks=2, workers=4, progress=None):
    unique_uids = list(dict.fromkeys(str(uid).strip() for uid in uids if str(uid).strip()))
    result = {'total': len(unique_uids), 'success': 0, 'failed': 0, 'saved': 0, 'errors': []}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(sync_uid, uid, weeks): uid for uid in unique_uids}
        for future in as_completed(futures):
            uid = futures[future]
            try:
                synced = future.result()
                result['success'] += 1
                result['saved'] += synced['saved']
                if progress:
                    progress(uid, True, synced['saved'], '')
            except Exception as e:
                error = str(e)
                result['failed'] += 1
                result['errors'].append({'uid': uid, 'msg': error})
                if progress:
                    progress(uid, False, 0, error)
    return result


if __name__ == '__main__':
    import sys
    target_uid = sys.argv[1] if len(sys.argv) > 1 else '34315471'
    print(json.dumps(sync_uid(target_uid, weeks=2), ensure_ascii=False, indent=2, default=str)[:4000])
