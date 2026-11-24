#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""点点开黑导师资质查询：只返回点点姐妹团和培训师，不包含其他游戏。"""
import json
import os

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_FILE = os.path.join(PROJECT_ROOT, 'data', 'qualification_cookies.json')
API_URL = 'https://captain-api.tuwan.com/admin/qualification/applyList'
SUPPORTED_GAMES = {'点点姐妹团': 'sister', '培训师': 'trainer'}


def _cookie_header():
    if not os.path.exists(COOKIE_FILE):
        raise RuntimeError('未配置兔玩登录凭据，请先完成平台登录')
    with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    cookies = data if isinstance(data, list) else data.get('cookies', data.get('data', {}).get('cookies', []))
    pairs = []
    for cookie in cookies:
        domain = str(cookie.get('domain', ''))
        if 'tuwan.com' not in domain:
            continue
        name = str(cookie.get('name', ''))
        value = str(cookie.get('value', ''))
        if name and value:
            pairs.append(f'{name}={value}')
    if not pairs:
        raise RuntimeError('兔玩登录凭据为空或已失效，请重新登录')
    return '; '.join(pairs)


def query_qualifications(uid):
    response = requests.get(API_URL, params={'uid': str(uid), 'page': 1, 'pageSize': 100, 'status': ''},
                            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                                     'Referer': 'https://y.tuwan.com/home/examine',
                                     'Cookie': _cookie_header()}, timeout=30)
    if response.status_code in (401, 403):
        raise RuntimeError('兔玩登录已失效，请重新登录后再查询')
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as e:
        raise RuntimeError('兔玩资质接口返回异常，可能需要重新登录') from e
    if payload.get('code') != 0:
        raise RuntimeError(payload.get('message') or '兔玩资质查询失败')

    records = (payload.get('data') or {}).get('records') or []
    latest = {}
    for row in records:
        game = row.get('applyGame')
        if game in SUPPORTED_GAMES:
            key = SUPPORTED_GAMES[game]
            if key not in latest or int(row.get('applyId') or 0) > int(latest[key].get('applyId') or 0):
                latest[key] = row
    nickname = ''
    if latest:
        nickname = max(latest.values(), key=lambda row: int(row.get('applyId') or 0)).get('nickname') or ''
    result = {'source': 'https://y.tuwan.com/home/examine', 'nickname': nickname}
    for game, key in SUPPORTED_GAMES.items():
        row = latest.get(key)
        if not row:
            result[key] = {'approved': False, 'status': '未查询到申请', 'passed_at': '', 'apply_id': None}
            continue
        status = row.get('applyStausStr') or ''
        result[key] = {
            'approved': row.get('applyStaus') == 0 or status == '审核通过',
            'status': status or '未知状态',
            'passed_at': row.get('passTime') or '',
            'apply_id': row.get('applyId'),
        }
    return result
