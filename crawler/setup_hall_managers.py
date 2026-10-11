#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建 hall_managers 表并重新入库厅运营数据"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hall_manager_crawler import HallManagerCrawler
import time

def main():
    print('=' * 60)
    print('创建 hall_managers 表并入库厅运营数据')
    print('=' * 60)

    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'stats.db')
    conn = sqlite3.connect(db_path)

    # 1. 创建 hall_managers 表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS hall_managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            hall_name TEXT NOT NULL,
            UNIQUE(uid, hall_name)
        )
    ''')
    print('[DB] hall_managers 表已创建')

    # 2. 清理旧数据
    conn.execute('DELETE FROM hall_managers')
    print('[DB] 已清理旧数据')

    # 3. 抓取所有厅运营UID
    print('\n--- 开始抓取 ---')
    crawler = HallManagerCrawler()
    halls = crawler.fetch_all_halls()

    results = []
    for i, hall in enumerate(halls):
        info = crawler.fetch_manager_uid(hall['id'], hall['name'])
        if info['manager_uid']:
            results.append(info)
        time.sleep(0.2)

    print(f'\n抓取完成: {len(results)}/{len(halls)} 个厅有运营UID')

    # 4. 入库（允许一个UID对应多个厅）
    inserted = 0
    for r in results:
        try:
            conn.execute('''
                INSERT OR IGNORE INTO hall_managers (uid, hall_name)
                VALUES (?, ?)
            ''', (r['manager_uid'], r['hall_name']))
            inserted += 1
        except Exception as e:
            print(f'[DB-WARN] 插入失败: {e}')

    conn.commit()

    # 5. 统计结果
    print('\n--- 统计结果 ---')
    cursor = conn.execute('SELECT COUNT(DISTINCT uid) FROM hall_managers')
    total_managers = cursor.fetchone()[0]
    cursor = conn.execute('SELECT COUNT(*) FROM hall_managers')
    total_bindings = cursor.fetchone()[0]
    print(f'运营UID数: {total_managers}')
    print(f'厅-运营绑定数: {total_bindings}')

    # 显示运营负责的厅列表
    print('\n--- 各运营负责的厅 ---')
    cursor = conn.execute('''
        SELECT uid, COUNT(*) as hall_count, GROUP_CONCAT(hall_name, ', ') as halls
        FROM hall_managers
        GROUP BY uid
        ORDER BY hall_count DESC
    ''')
    for row in cursor.fetchall():
        print(f'  UID:{row[0]} ({row[1]}个厅)')

    conn.close()
    print(f'\n[DB] 成功保存 {inserted} 条绑定记录')
    print('=' * 60)

if __name__ == '__main__':
    main()
