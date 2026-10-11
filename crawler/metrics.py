#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指标计算模块 - 基于 date_str 计算周报指标"""
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from db import get_db


def get_week_label(week_start: str, week_end: str) -> str:
    """生成周标签"""
    return f'{week_start}~{week_end}'


def calculate_weekly_metrics(hall_name: str = 'all',
                              target_week_start: str = None) -> dict:
    """
    计算单周核心指标
    参数:
        hall_name: 'all' 或具体大厅名
        target_week_start: 目标周开始日期 YYYY-MM-DD，None则取最新周
    """
    conn = get_db()
    
    # 如果没有指定日期，取数据库中最新 date_str
    if not target_week_start:
        cursor = conn.execute(
            'SELECT date_str FROM stats_daily WHERE hall_name = "全部" ORDER BY date_str DESC LIMIT 1'
        )
        row = cursor.fetchone()
        if row and row['date_str']:
            latest = datetime.strptime(row['date_str'], '%Y-%m-%d')
            monday = latest - timedelta(days=latest.weekday())
            target_week_start = monday.strftime('%Y-%m-%d')
        else:
            conn.close()
            return None
    
    # 计算周起止（周一到周日）
    start_dt = datetime.strptime(target_week_start, '%Y-%m-%d')
    end_dt = start_dt + timedelta(days=6)
    week_start = start_dt.strftime('%Y-%m-%d')
    week_end = end_dt.strftime('%Y-%m-%d')
    
    # 查询本周7天的数据
    hall_filter = '全部' if hall_name == 'all' else hall_name
    
    df = pd.read_sql_query('''
        SELECT * FROM stats_daily 
        WHERE date_str >= ? AND date_str <= ? AND hall_name = ?
        ORDER BY date_str
    ''', conn, params=(week_start, week_end, hall_filter))
    
    conn.close()
    
    if df.empty:
        print(f'[Metrics] 无数据: {week_start} ~ {week_end} / {hall_name}')
        return None
    
    # ===== 计算指标 =====
    metrics = {}
    
    # 1. 基础指标
    metrics['week_label'] = get_week_label(start_dt.strftime('%m-%d'), end_dt.strftime('%m-%d'))
    metrics['week_start'] = week_start
    metrics['week_end'] = week_end
    metrics['hall_name'] = hall_name
    
    metrics['new_team_count'] = int(df['new_team_count'].sum())
    metrics['active_team_count_end'] = int(df['active_team_count'].iloc[-1])
    metrics['active_team_count_start'] = int(df['active_team_count'].iloc[0])
    metrics['dissolved_count'] = int(df['dissolved_count'].sum())
    metrics['active_dissolved_count'] = int(df['active_dissolved_count'].sum())
    metrics['system_dissolved_count'] = int(df['system_dissolved_count'].sum())
    metrics['total_reward'] = float(df['reward_amount'].sum())
    
    # 2. 留存率 = (期末进行中 - 本周新成团) / 期初进行中 × 100
    if metrics['active_team_count_start'] > 0:
        metrics['retention_rate'] = round(
            (metrics['active_team_count_end'] - metrics['new_team_count']) 
            / metrics['active_team_count_start'] * 100, 2
        )
    else:
        metrics['retention_rate'] = 0.0
    
    # 3. 解散率 = 本周解散数 / 周始进行中 × 100
    if metrics['active_team_count_start'] > 0:
        metrics['dissolution_rate'] = round(
            metrics['dissolved_count'] / metrics['active_team_count_start'] * 100, 2
        )
    else:
        metrics['dissolution_rate'] = 0.0
    # 4. 单团平均流水
    if metrics['active_team_count_end'] > 0:
        metrics['avg_reward_per_team'] = round(
            metrics['total_reward'] / metrics['active_team_count_end'], 2
        )
    else:
        metrics['avg_reward_per_team'] = 0.0
    
    # 5. 活跃度
    metrics['total_drive_tasks'] = int(df['drive_task_count'].sum())
    metrics['total_accompany_tasks'] = int(df['accompany_task_count'].sum())
    metrics['total_gift_tasks'] = int(df['gift_task_count'].sum())
    total_tasks = metrics['total_drive_tasks'] + metrics['total_accompany_tasks'] + metrics['total_gift_tasks']
    
    if metrics['active_team_count_end'] > 0:
        metrics['activity_index'] = round(total_tasks / metrics['active_team_count_end'], 2)
    else:
        metrics['activity_index'] = 0.0
    
    # 6. 成就
    metrics['level_achievement_count'] = int(df['level_achievement_count'].sum())
    metrics['revenue_achievement_count'] = int(df['revenue_achievement_count'].sum())
    
    return metrics




def calculate_weekly_metrics_from_detail(hall_name: str = 'all',
                                          target_week_start: str = None) -> dict:
    """
    从 team_detail 快照表计算分厅周报指标
    （当 stats_daily 中没有分厅数据时使用）
    """
    conn = get_db()
    
    # 计算周起止
    if not target_week_start:
        cursor = conn.execute('SELECT MAX(snapshot_date) FROM team_detail')
        row = cursor.fetchone()
        if row and row[0]:
            latest = datetime.strptime(row[0], '%Y-%m-%d')
            target_week_start = (latest - timedelta(days=latest.weekday())).strftime('%Y-%m-%d')
        else:
            conn.close()
            return None
    
    start_dt = datetime.strptime(target_week_start, '%Y-%m-%d')
    end_dt = start_dt + timedelta(days=6)
    week_start = start_dt.strftime('%Y-%m-%d')
    week_end = end_dt.strftime('%Y-%m-%d')
    
    # 获取本周的所有 snapshot_date
    snapshots = pd.read_sql_query('''
        SELECT DISTINCT snapshot_date FROM team_detail 
        WHERE snapshot_date >= ? AND snapshot_date <= ? 
        ORDER BY snapshot_date
    ''', conn, params=(week_start, week_end))
    
    if snapshots.empty:
        conn.close()
        return None
    
    first_snap = snapshots['snapshot_date'].iloc[0]
    last_snap = snapshots['snapshot_date'].iloc[-1]
    
    # 大厅参数
    hall_sql = '' if hall_name == 'all' else 'AND hall_name = ?'
    
    # 1. 周初进行中
    df_start = pd.read_sql_query(f'''
        SELECT team_id, dissolve_date FROM team_detail 
        WHERE snapshot_date = ? {hall_sql}
    ''', conn, params=(first_snap, hall_name) if hall_name != 'all' else (first_snap,))
    active_start = len(df_start[df_start['dissolve_date'].isna() | (df_start['dissolve_date'] == '')])
    
    # 2. 周末进行中 + 流水 + 奖励金额 + 任务数
    df_end = pd.read_sql_query(f'''
        SELECT team_id, dissolve_date, sister_revenue, reward_amount,
               drive_task_count, accompany_task_count, gift_task_count
        FROM team_detail 
        WHERE snapshot_date = ? {hall_sql}
    ''', conn, params=(last_snap, hall_name) if hall_name != 'all' else (last_snap,))
    df_end = pd.read_sql_query(f'''
        SELECT team_id, dissolve_date, reward_amount,
               drive_task_count, accompany_task_count, gift_task_count
        FROM team_detail 
        WHERE snapshot_date = ? {hall_sql}
    ''', conn, params=(last_snap, hall_name) if hall_name != 'all' else (last_snap,))
    active_end = len(df_end[df_end['dissolve_date'].isna() | (df_end['dissolve_date'] == '')])
    
    # 3. 新成团
    df_new = pd.read_sql_query(f'''
        SELECT DISTINCT team_id FROM team_detail 
        WHERE form_date >= ? AND form_date <= ? {hall_sql}
    ''', conn, params=(week_start, week_end, hall_name) if hall_name != 'all' else (week_start, week_end))
    new_count = len(df_new)
    
    # 4. 解散数
    df_diss = pd.read_sql_query(f'''
        SELECT DISTINCT team_id FROM team_detail 
        WHERE dissolve_date >= ? AND dissolve_date <= ? {hall_sql}
    ''', conn, params=(week_start, week_end, hall_name) if hall_name != 'all' else (week_start, week_end))
    dissolved_count = len(df_diss)
    
    
    # 5. 总流水（直接使用累计值，不计算增量）
    total_reward = float(df_end['sister_revenue'].sum()) if not df_end.empty else 0
    # 6. 任务数
    total_drive = int(df_end['drive_task_count'].sum()) if 'drive_task_count' in df_end.columns else 0
    total_accompany = int(df_end['accompany_task_count'].sum()) if 'accompany_task_count' in df_end.columns else 0
    total_gift = int(df_end['gift_task_count'].sum()) if 'gift_task_count' in df_end.columns else 0
    
    conn.close()
    
    # 组装指标
    avg_teams = (active_start + active_end) / 2
    metrics = {
        'week_label': f'{start_dt.strftime("%m-%d")}~{end_dt.strftime("%m-%d")}',
        'week_start': week_start,
        'week_end': week_end,
        'hall_name': hall_name,
        'new_team_count': new_count,
        'active_team_count_end': active_end,
        'active_team_count_start': active_start,
        'dissolved_count': dissolved_count,
        'active_dissolved_count': dissolved_count,
        'system_dissolved_count': 0,
        'total_reward': total_reward,
        'avg_reward_per_team': round(total_reward / active_end, 2) if active_end > 0 else 0,
        'total_drive_tasks': total_drive,
        'total_accompany_tasks': total_accompany,
        'total_gift_tasks': total_gift,
        'activity_index': round((total_drive + total_accompany + total_gift) / active_end, 2) if active_end > 0 else 0,
        'retention_rate': round(active_end / active_start * 100, 2) if active_start > 0 else 0,
        'dissolution_rate': round(dissolved_count / avg_teams * 100, 2) if avg_teams > 0 else 0,
        'level_achievement_count': 0,
        'revenue_achievement_count': 0,
    }
    
    return metrics
def save_weekly_report(metrics: dict):
    """保存周报指标到数据库"""
    if not metrics:
        return
    
    conn = get_db()
    conn.execute('''
        INSERT OR REPLACE INTO weekly_report 
        (week_label, week_start, week_end, hall_name, new_team_count,
         active_team_count_end, active_team_count_start, dissolved_count,
         active_dissolved_count, system_dissolved_count, retention_rate,
         dissolution_rate, total_reward, avg_reward_per_team, total_drive_tasks,
         total_accompany_tasks, total_gift_tasks, activity_index)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        metrics['week_label'], metrics['week_start'], metrics['week_end'],
        metrics['hall_name'], metrics['new_team_count'],
        metrics['active_team_count_end'], metrics['active_team_count_start'],
        metrics['dissolved_count'], metrics['active_dissolved_count'],
        metrics['system_dissolved_count'], metrics['retention_rate'],
        metrics['dissolution_rate'], metrics['total_reward'],
        metrics['avg_reward_per_team'], metrics['total_drive_tasks'],
        metrics['total_accompany_tasks'], metrics['total_gift_tasks'],
        metrics['activity_index']
    ))
    conn.commit()
    conn.close()
    print(f'[Metrics] 周报已保存: {metrics["week_label"]} / {metrics["hall_name"]}')


def calculate_policy_comparison(weeks_before: int = 4, weeks_after: int = 2) -> dict:
    """政策前后对比分析（政策上线日: 2026-07-17）"""
    conn = get_db()
    df = pd.read_sql_query(
        'SELECT * FROM weekly_report WHERE hall_name = "all" ORDER BY week_start',
        conn
    )
    conn.close()
    
    if df.empty:
        return {}
    
    before = df[df['week_end'] < '2026-07-17'].tail(weeks_before)
    after = df[df['week_start'] >= '2026-07-17'].head(weeks_after)
    
    result = {}
    for metric in ['new_team_count', 'retention_rate', 'dissolution_rate',
                   'total_reward', 'activity_index']:
        before_avg = before[metric].mean() if not before.empty else 0
        after_avg = after[metric].mean() if not after.empty else 0
        
        if before_avg > 0:
            change_pct = round((after_avg - before_avg) / before_avg * 100, 2)
        else:
            change_pct = 0.0
        
        result[metric] = {
            'before': round(before_avg, 2),
            'after': round(after_avg, 2),
            'change_pct': change_pct,
            'trend': 'up' if change_pct > 0 else 'down' if change_pct < 0 else 'flat'
        }
    
    return result


def run_metrics_pipeline():
    """运行完整的指标计算流水线"""
    print('\n--- 指标计算流水线 ---')
    
    # 1. 计算最新周报（全部大厅）
    metrics = calculate_weekly_metrics(hall_name='all')
    if metrics:
        save_weekly_report(metrics)
        print(f'全部大厅汇总: 新成团{metrics["new_team_count"]}, 留存率{metrics["retention_rate"]}%, 解散率{metrics["dissolution_rate"]}%')
    
    # 2. 计算各分厅周报（从 team_detail 快照表聚合）
    conn = get_db()
    halls = pd.read_sql_query(
        'SELECT DISTINCT hall_name FROM team_detail WHERE snapshot_date IS NOT NULL',
        conn
    )
    conn.close()
    
    for hall in halls['hall_name']:
        m = calculate_weekly_metrics_from_detail(hall_name=hall)
        if m:
            save_weekly_report(m)
    
    # 3. 政策对比
    comparison = calculate_policy_comparison()
    if comparison:
        print('\n政策前后对比:')
        for k, v in comparison.items():
            arrow = '↑' if v['change_pct'] > 0 else '↓' if v['change_pct'] < 0 else '→'
            print(f'  {k}: 政策前{v["before"]} → 政策后{v["after"]} ({arrow}{v["change_pct"]}%)')
    
    print('\n指标计算完成')


if __name__ == '__main__':
    run_metrics_pipeline()
