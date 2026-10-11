#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预警引擎
根据需求文档第6章的预警规则实现
"""
import sqlite3
import pandas as pd
from datetime import datetime
from db import get_db


def check_alerts():
    """
    检查所有预警规则，返回触发的预警列表
    """
    alerts = []
    conn = get_db()
    
    # 1. 获取最近两周的统计数据（全部大厅）
    df = pd.read_sql_query('''
        SELECT * FROM stats_daily 
        WHERE hall_name = '全部'
        ORDER BY cycle DESC LIMIT 14
    ''', conn)
    conn.close()
    
    if len(df) < 7:
        return alerts  # 数据不足
    
    # 分离本周和上周数据（各取7天）
    this_week = df.head(7)
    last_week = df.iloc[7:14]
    
    if len(last_week) < 7:
        return alerts
    
    # ===== 计算指标 =====
    this_dissolved = this_week['dissolved_count'].sum()
    last_dissolved = last_week['dissolved_count'].sum()
    this_new = this_week['new_team_count'].sum()
    last_new = last_week['new_team_count'].sum()
    this_reward = this_week['reward_amount'].sum()
    last_reward = last_week['reward_amount'].sum()
    
    # 本周平均团数（用于解散率计算）
    this_avg_teams = this_week['active_team_count'].mean()
    last_avg_teams = last_week['active_team_count'].mean()
    
    this_dissolution_rate = this_dissolved / this_avg_teams * 100 if this_avg_teams > 0 else 0
    last_dissolution_rate = last_dissolved / last_avg_teams * 100 if last_avg_teams > 0 else 0
    
    # ===== 规则1: 解散率突增 (>20%) =====
    if last_dissolution_rate > 0:
        dissolution_change = (this_dissolution_rate - last_dissolution_rate) / last_dissolution_rate * 100
        if dissolution_change > 20:
            alerts.append({
                'type': 'dissolution_spike',
                'severity': 'high',
                'title': '解散率突增',
                'description': f'本周解散率{this_dissolution_rate:.1f}%，环比↑{dissolution_change:.1f}%',
                'metric_name': 'dissolution_rate',
                'metric_value': this_dissolution_rate,
                'threshold': 20,
            })
    
    # ===== 规则2: 解散率连续上升 =====
    if this_dissolution_rate > last_dissolution_rate:
        # 检查上上周是否也上升（简化：只检查两周）
        alerts.append({
            'type': 'dissolution_rising',
            'severity': 'medium',
            'title': '解散率连续上升',
            'description': f'解散率从{last_dissolution_rate:.1f}%升至{this_dissolution_rate:.1f}%',
            'metric_name': 'dissolution_rate',
            'metric_value': this_dissolution_rate,
            'threshold': None,
        })
    
    # ===== 规则3: 新成团数骤降 (>30%) =====
    if last_new > 0:
        new_change = (this_new - last_new) / last_new * 100
        if new_change < -30:
            alerts.append({
                'type': 'new_team_drop',
                'severity': 'high',
                'title': '新成团数骤降',
                'description': f'本周新成团{this_new}个，环比↓{abs(new_change):.1f}%',
                'metric_name': 'new_team_count',
                'metric_value': this_new,
                'threshold': -30,
            })
    
    # ===== 规则4: 流水大幅下降 (>25%) =====
    if last_reward > 0:
        reward_change = (this_reward - last_reward) / last_reward * 100
        if reward_change < -25:
            alerts.append({
                'type': 'revenue_drop',
                'severity': 'high',
                'title': '流水大幅下降',
                'description': f'本周流水¥{this_reward:,.0f}，环比↓{abs(reward_change):.1f}%',
                'metric_name': 'reward_amount',
                'metric_value': this_reward,
                'threshold': -25,
            })
    
    # ===== 规则5: 进行中团数跌破临界值 (<300) =====
    latest_active = this_week['active_team_count'].iloc[0]
    if latest_active < 300:
        alerts.append({
            'type': 'team_count_critical',
            'severity': 'high',
            'title': '进行中团数跌破临界值',
            'description': f'当前进行中团数{latest_active}个，低于300临界值',
            'metric_name': 'active_team_count',
            'metric_value': latest_active,
            'threshold': 300,
        })
    
    # ===== 规则6: 系统解散占比过高 (>80%) =====
    this_system = this_week['system_dissolved_count'].sum()
    if this_dissolved > 0 and this_system / this_dissolved > 0.8:
        alerts.append({
            'type': 'system_dissolution_high',
            'severity': 'medium',
            'title': '系统解散占比过高',
            'description': f'系统解散占比{(this_system/this_dissolved*100):.1f}%，可能多为到期解散',
            'metric_name': 'system_dissolution_rate',
            'metric_value': this_system / this_dissolved * 100,
            'threshold': 80,
        })
    
    return alerts


def save_alerts(alerts: list):
    """保存预警到数据库"""
    if not alerts:
        return
    
    conn = get_db()
    week_label = datetime.now().strftime('%Y-%m-%d')
    
    for alert in alerts:
        conn.execute('''
            INSERT INTO alerts 
            (alert_type, severity, title, description, metric_name, metric_value, threshold, week_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            alert['type'], alert['severity'], alert['title'], alert['description'],
            alert.get('metric_name'), alert.get('metric_value'), alert.get('threshold'), week_label
        ))
    
    conn.commit()
    conn.close()
    print(f'[Alerts] 已保存 {len(alerts)} 条预警')


def get_recent_alerts(limit: int = 10):
    """获取最近的预警"""
    conn = get_db()
    cursor = conn.execute('''
        SELECT * FROM alerts 
        ORDER BY created_at DESC LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def run_alert_check():
    """运行预警检查"""
    print('\n--- 预警引擎检查 ---')
    alerts = check_alerts()
    
    if alerts:
        print(f'发现 {len(alerts)} 条预警:')
        for a in alerts:
            icon = '🔴' if a['severity'] == 'high' else '🟡'
            print(f'  {icon} [{a["severity"].upper()}] {a["title"]}: {a["description"]}')
        save_alerts(alerts)
    else:
        print('✅ 未发现异常，系统运行正常')
    
    return alerts


if __name__ == '__main__':
    run_alert_check()
