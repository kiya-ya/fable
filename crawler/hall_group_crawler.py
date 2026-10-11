#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组→厅 层级爬虫（一次性缓存）

数据源：server1 `play_activity_captain_score_v2.php`（队长积分排行列表）。
页面顶部「类型」下拉（typeid）选项：
  1  端游队长周排行    2  王者队长周排行    3  和平队长周排行
  5  娱乐队长周排行    6  LOLm队长周排行   7  狼人杀队长周排行
  8  谁是卧底周排行    9  乐园杀周排行     10 三角洲周排行

需求口径：只抓 王者(2)/和平(3)/娱乐(5) 三类；其余 typeid 全部归入「其他」。
表结构：排名 / 队长UID / 队长昵称 / 所属厅 / 定级 / 分组 / …（所属厅=子集，分组=父集）。

产出：data/hall_groups.json（一次性缓存，落地后前端直接读、不再重复抓）
{
  "_meta": {"source": ..., "date": ..., "crawled_at": ...},
  "王者队长周排行": { "<分组>": ["<所属厅>", ...], ... },
  "和平队长周排行": { ... },
  "娱乐队长周排行": { ... },
  "其他": { ... }          # 由 typeid 1/6/7/8/9/10 合并
}
"""
import os
import re
import json
import html as _html
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
COOKIE_FILE = os.path.join(DATA_DIR, 'cookie.json')
OUT_FILE = os.path.join(DATA_DIR, 'hall_groups.json')

BASE = 'http://server1.tuwan.com:10010/fly2013/play_activity_captain_score_v2.php'
BASIC = 'MjAxODoyMDE4dHV3YW50ZW5nZmVp'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

# 三个重点类型（用户点名要的）→ 各自的顶层桶
PRIMARY = {'2': '王者队长周排行', '3': '和平队长周排行', '5': '娱乐队长周排行'}
# 其余类型全部归入「其他」
OTHER_TYPEIDS = ['1', '6', '7', '8', '9', '10']

ROW_RE = re.compile(r'<tr[^>]*class="title_\d+"[^>]*>(.*?)</tr>', re.S)
TD_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
TAG_RE = re.compile(r'<[^>]+>')
DATE_RE = re.compile(r'<select[^>]*name=["\']date["\'][^>]*>(.*?)</select>', re.S)
OPT_RE = re.compile(r'<option[^>]*value=["\']([^"\']*)["\']', re.S)


def _load_cookie():
    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        cookie = cfg.get('cookie_str', '')
        if not cookie:
            raise RuntimeError('data/cookie.json 无 cookie_str')
        return cookie
    except Exception as e:
        raise RuntimeError(f'读取 Cookie 失败：{e}（请先运行 crawler/auto_login.py）')


def _fetch(typeid, date):
    """抓取某个 typeid 的排行页，返回 HTML 文本（GBK → Unicode）。"""
    r = requests.get(
        BASE,
        params={'typeid': typeid, 'date': date},
        headers={'User-Agent': UA, 'Authorization': f'Basic {BASIC}', 'Cookie': _load_cookie()},
        timeout=60, verify=False)
    r.encoding = 'utf-8'  # 页面 meta/Content-Type 均为 charset=utf-8
    return r.text


def _latest_date(html):
    """从日期下拉里取第一个（最新周）选项。"""
    m = DATE_RE.search(html)
    if not m:
        return None
    opts = OPT_RE.findall(m.group(1))
    return opts[0] if opts else None


def _clean(s):
    s = _html.unescape(s)
    s = TAG_RE.sub('', s)
    s = s.replace('　', ' ').strip()
    return s


def _parse_rows(html):
    """从排行表解析出 (分组, 所属厅) 列表。"""
    pairs = []
    for rm in ROW_RE.finditer(html):
        cells = TD_RE.findall(rm.group(1))
        if len(cells) < 6:
            continue
        hall = _clean(cells[3])   # 所属厅
        group = _clean(cells[5])  # 分组
        if hall and group:
            pairs.append((group, hall))
    return pairs


def _group_halls(pairs):
    """(分组, 所属厅) → {分组: [所属厅...]}，去重保序。"""
    d = {}
    for group, hall in pairs:
        d.setdefault(group, {})
        d[group][hall] = True
    return {g: list(halls.keys()) for g, halls in d.items()}


def crawl() -> dict:
    cookie_ok = bool(_load_cookie())
    # 先抓 typeid=2 拿最新周日期
    probe = _fetch('2', '')
    date = _latest_date(probe) or '2026-08-24 - 2026-08-30'
    if not _parse_rows(probe):
        # 无参数时可能没渲染表格，带日期再试一次
        probe = _fetch('2', date)
        date = _latest_date(probe) or date

    result = {
        '王者队长周排行': {}, '和平队长周排行': {}, '娱乐队长周排行': {}, '其他': {},
    }
    stats = {}

    # 三个重点类型
    for typeid, name in PRIMARY.items():
        try:
            html = _fetch(typeid, date)
            pairs = _parse_rows(html)
            result[name] = _group_halls(pairs)
            stats[name] = {'groups': len(result[name]),
                           'halls': sum(len(v) for v in result[name].values())}
        except Exception as e:
            stats[name] = {'error': str(e)}

    # 其余类型合并进「其他」
    other = {}
    for typeid in OTHER_TYPEIDS:
        try:
            html = _fetch(typeid, date)
            pairs = _parse_rows(html)
            for group, hall in pairs:
                other.setdefault(group, {})
                other[group][hall] = True
        except Exception as e:
            stats[f'其他(typeid={typeid})'] = {'error': str(e)}
    result['其他'] = {g: list(h.keys()) for g, h in other.items()}
    stats['其他'] = {'groups': len(result['其他']),
                     'halls': sum(len(v) for v in result['其他'].values())}

    return {
        '_meta': {
            'source': BASE,
            'date': date,
            'crawled_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'cookie_ok': cookie_ok,
            'stats': stats,
        },
        '王者队长周排行': result['王者队长周排行'],
        '和平队长周排行': result['和平队长周排行'],
        '娱乐队长周排行': result['娱乐队长周排行'],
        '其他': result['其他'],
    }


def main():
    data = crawl()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    meta = data['_meta']
    print('=' * 60)
    print(f"组→厅 爬取完成 · 数据周 {meta['date']} · {meta['crawled_at']}")
    print('=' * 60)
    for name, s in meta['stats'].items():
        if 'error' in s:
            print(f'[{name}] 失败: {s["error"]}')
        else:
            print(f'[{name}] {s["groups"]} 组 · {s["halls"]} 厅')
    total_groups = sum(s.get('groups', 0) for s in meta['stats'].values())
    total_halls = sum(s.get('halls', 0) for s in meta['stats'].values())
    print(f'合计: {total_groups} 组 · {total_halls} 厅 → {OUT_FILE}')


if __name__ == '__main__':
    main()
