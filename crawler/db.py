#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库工具模块"""
import sqlite3
import os
from datetime import datetime

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'stats.db')
SCHEMA_PATH = os.path.join(PROJECT_ROOT, 'data', 'schema.sql')


def get_db():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库（执行schema.sql）"""
    if not os.path.exists(SCHEMA_PATH):
        print(f'[WARN] schema.sql not found: {SCHEMA_PATH}')
        return
    
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        sql = f.read()
    
    conn = get_db()
    conn.executescript(sql)
    conn.commit()
    conn.close()
    print('[OK] Database initialized.')


def log_crawl(source: str, status: str, records_count: int = 0, error_message: str = None):
    """记录抓取日志"""
    conn = get_db()
    conn.execute(
        'INSERT INTO crawl_log (source, status, records_count, error_message) VALUES (?, ?, ?, ?)',
        (source, status, records_count, error_message)
    )
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_db()
