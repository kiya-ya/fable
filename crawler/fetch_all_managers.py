#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键抓取所有厅运营UID并存入数据库"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hall_manager_crawler import HallManagerCrawler
import sqlite3
import time

def main():
    print('=' * 60)
    print('开始完整抓取所有厅运营UID')
    print('=' * 60)

    crawler = HallManagerCrawler()

    # 1. 抓取所有大厅
    print('\n--- 步骤1: 抓取大厅列表 ---')
    halls = crawler.fetch_all_halls()
    print(f'共 {len(halls)} 个大厅')

    # 2. 逐个抓取厅运营UID
    print('\n--- 步骤2: 抓取厅运营UID ---')
    results = []
    for i, hall in enumerate(halls):
        info = crawler.fetch_manager_uid(hall['id'], hall['name'])
        if info['manager_uid']:
            results.append(info)
            print(f'  ✓ [{i+1}/{len(halls)}] {info["hall_name"]} → UID:{info["manager_uid"]}')
        else:
            print(f'  ✗ [{i+1}/{len(halls)}] {hall["name"]} → 未找到UID')
        time.sleep(0.3)

    print(f'\n抓取完成: {len(results)}/{len(halls)} 个厅有运营UID')

    # 3. 保存到数据库
    print('\n--- 步骤3: 保存到数据库 ---')
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'stats.db')
    conn = sqlite3.connect(db_path)

    # 确保users表有hall_name字段
    try:
        conn.execute('ALTER TABLE users ADD COLUMN hall_name TEXT')
        print('[DB] 已添加 hall_name 字段')
    except Exception:
        pass

    # 先清理旧的hall_manager记录（保留admin）
    conn.execute("DELETE FROM users WHERE role = 'hall_manager'")
    print('[DB] 已清理旧厅运营记录')

    added = 0
    for r in results:
        try:
            conn.execute('''
                INSERT INTO users (uid, nickname, role, hall_name)
                VALUES (?, ?, ?, ?)
            ''', (r['manager_uid'], r['manager_uid'], 'hall_manager', r['hall_name']))
            added += 1
        except Exception as e:
            print(f'[DB-WARN] 插入失败: {e}')

    conn.commit()

    # 显示结果
    print('\n--- 数据库中的厅运营列表 ---')
    cursor = conn.execute("SELECT uid, hall_name FROM users WHERE role = 'hall_manager' ORDER BY hall_name")
    for row in cursor.fetchall():
        print(f'  UID:{row[0]} → {row[1]}')

    conn.close()
    print(f'\n[DB] 成功保存 {added} 条厅运营记录')
    print('=' * 60)

if __name__ == '__main__':
    main()
