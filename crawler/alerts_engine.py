#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预警规则引擎
基于 weekly_report / stats_daily / hall_stats 数据自动检测异常
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))
from db import get_db


# ═══════════════════════════════════════════════════════════════════════════
#  预警规则配置
# ═══════════════════════════════════════════════════════════════════════════

RULES = {
    'dissolution_spike': {
        'name': '解散率突增',
        'severity': 'high',
        'threshold': 20.0,        # 环比上升超过 20%
        'metric': 'dissolution_rate',
    },
    'revenue_decline': {
        'name': '流水连续下降',
        'severity': 'medium',
        'threshold': 2,           # 连续下降周数
        'metric': 'total_reward',
    },
    'new_team_drop': {
        'name': '新成团数骤降',
        'severity': 'high',
        'threshold': 30.0,        # 环比下降超过 30%
        'metric': 'new_team_count',
    },
    'retention_drop': {
        'name': '留存率大幅下降',
        'severity': 'medium',
        'threshold': 10.0,        # 环比下降超过 10 个百分点
        'metric': 'retention_rate',
    },
    'hall_dissolution_high': {
        'name': '大厅解散率异常',
        'severity': 'medium',
        'threshold': 1.5,         # 高于全平台平均 50%
        'metric': 'dissolution_rate',
    },
}


def _save_alert(alert_type: str, severity: str, title: str, description: str,
                metric_name: str = None, metric_value: float = None,
                threshold: float = None, week_label: str = None):
    """保存预警到数据库"""
    conn = get_db()
    try:
        # 同一周同类预警去重
        conn.execute('''
            DELETE FROM alerts
            WHERE alert_type = ? AND week_label = ?
        ''', (alert_type, week_label))
        conn.execute('''
            INSERT INTO alerts (alert_type, severity, title, description,
                                metric_name, metric_value, threshold, week_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (alert_type, severity, title, description,
              metric_name, metric_value, threshold, week_label))
        conn.commit()
        print(f'[Alert] {severity.upper()}: {title}')
    except Exception as e:
        print(f'[Alert ERROR] 保存预警失败: {e}')
    finally:
        conn.close()


def check_dissolution_spike(conn):
    """规则1: 解散率突增"""
    cfg = RULES['dissolution_spike']
    cursor = conn.execute('''
        SELECT week_label, dissolution_rate
        FROM weekly_report WHERE hall_name = 'all'
        ORDER BY week_start DESC LIMIT 2
    ''')
    rows = cursor.fetchall()
    if len(rows) < 2:
        return
    this_week, last_week = rows[0], rows[1]
    curr, prev = this_week['dissolution_rate'], last_week['dissolution_rate']
    if prev <= 0:
        return
    change_pct = round((curr - prev) / prev * 100, 1)
    if change_pct >= cfg['threshold']:
        _save_alert(
            'dissolution_spike', cfg['severity'], cfg['name'],
            f'本周解散率 {curr}% 环比上周 {prev}% 上升 {change_pct}%，超过阈值 {cfg["threshold"]}%',
            cfg['metric'], curr, cfg['threshold'], this_week['week_label']
        )


def check_revenue_decline(conn):
    """规则2: 流水连续下降"""
    cfg = RULES['revenue_decline']
    cursor = conn.execute('''
        SELECT week_label, total_reward
        FROM weekly_report WHERE hall_name = 'all'
        ORDER BY week_start DESC LIMIT 5
    ''')
    rows = cursor.fetchall()
    if len(rows) < 2:
        return
    # 找连续下降周数
    decline_weeks = 0
    for i in range(len(rows) - 1):
        if rows[i]['total_reward'] < rows[i+1]['total_reward']:
            decline_weeks += 1
        else:
            break
    if decline_weeks >= cfg['threshold']:
        latest = rows[0]
        _save_alert(
            'revenue_decline', cfg['severity'], cfg['name'],
            f'本周流水 ¥{latest["total_reward"]:,.0f}，已连续下降 {decline_weeks} 周',
            cfg['metric'], latest['total_reward'], cfg['threshold'], latest['week_label']
        )


def check_new_team_drop(conn):
    """规则3: 新成团数骤降"""
    cfg = RULES['new_team_drop']
    cursor = conn.execute('''
        SELECT week_label, new_team_count
        FROM weekly_report WHERE hall_name = 'all'
        ORDER BY week_start DESC LIMIT 2
    ''')
    rows = cursor.fetchall()
    if len(rows) < 2:
        return
    this_week, last_week = rows[0], rows[1]
    curr, prev = this_week['new_team_count'], last_week['new_team_count']
    if prev <= 0:
        return
    change_pct = round((curr - prev) / prev * 100, 1)
    if change_pct <= -cfg['threshold']:
        _save_alert(
            'new_team_drop', cfg['severity'], cfg['name'],
            f'本周新成团 {curr} 个，环比上周 {prev} 个下降 {abs(change_pct)}%，超过阈值 {cfg["threshold"]}%',
            cfg['metric'], curr, cfg['threshold'], this_week['week_label']
        )


def check_retention_drop(conn):
    """规则4: 留存率大幅下降"""
    cfg = RULES['retention_drop']
    cursor = conn.execute('''
        SELECT week_label, retention_rate
        FROM weekly_report WHERE hall_name = 'all'
        ORDER BY week_start DESC LIMIT 2
    ''')
    rows = cursor.fetchall()
    if len(rows) < 2:
        return
    this_week, last_week = rows[0], rows[1]
    curr, prev = this_week['retention_rate'], last_week['retention_rate']
    drop = prev - curr
    if drop >= cfg['threshold']:
        _save_alert(
            'retention_drop', cfg['severity'], cfg['name'],
            f'本周留存率 {curr}% 环比上周 {prev}% 下降 {drop:.1f} 个百分点',
            cfg['metric'], curr, cfg['threshold'], this_week['week_label']
        )


def check_hall_dissolution_high(conn):
    """规则5: 大厅解散率异常"""
    cfg = RULES['hall_dissolution_high']
    # 获取全平台最新平均解散率
    avg_cursor = conn.execute('''
        SELECT dissolution_rate FROM weekly_report
        WHERE hall_name = 'all' ORDER BY week_start DESC LIMIT 1
    ''')
    avg_row = avg_cursor.fetchone()
    if not avg_row:
        return
    avg_rate = avg_row['dissolution_rate']
    if avg_rate <= 0:
        return

    # 检查各厅（从 hall_stats 中找解散率高的）
    # hall_stats 没有解散率，需要从 team_detail 计算
    snapshot = conn.execute(
        "SELECT MAX(snapshot_date) as d FROM team_detail"
    ).fetchone()['d']
    if not snapshot:
        return

    hall_cursor = conn.execute('''
        SELECT hall_name,
               COUNT(*) as total,
               SUM(CASE WHEN COALESCE(dissolve_date, '') != '' THEN 1 ELSE 0 END) as dissolved
        FROM team_detail WHERE snapshot_date = ?
        GROUP BY hall_name HAVING total >= 5
    ''', (snapshot,))

    # 收集所有大厅解散率，只取 top 5
    hall_rates = []
    for row in hall_cursor.fetchall():
        hall_rate = (row['dissolved'] / row['total'] * 100) if row['total'] > 0 else 0
        if hall_rate >= avg_rate * cfg['threshold'] and hall_rate >= 20:
            hall_rates.append((row['hall_name'], hall_rate, row['total']))
    
    # 按解散率降序，取前5
    hall_rates.sort(key=lambda x: x[1], reverse=True)
    for hall_name, hall_rate, total in hall_rates[:5]:
        _save_alert(
            'hall_dissolution_high', cfg['severity'], cfg['name'],
            f'{hall_name} 解散率 {hall_rate:.1f}%（{total}个团），高于全平台平均 {avg_rate:.1f}%',
            cfg['metric'], hall_rate, cfg['threshold'],
            datetime.now().strftime('%Y-%m-%d')
        )


def run_alerts_check():
    """运行全部预警检测"""
    print('\n--- [Alerts] 开始预警检测 ---')
    conn = get_db()
    try:
        check_dissolution_spike(conn)
        check_revenue_decline(conn)
        check_new_team_drop(conn)
        check_retention_drop(conn)
        check_hall_dissolution_high(conn)
        print('[Alerts] 预警检测完成')
    except Exception as e:
        print(f'[Alerts ERROR] 预警检测失败: {e}')
    finally:
        conn.close()


if __name__ == '__main__':
    run_alerts_check()
