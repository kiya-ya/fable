#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厅运营UID抓取模块
数据源: http://server1.tuwan.com:10010/fly2013/play_chatroom.php
功能: 抓取每个厅的厅运营UID，用于权限系统
"""
import os
import re
import json
import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings()

# Cookie 已脱敏（勿把真实会话 Cookie 提交进代码）；用环境变量 HALL_COOKIE 提供
HALL_COOKIE_STR = os.environ.get('HALL_COOKIE', '')

HALL_BASIC_AUTH = 'MjAxODoyMDE4dHV3YW50ZW5nZmVp'
HALL_BASE_URL = 'http://server1.tuwan.com:10010'
HALL_LIST_URL = f'{HALL_BASE_URL}/fly2013/play_chatroom.php'


class HallManagerCrawler:
    """厅运营UID抓取器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self._build_headers()

    def _build_headers(self):
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.0',
            'Cookie': HALL_COOKIE_STR,
            'Referer': HALL_LIST_URL,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Authorization': f'Basic {HALL_BASIC_AUTH}',
        })

    def fetch_hall_list(self, page=1):
        """抓取大厅列表页，提取每个厅的编辑链接"""
        url = f'{HALL_LIST_URL}?state=0&tpl_id=-10&list_type=0&gameid=0&title=&pageno={page}'
        print(f'[Hall-Crawl] 抓取大厅列表第{page}页: {url}')

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()

            if '织梦内容管理系统' in resp.text or 'login' in resp.text.lower():
                raise Exception('Cookie已过期，请重新登录')

            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.find_all('table')
            halls = []

            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    # 查找包含"修改"链接的行
                    edit_link = row.find('a', string='修改')
                    if edit_link:
                        href = edit_link.get('href', '')
                        # 提取id参数
                        match = re.search(r'id=(\d+)', href)
                        if match:
                            hall_id = match.group(1)
                            # 提取厅名（第2个td）
                            cells = row.find_all('td')
                            hall_name = ''
                            if len(cells) >= 2:
                                hall_name = cells[1].get_text(strip=True)

                            # 构建完整URL
                            if href.startswith('?'):
                                edit_url = f'{HALL_BASE_URL}/fly2013/play_chatroom.php{href}'
                            elif href.startswith('/'):
                                edit_url = f'{HALL_BASE_URL}{href}'
                            else:
                                edit_url = f'{HALL_BASE_URL}/fly2013/{href}'

                            halls.append({
                                'id': hall_id,
                                'name': hall_name,
                                'edit_url': edit_url
                            })

            # 检查总页数
            total_pages = 1
            pagelist = soup.find('div', class_='pagelistbox')
            if pagelist:
                text = pagelist.get_text()
                match = re.search(r'(\d+)条记录', text)
                if match:
                    total_records = int(match.group(1))
                    total_pages = (total_records + 19) // 20  # 每页约20条

            print(f'[Hall-Crawl] 第{page}页找到 {len(halls)} 个大厅')
            return halls, total_pages

        except Exception as e:
            print(f'[Hall-Crawl-ERROR] 抓取列表失败: {e}')
            raise

    def fetch_all_halls(self):
        """抓取所有页的大厅"""
        all_halls = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            halls, total_pages = self.fetch_hall_list(page)
            all_halls.extend(halls)
            if not halls or page >= total_pages:
                break
            page += 1
            import time
            time.sleep(0.3)

        print(f'[Hall-Crawl] 总共找到 {len(all_halls)} 个大厅')
        return all_halls

    def fetch_manager_uid(self, hall_id, hall_name=''):
        """抓取单个厅的编辑页，提取厅运营UID"""
        url = f'{HALL_BASE_URL}/fly2013/play_chatroom.php?dopost=save&id={hall_id}'
        print(f'[Hall-Crawl] 抓取厅运营UID: 厅ID={hall_id}, 厅名={hall_name}')

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()

            # 保存调试文件（仅前3个）
            debug_file = os.path.join(os.path.dirname(__file__), '..', f'debug_hall_{hall_id}.html')
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(resp.text)

            soup = BeautifulSoup(resp.text, 'html.parser')

            manager_uid = None
            found_hall_name = hall_name

            # 方法1: 查找input字段，name包含uid、manager、operator
            for input_tag in soup.find_all('input'):
                name = input_tag.get('name', '')
                value = input_tag.get('value', '')

                # 厅名（title字段）
                if name == 'title' and value:
                    found_hall_name = value.strip()

                # 厅运营UID（常见字段名）
                if name.lower() in ['uid', 'manager_uid', 'operator_uid', 'hall_uid', 'room_uid']:
                    if value and value.isdigit():
                        manager_uid = value.strip()
                        print(f'  → 找到UID字段 {name}={value}')

            # 方法2: 查找包含"运营"或"UID"的tr行
            if not manager_uid:
                for tr in soup.find_all('tr'):
                    tds = tr.find_all('td')
                    for i, td in enumerate(tds):
                        text = td.get_text(strip=True)
                        if '运营' in text or 'UID' in text or '管理' in text:
                            # 检查同行或相邻单元格
                            if i + 1 < len(tds):
                                val = tds[i + 1].get_text(strip=True)
                                if val and val.isdigit() and len(val) >= 5:
                                    manager_uid = val
                                    print(f'  → 从表格找到UID: {val}')
                                    break
                    if manager_uid:
                        break

            # 方法3: 从所有input中找纯数字UID
            if not manager_uid:
                for input_tag in soup.find_all('input', {'type': 'text'}):
                    value = input_tag.get('value', '')
                    if value and value.isdigit() and len(value) >= 5 and len(value) <= 12:
                        name = input_tag.get('name', '')
                        # 排除id字段
                        if name not in ['id', 'cid', 'hall_id', 'room_id']:
                            manager_uid = value
                            print(f'  → 从input找到UID: {name}={value}')
                            break

            return {
                'hall_id': hall_id,
                'hall_name': found_hall_name,
                'manager_uid': manager_uid,
            }

        except Exception as e:
            print(f'[Hall-Crawl-ERROR] 抓取厅 {hall_id} 失败: {e}')
            return {'hall_id': hall_id, 'hall_name': hall_name, 'manager_uid': None}

    def fetch_all(self):
        """抓取所有厅的运营UID"""
        print('=' * 60)
        print('厅运营UID抓取开始')
        print('=' * 60)

        # 1. 抓取所有大厅
        halls = self.fetch_all_halls()
        if not halls:
            print('[Hall-Crawl] 未找到任何大厅')
            return []

        # 2. 逐个抓取厅运营UID（只抓前3个测试）
        results = []
        for hall in halls[:3]:
            info = self.fetch_manager_uid(hall['id'], hall['name'])
            if info['manager_uid']:
                results.append(info)
            import time
            time.sleep(0.5)

        print(f'\n[Hall-Crawl] 测试抓取完成: {len(results)}/{len(halls[:3])} 个厅有运营UID')
        return results

    def save_to_db(self, results):
        """保存到数据库"""
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'stats.db')
        conn = sqlite3.connect(db_path)

        # 确保users表有hall_name字段
        try:
            conn.execute('ALTER TABLE users ADD COLUMN hall_name TEXT')
            print('[DB] 已添加 hall_name 字段')
        except Exception:
            pass

        added = 0
        for r in results:
            if not r['manager_uid']:
                continue
            try:
                conn.execute('''
                    INSERT OR REPLACE INTO users (uid, nickname, role, hall_name)
                    VALUES (?, ?, ?, ?)
                ''', (r['manager_uid'], r['manager_uid'], 'hall_manager', r['hall_name']))
                added += 1
            except Exception as e:
                print(f'[DB-WARN] 插入失败: {e}')

        conn.commit()
        conn.close()
        print(f'[DB] 已保存 {added} 条厅运营记录')


if __name__ == '__main__':
    print('=' * 60)
    print('厅运营UID抓取测试')
    print('=' * 60)

    try:
        crawler = HallManagerCrawler()

        # 测试抓取列表
        print('\n--- [1/2] 抓取大厅列表 ---')
        halls, total = crawler.fetch_hall_list(1)
        print(f'第1页找到 {len(halls)} 个大厅，共{total}页')
        for h in halls[:5]:
            print(f'  ID={h["id"]}, 名称={h["name"]}')

        # 测试抓取第一个厅的运营UID
        if halls:
            print(f'\n--- [2/2] 抓取第一个厅的运营UID ---')
            info = crawler.fetch_manager_uid(halls[0]['id'], halls[0]['name'])
            print(f'结果: {json.dumps(info, ensure_ascii=False, indent=2)}')

    except Exception as e:
        print(f'测试失败: {e}')
        import traceback
        traceback.print_exc()
