#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时任务调度器
每日凌晨 02:00 自动执行数据抓取和指标计算
"""
import sys
import os
import time
from datetime import datetime

# 将项目目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.crawler import run_all as run_crawler
from crawler.metrics import run_metrics_pipeline


def run_daily_job():
    """执行每日抓取任务"""
    print(f'\n{"="*50}')
    print(f'定时任务启动: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{"="*50}')
    
    try:
        # 1. 数据抓取
        run_crawler()
        
        # 2. 指标计算
        run_metrics_pipeline()
        
        print(f'\n[OK] 定时任务完成: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        
    except Exception as e:
        print(f'\n[ERROR] 定时任务失败: {e}')


def main():
    """主循环：每分钟检查一次时间"""
    print('定时调度器已启动...')
    print('目标执行时间: 每日 02:00')
    print('按 Ctrl+C 退出')
    
    last_run_date = None
    
    while True:
        now = datetime.now()
        current_date = now.strftime('%Y-%m-%d')
        current_time = now.strftime('%H:%M')
        
        # 每天 02:00 执行一次
        if current_time == '02:00' and last_run_date != current_date:
            run_daily_job()
            last_run_date = current_date
        
        time.sleep(30)  # 每30秒检查一次


if __name__ == '__main__':
    # 支持直接运行一次
    if len(sys.argv) > 1 and sys.argv[1] == '--now':
        run_daily_job()
    else:
        main()
