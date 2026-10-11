#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cookie 保活模块
原理：PHP session 因「不活跃」而过期。定时用已保存的 Cookie 访问一次两个系统的页面，
让服务端 session 保持活跃，Cookie 就能长期有效。
若检测到会话已失效（硬过期），则尝试调用 auto_login 自动重新登录（失效自愈）。
结果写入 data/keepalive_status.json，供前端 Cookie 管理面板展示。
"""
import os
import json
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings()

try:
    import auto_login
except ImportError:
    from crawler import auto_login

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
STATUS_FILE = os.path.join(DATA_DIR, 'keepalive_status.json')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'


def _load(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _check_uid() -> dict:
    """UID 查询系统（server1 dedecms）：访问查询页，看是否被踢回登录页"""
    cfg = _load(os.path.join(DATA_DIR, 'cookie.json'))
    cookie = cfg.get('cookie_str', '')
    if not cookie:
        return {'ok': False, 'msg': '未配置 Cookie'}
    basic = cfg.get('basic_auth', 'MjAxODoyMDE4dHV3YW50ZW5nZmVp')
    try:
        r = requests.get(
            'http://server1.tuwan.com:10010/fly2013/play_user_newcaptian.php',
            headers={'User-Agent': UA, 'Cookie': cookie, 'Authorization': f'Basic {basic}'},
            timeout=30, verify=False)
        r.encoding = r.apparent_encoding or 'utf-8'
        if '织梦内容管理系统' in r.text or 'login' in r.text.lower():
            return {'ok': False, 'msg': '会话已失效，请手动更新 Cookie'}
        return {'ok': True, 'msg': '保活成功'}
    except Exception as e:
        return {'ok': False, 'msg': f'请求失败: {e}'}


def _check_bigdata() -> dict:
    """数据抓取系统（bigdata）：访问统计页，看是否被踢回登录页"""
    cfg = _load(os.path.join(DATA_DIR, 'cookie_bigdata.json'))
    cookie = cfg.get('cookie_str', '')
    if not cookie:
        return {'ok': False, 'msg': '未配置 Cookie'}
    try:
        r = requests.get(
            'https://bigdata.tuwan.com/sisters/tj',
            headers={'User-Agent': UA, 'Cookie': cookie},
            timeout=30, verify=False)
        if '登录' in r.text and 'password' in r.text.lower():
            return {'ok': False, 'msg': '会话已失效，请手动更新 Cookie'}
        return {'ok': True, 'msg': '保活成功'}
    except Exception as e:
        return {'ok': False, 'msg': f'请求失败: {e}'}


def _auto_heal(check_fn, refresh_fn) -> dict:
    """会话失效时自动重登并复查，成功则标注「自动重登」"""
    try:
        refresh_fn()
        r = check_fn()
        if r.get('ok'):
            r['msg'] = '自动重登成功'
        return r
    except Exception as e:
        return {'ok': False, 'msg': f'自动重登失败: {e}'}


def run_keepalive() -> dict:
    """执行一次双系统保活；失效的自动重登自愈"""
    uid = _check_uid()
    bigdata = _check_bigdata()
    healed = {}

    if not uid['ok']:
        healed['uid'] = True
        uid = _auto_heal(_check_uid, auto_login.refresh_uid_cookie)
    if not bigdata['ok']:
        healed['bigdata'] = True
        bigdata = _auto_heal(_check_bigdata, auto_login.refresh_bigdata_cookie)

    result = {
        'last_run': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'uid': uid,
        'bigdata': bigdata,
        'auto_healed': healed,
    }
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'[Keepalive] 状态写入失败: {e}')
    status = 'OK' if result['uid']['ok'] and result['bigdata']['ok'] else 'FAIL'
    print(f"[Keepalive] {result['last_run']} UID:{'OK' if result['uid']['ok'] else 'FAIL'} "
          f"bigdata:{'OK' if result['bigdata']['ok'] else 'FAIL'} {status}")
    return result


if __name__ == '__main__':
    run_keepalive()
