#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cookie 自动登录模块

通过 ddddocr OCR 识别 server1 验证码，自动登录两套外部系统并刷新 Cookie：
  - UID查询（server1 织梦）    ：login.php 登录 → 写 data/cookie.json
  - 数据抓取（bigdata.tuwan.com）：server1 登录 → SSO 令牌换 bigdata 会话 → 写 data/cookie_bigdata.json

两套系统共用 server1 的 zhangty 账号 + 一个验证码（vdimgck 英文数字）。
bigdata 不走邮箱/密码/中文验证码，而是 server1 生成的 secret_token 单点登录（SSO）。

账号密码存 data/login_credentials.json（已 gitignore，不提交真实密码）。
"""
import os
import re
import json
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
CRED_FILE = os.path.join(DATA_DIR, 'login_credentials.json')
COOKIE_UID = os.path.join(DATA_DIR, 'cookie.json')
COOKIE_BIGDATA = os.path.join(DATA_DIR, 'cookie_bigdata.json')

BASE1 = 'http://server1.tuwan.com:10010'
BIGDATA = 'https://bigdata.tuwan.com'
# server1 的 HTTP Basic 鉴权头（静态，base64("2018:2018tuwantengfei")）
BASIC = 'MjAxODoyMDE4dHV3YW50ZW5nZmVp'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

MAX_RETRY = 6  # 验证码读错时的最大重试次数

try:
    import ddddocr
    _OCR = ddddocr.DdddOcr(show_ad=False)
except Exception as e:  # ddddocr 未安装时降级，登录会报错提示
    _OCR = None
    _OCR_ERR = str(e)


def _load_credentials():
    """从 data/login_credentials.json 读取账号密码"""
    try:
        with open(CRED_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get('userid', 'zhangty'), cfg.get('pwd', '')
    except Exception:
        return 'zhangty', ''


def _server1_session():
    """新建一个带 Basic 鉴权头的 server1 会话"""
    s = requests.Session()
    s.verify = False
    s.headers.update({'User-Agent': UA, 'Authorization': f'Basic {BASIC}'})
    return s


def _server1_login():
    """登录 server1（织梦），返回带登录态的会话。失败抛异常。"""
    if _OCR is None:
        raise RuntimeError(f'ddddocr 未安装，无法识别验证码: {_OCR_ERR}')
    userid, pwd = _load_credentials()
    if not pwd:
        raise RuntimeError('未配置登录密码，请检查 data/login_credentials.json')

    last_err = None
    for _ in range(MAX_RETRY):
        s = _server1_session()
        try:
            # 1. 访问登录页建立 PHPSESSID；2. 同一会话拉验证码图；3. 提交登录
            s.get(f'{BASE1}/fly2013/login.php', timeout=30)
            img = s.get(f'{BASE1}/include/vdimgck.php', timeout=30).content
            code = _OCR.classification(img)
            s.post(f'{BASE1}/fly2013/login.php', data={
                'dopost': 'login',
                'gotopage': '/fly2013/',
                'adminstyle': 'newdedecms',
                'userid': userid,
                'pwd': pwd,
                'validate': code,
            }, timeout=30, allow_redirects=True)
            # 登录成功会写入 DedeUserID 等织梦会话 cookie
            if 'DedeUserID' in [c.name for c in s.cookies]:
                return s
        except Exception as e:
            last_err = e
    raise RuntimeError(f'server1 登录失败（重试 {MAX_RETRY} 次）: {last_err}')


def _session_cookie_str(s: requests.Session) -> str:
    return '; '.join(f'{c.name}={c.value}' for c in s.cookies)


def _bigdata_sso(server1_session) -> str:
    """用已登录的 server1 会话换 bigdata 会话，返回 bigdata cookie 串（只需 PHPSESSID）"""
    # 1. server1 的入口页会 JS 跳转到 tuwanLogin?secret_token=...
    r = server1_session.get(f'{BASE1}/fly2013/bigdata_report_enter.php', timeout=30)
    m = re.search(r'secret_token=([^"\']+)', r.text)
    if not m:
        raise RuntimeError('bigdata_report_enter.php 中未找到 secret_token，server1 会话可能已失效')
    token_enc = m.group(1)

    # 2. 访问 tuwanLogin 拿到自动提交表单（含 secret_token + 随机隐藏字段）
    s2 = requests.Session()
    s2.verify = False
    s2.headers.update({'User-Agent': UA})
    r2 = s2.get(f'{BIGDATA}/login/tuwanLogin?secret_token={token_enc}', timeout=30)
    fields = re.findall(
        r'<input[^>]+type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
        r2.text, re.I)
    data = {name: value for name, value in fields}
    if 'secret_token' not in data:
        raise RuntimeError('tuwanLogin 表单缺少 secret_token 字段')

    # 3. 提交到 tuwanTokenLogin，服务端把 PHPSESSID 会话标记为已登录
    s2.post(f'{BIGDATA}/login/tuwanTokenLogin', data=data, timeout=30, allow_redirects=True)
    return _session_cookie_str(s2)


def _write_json(path, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def refresh_uid_cookie() -> str:
    """登录 UID 查询系统并刷新 data/cookie.json，返回新 cookie 串"""
    s1 = _server1_login()
    cookie_str = _session_cookie_str(s1)
    _write_json(COOKIE_UID, {
        'cookie_str': cookie_str,
        'basic_auth': BASIC,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'auto-login',
    })
    return cookie_str


def refresh_bigdata_cookie() -> str:
    """登录并刷新 data/cookie_bigdata.json，返回新 cookie 串"""
    s1 = _server1_login()
    cookie_str = _bigdata_sso(s1)
    _write_json(COOKIE_BIGDATA, {
        'cookie_str': cookie_str,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'auto-login',
    })
    return cookie_str


def refresh_all() -> dict:
    """一次性刷新两套 Cookie（共用一次 server1 登录），返回结果摘要"""
    try:
        s1 = _server1_login()
    except Exception as e:
        return {'uid': {'ok': False, 'msg': str(e)}, 'bigdata': {'ok': False, 'msg': str(e)}}

    result = {}
    # UID 查询：直接用 server1 织梦会话 cookie
    try:
        _write_json(COOKIE_UID, {
            'cookie_str': _session_cookie_str(s1),
            'basic_auth': BASIC,
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'auto-login',
        })
        result['uid'] = {'ok': True}
    except Exception as e:
        result['uid'] = {'ok': False, 'msg': str(e)}

    # 数据抓取：SSO 换 bigdata 会话
    try:
        _write_json(COOKIE_BIGDATA, {
            'cookie_str': _bigdata_sso(s1),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'auto-login',
        })
        result['bigdata'] = {'ok': True}
    except Exception as e:
        result['bigdata'] = {'ok': False, 'msg': str(e)}

    return result


if __name__ == '__main__':
    print('=' * 60)
    print('Cookie 自动登录测试')
    print('=' * 60)
    res = refresh_all()
    for key, val in res.items():
        status = 'OK' if val.get('ok') else 'FAIL'
        msg = '' if val.get('ok') else f'  -> {val.get("msg")}'
        print(f'[{key}] {status}{msg}')
