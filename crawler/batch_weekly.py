#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史周报批量计算
遍历 stats_daily 中所有日期，按自然周生成周报
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'crawler'))

from datetime import datetime, timedelta
import pandas as pd
from db import get_db
from metrics import calculate_weekly_metrics, calculate_weekly_metrics_from_detail, save_weekly_report


def get_all_weeks():
    """获取数据库中所有存在的自然周（周一日期列表）"""
    conn = get_db()
    cursor = conn.execute(
        'SELECT DISTINCT date_str FROM stats_daily WHERE hall_name = "全部" AND date_str IS NOT NULL ORDER BY date_str'
    )
    dates = [row['date_str'] for row in cursor.fetchall()]
    conn.close()
    
    # 按自然周分组，取每周一
    weeks = set()
    for d in dates:
        try:
            dt = datetime.strptime(d, '%Y-%m-%d')
            monday = dt - timedelta(days=dt.weekday())  # 本周一
            weeks.add(monday.strftime('%Y-%m-%d'))
        except ValueError:
            continue
    
    return sorted(weeks)


def run_batch_weekly():
    """批量计算所有历史周报"""
    weeks = get_all_weeks()
    print(f'发现 {len(weeks)} 个自然周需要计算')
    
    success = 0
    failed = 0
    
    # 获取所有大厅列表
    conn = get_db()
    halls_df = pd.read_sql_query(
        'SELECT DISTINCT hall_name FROM team_detail WHERE snapshot_date IS NOT NULL',
        conn
    )
    conn.close()
    hall_list = ['all'] + halls_df['hall_name'].tolist()
    
    for i, week_start in enumerate(weeks):
        dt = datetime.strptime(week_start, '%Y-%m-%d')
        week_end = dt + timedelta(days=6)
        print(f'\n[{i+1}/{len(weeks)}] 计算周报: {week_start} (周一) ~ {week_end.strftime("%Y-%m-%d")} (周日)')
        
        for hall in hall_list:
            if hall == 'all':
                metrics = calculate_weekly_metrics(hall_name='all', target_week_start=week_start)
            else:
                metrics = calculate_weekly_metrics_from_detail(hall_name=hall, target_week_start=week_start)
            
            if metrics:
                save_weekly_report(metrics)
                if hall == 'all':
                    print(f'  ✅ 汇总: 新成团{metrics["new_team_count"]}, 留存率{metrics["retention_rate"]}%, 解散率{metrics["dissolution_rate"]}%')
                success += 1
            else:
                if hall == 'all':
                    print(f'  ⚠️ 跳过: 该周无数据')
                failed += 1
    
    print(f'\n{"="*50}')
    print(f'批量计算完成: 成功{success}周, 跳过{failed}周')
    print(f'{"="*50}')


def show_weekly_reports():
    """展示所有周报数据"""
    conn = get_db()
    cursor = conn.execute('''
        SELECT week_label, week_start, week_end, 
               new_team_count, active_team_count_end, active_team_count_start,
               dissolved_count, retention_rate, dissolution_rate, total_reward, activity_index
        FROM weekly_report 
        WHERE hall_name = 'all'
        ORDER BY week_start
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    print(f'\n{"="*80}')
    print(f'周报汇总表 (共{len(rows)}周)')
    print(f'{"="*80}')
    print(f'{"周次":<12} {"新成团":>6} {"周初团数":>8} {"周末团数":>8} {"解散":>6} {"留存率":>8} {"解散率":>8} {"总流水":>10} {"活跃度":>6}')
    print(f'{"-"*80}')
    
    for row in rows:
        print(f'{row["week_label"]:<12} {row["new_team_count"]:>6} {row["active_team_count_start"]:>8} {row["active_team_count_end"]:>8} {row["dissolved_count"]:>6} {row["retention_rate"]:>7.1f}% {row["dissolution_rate"]:>7.1f}% ¥{row["total_reward"]:>8.0f} {row["activity_index"]:>6.2f}')
    
    # 政策前后对比
    print(f'\n{"="*80}')
    print('政策前后对比 (政策上线: 2026-07-17)')
    print(f'{"="*80}')
    
    policy_date = datetime.strptime('2026-07-17', '%Y-%m-%d')
    
    before = [r for r in rows if datetime.strptime(r['week_end'], '%Y-%m-%d') < policy_date]
    after = [r for r in rows if datetime.strptime(r['week_start'], '%Y-%m-%d') >= policy_date]
    
    if before and after:
        avg_before_new = sum(r['new_team_count'] for r in before) / len(before)
        avg_after_new = sum(r['new_team_count'] for r in after) / len(after)
        change = (avg_after_new - avg_before_new) / avg_before_new * 100 if avg_before_new > 0 else 0
        
        print(f'周均新成团数: 政策前 {avg_before_new:.1f} → 政策后 {avg_after_new:.1f} ({"↑" if change > 0 else "↓"}{abs(change):.1f}%)')
        
        avg_before_retention = sum(r['retention_rate'] for r in before) / len(before)
        avg_after_retention = sum(r['retention_rate'] for r in after) / len(after)
        print(f'平均留存率: 政策前 {avg_before_retention:.1f}% → 政策后 {avg_after_retention:.1f}%')
        
        avg_before_dissolution = sum(r['dissolution_rate'] for r in before) / len(before)
        avg_after_dissolution = sum(r['dissolution_rate'] for r in after) / len(after)
        print(f'平均解散率: 政策前 {avg_before_dissolution:.1f}% → 政策后 {avg_after_dissolution:.1f}%')
        
        avg_before_reward = sum(r['total_reward'] for r in before) / len(before)
        avg_after_reward = sum(r['total_reward'] for r in after) / len(after)
        change_r = (avg_after_reward - avg_before_reward) / avg_before_reward * 100 if avg_before_reward > 0 else 0
        print(f'周均总流水: 政策前 ¥{avg_before_reward:.0f} → 政策后 ¥{avg_after_reward:.0f} ({"↑" if change_r > 0 else "↓"}{abs(change_r):.1f}%)')


if __name__ == '__main__':
    run_batch_weekly()
    show_weekly_reports()
