#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
姐妹团数据抓取核心模块
数据源:
  1. 统计数据页: https://bigdata.tuwan.com/sisters/tj
  2. 基础数据页: https://bigdata.tuwan.com/sisters/detail/
  3. 折线图API: https://bigdata.tuwan.com/sisters/getlineData?...
"""
import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import urllib3

from db import get_db, log_crawl

urllib3.disable_warnings()


# ═══════════════════════════════════════════════════════════════════════════
#  ██████╗ ██████╗  ██████╗ ██╗  ██╗██╗███████╗    ██████╗ ███████╗
# ██╔════╝██╔═══██╗██╔═══██╗██║ ██╔╝██║██╔════╝    ██╔══██╗██╔════╝
# ██║     ██║   ██║██║   ██║█████╔╝ ██║█████╗      ██║  ██║█████╗
# ██║     ██║   ██║██║   ██║██╔═██╗ ██║██╔══╝      ██║  ██║██╔══╝
# ╚██████╗╚██████╔╝╚██████╔╝██║  ██╗██║███████╗    ██████╔╝██║
#  ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝    ╚═════╝ ╚═╝
# ═══════════════════════════════════════════════════════════════════════════
#  🔔 重要提示：以下 Cookie 会过期，过期后需要重新粘贴更新！
# ═══════════════════════════════════════════════════════════════════════════
#
#  【需要登录的页面】（必须携带有效 Cookie）
#  ┌──────────────────────────────────────────────────────────────────┐
#  │ ① /sisters/tj      → 统计数据表（每日新成团/解散/流水等）       │
#  │ ② /sisters/detail/ → 基础数据明细（每个姐妹团的详细记录）       │
#  └──────────────────────────────────────────────────────────────────┘
#
#  【不需要登录的页面】（公开API，Cookie过期也能抓）
#  ┌──────────────────────────────────────────────────────────────────┐
#  │ ③ /sisters/getlineData → 折线图趋势数据（留存率/解散率等）     │
#  └──────────────────────────────────────────────────────────────────┘
#
#  【如何更新 Cookie】
#  1. 用浏览器登录 https://bigdata.tuwan.com/sisters/tj
#  2. 按 F12 → Network（网络）→ 刷新页面
#  3. 找到任意请求 → Headers → Request Headers → 复制 Cookie
#  4. 把下面的 COOKIE_STR 整行替换为新的 Cookie 字符串
#  5. 保存文件，重新运行抓取脚本
#
#  ⚠️ Cookie 有效期：通常 1~7 天，过期后抓取会报 "Cookie已过期"
# ═══════════════════════════════════════════════════════════════════════════

# Cookie 已脱敏（勿把真实会话 Cookie 提交进代码）；运行时从 data/cookie_bigdata.json 热加载
COOKIE_STR = ''
# 也可以设置环境变量 SISTERS_COOKIE 来覆盖上面的配置
COOKIE_STR = os.environ.get('SISTERS_COOKIE', COOKIE_STR)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.0',
    'Cookie': COOKIE_STR,
    'Referer': 'https://bigdata.tuwan.com/sisters/tj',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

def _load_cookie():
    """从 data/cookie_bigdata.json 读取 Cookie（bigdata 抓取专用）
    ⚠️ 注意：此 Cookie 与 UID 查询的 Cookie 不同，需分别更新
    """
    cookie_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'cookie_bigdata.json')
    try:
        with open(cookie_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get('cookie_str', '')
    except Exception:
        return ''


def infer_full_date(cycle: str, reference: datetime = None) -> str:
    """
    从 cycle (MM-DD星期X) 推断完整日期 YYYY-MM-DD
    规则: 如果 MM-DD 在参考日期之后超过30天，推断为去年
    """
    if reference is None:
        reference = datetime.now()
    
    mm_dd = cycle[:5]  # "07-26"
    try:
        month = int(mm_dd[:2])
        day = int(mm_dd[3:5])
    except ValueError:
        return reference.strftime('%Y-%m-%d')
    
    try:
        this_year_date = reference.replace(month=month, day=day)
    except ValueError:
        return reference.strftime('%Y-%m-%d')
    
    delta_days = (this_year_date - reference).days
    
    # 如果推断日期在参考日期之后（未来），判定为去年
    if delta_days > 0:
        last_year_date = this_year_date.replace(year=reference.year - 1)
        return last_year_date.strftime('%Y-%m-%d')
    
    return this_year_date.strftime('%Y-%m-%d')



class SistersCrawler:
    BASE_URL = 'https://bigdata.tuwan.com'
    
    def __init__(self):
        self.session = requests.Session()
        # 优先从 data/cookie.json 读取，其次环境变量，最后硬编码
        cookie_str = _load_cookie() or os.environ.get('SISTERS_COOKIE', COOKIE_STR)
        headers = dict(HEADERS)
        headers['Cookie'] = cookie_str
        self.session.headers.update(headers)
        self.session.verify = False
        self.reference_date = datetime.now()
    
    def _check_login(self, resp_text: str) -> bool:
        text_lower = resp_text.lower()
        return '登录' in resp_text and 'password' in text_lower
    
    def crawl_stats(self) -> list:
        """
        抓取统计数据页 (/sisters/tj)
        ⚠️ 【需要登录】Cookie 过期会抛异常，请更新文件顶部的 COOKIE_STR
        数据：每日新成团数、进行中团数、解散数、任务次数、奖励金额等
        """
        url = f'{self.BASE_URL}/sisters/tj'
        print(f'[Crawl] 抓取统计数据: {url}')
        url = f'{self.BASE_URL}/sisters/tj'
        print(f'[Crawl] 抓取统计数据: {url}')
        
        try:
            resp = self.session.get(url, timeout=30)
            if self._check_login(resp.text):
                raise Exception('Cookie已过期，需要重新登录')
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.find_all('table')
            
            if not tables:
                raise Exception('页面未找到数据表格')
            
            table = tables[0]
            rows = table.find_all('tr')
            
            data = []
            headers = []
            
            for i, row in enumerate(rows):
                cols = row.find_all(['td', 'th'])
                cells = [c.get_text(strip=True) for c in cols]
                
                if i == 0:
                    headers = cells
                    print(f'[Crawl] 表头: {headers}')
                    continue
                
                if len(cells) < 5:
                    continue
                
                record = self._map_stats_row(headers, cells)
                if record:
                    data.append(record)
            
            print(f'[Crawl] 统计数据抓取完成: {len(data)} 条')
            log_crawl('stats_daily', 'success', len(data))
            return data
            
        except Exception as e:
            print(f'[ERROR] 统计数据抓取失败: {e}')
            log_crawl('stats_daily', 'failed', error_message=str(e))
            raise
    
    def _map_stats_row(self, headers: list, cells: list) -> dict:
        header_map = {
            '周期': 'cycle',
            '大厅名称': 'hall_name',
            '新成团数': 'new_team_count',
            '进行中姐妹团数': 'active_team_count',
            '团解散数': 'dissolved_count',
            '主动解散数': 'active_dissolved_count',
            '系统解散数': 'system_dissolved_count',
            '开车任务完成次数': 'drive_task_count',
            '陪档任务完成次数': 'accompany_task_count',
            '收送礼任务完成次数': 'gift_task_count',
            '等级成就达成数': 'level_achievement_count',
            '流水成就达成数': 'revenue_achievement_count',
            '发放礼物奖励金额': 'reward_amount',
        }
        
        record = {}
        cycle_val = ''
        
        for i, header in enumerate(headers):
            if i >= len(cells):
                break
            field = header_map.get(header)
            if field:
                value = cells[i]
                if field == 'cycle':
                    cycle_val = value
                    record[field] = value
                    # 推断完整日期
                    record['date_str'] = infer_full_date(value, self.reference_date)
                elif field in ['new_team_count', 'active_team_count', 'dissolved_count',
                            'active_dissolved_count', 'system_dissolved_count',
                            'drive_task_count', 'accompany_task_count', 'gift_task_count',
                            'level_achievement_count', 'revenue_achievement_count']:
                    try:
                        value = int(value.replace(',', '')) if value else 0
                    except:
                        value = 0
                    record[field] = value
                elif field == 'reward_amount':
                    try:
                        value = float(value.replace(',', '')) if value else 0.0
                    except:
                        value = 0.0
                    record[field] = value
                else:
                    record[field] = value
        
        return record if 'cycle' in record else None
    
    def save_stats(self, data: list):
        conn = get_db()
        inserted = 0
        
        for row in data:
            try:
                conn.execute('''
                    INSERT OR REPLACE INTO stats_daily 
                    (cycle, date_str, hall_name, new_team_count, active_team_count, dissolved_count,
                     active_dissolved_count, system_dissolved_count, drive_task_count,
                     accompany_task_count, gift_task_count, level_achievement_count,
                     revenue_achievement_count, reward_amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    row.get('cycle', ''),
                    row.get('date_str', ''),
                    row.get('hall_name', ''),
                    row.get('new_team_count', 0),
                    row.get('active_team_count', 0),
                    row.get('dissolved_count', 0),
                    row.get('active_dissolved_count', 0),
                    row.get('system_dissolved_count', 0),
                    row.get('drive_task_count', 0),
                    row.get('accompany_task_count', 0),
                    row.get('gift_task_count', 0),
                    row.get('level_achievement_count', 0),
                    row.get('revenue_achievement_count', 0),
                    row.get('reward_amount', 0.0),
                ))
                inserted += 1
            except Exception as e:
                print(f'[WARN] 插入失败: {e}')
        
        conn.commit()
        conn.close()
        print(f'[DB] 已保存 {inserted} 条统计数据')
    
    def crawl_detail(self) -> list:
        """
        抓取基础数据明细页 (/sisters/detail/)
        ⚠️ 【需要登录】Cookie 过期会抛异常，请更新文件顶部的 COOKIE_STR
        数据：每个姐妹团的详细信息（成员、等级、流水、解散状态等）
        """
        url = f'{self.BASE_URL}/sisters/detail/'
        url = f'{self.BASE_URL}/sisters/detail/'
        print(f'[Crawl] 抓取基础数据明细: {url}')
        
        try:
            resp = self.session.get(url, timeout=60)
            if self._check_login(resp.text):
                raise Exception('Cookie已过期，需要重新登录')
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.find_all('table')
            
            if not tables:
                raise Exception('页面未找到数据表格')
            
            table = tables[0]
            rows = table.find_all('tr')
            
            data = []
            headers = []
            snapshot_date = datetime.now().strftime('%Y-%m-%d')
            
            for i, row in enumerate(rows):
                cols = row.find_all(['td', 'th'])
                cells = [c.get_text(strip=True) for c in cols]
                
                if i == 0:
                    headers = cells
                    print(f'[Crawl] 表头: {headers[:5]}... (共{len(headers)}列)')
                    continue
                
                if len(cells) < 10:
                    continue
                
                record = self._map_detail_row(headers, cells)
                if record:
                    record['snapshot_date'] = snapshot_date
                    data.append(record)
            
            print(f'[Crawl] 基础数据抓取完成: {len(data)} 条')
            log_crawl('team_detail', 'success', len(data))
            return data
            
        except Exception as e:
            print(f'[ERROR] 基础数据抓取失败: {e}')
            log_crawl('team_detail', 'failed', error_message=str(e))
            raise
    
    def _map_detail_row(self, headers: list, cells: list) -> dict:
        header_map = {
            '姐妹团ID': 'team_id',
            '成团日期': 'form_date',
            '大厅名称': 'hall_name',
            '姐姐UID': 'sister_uid',
            '姐姐昵称': 'sister_nickname',
            '姐姐当前等级': 'sister_level',
            '妹妹UID': 'sister_uid2',
            '妹妹昵称': 'sister_nickname2',
            '妹妹当前等级': 'sister_level2',
            '妹妹最高等级': 'sister_max_level2',
            '妹妹累计流水': 'sister_revenue',
            '开车任务完成次数': 'drive_task_count',
            '陪档任务完成次数': 'accompany_task_count',
            '收送礼任务完成次数': 'gift_task_count',
            '等级成就达成数': 'level_achievement_count',
            '流水成就达成数': 'revenue_achievement_count',
            '银箱子成就达成数': 'silver_box_achievement',
            '已成团天数': 'days_since_formed',
            '发放礼物奖励金额': 'reward_amount',
            '解散日期': 'dissolve_date',
            '解散原因': 'dissolve_reason',
        }
        
        record = {}
        for i, header in enumerate(headers):
            if i >= len(cells):
                break
            field = header_map.get(header)
            if field:
                value = cells[i]
                if field in ['team_id', 'sister_uid', 'sister_uid2', 'drive_task_count',
                            'accompany_task_count', 'gift_task_count', 'level_achievement_count',
                            'revenue_achievement_count', 'silver_box_achievement', 'days_since_formed']:
                    try:
                        value = int(value) if value else 0
                    except:
                        value = 0
                elif field in ['sister_revenue', 'reward_amount']:
                    try:
                        value = float(value) if value else 0.0
                    except:
                        value = 0.0
                elif field == 'form_date':
                    # 规范化日期格式：从 "MM-DD星期X" 转换为 "YYYY-MM-DD"
                    import re
                    m = re.match(r'(\d{2})-(\d{2})星期.', value)
                    if m:
                        from datetime import datetime
                        year = datetime.now().year
                        value = f'{year}-{m.group(1)}-{m.group(2)}'
                record[field] = value
        
        return record if 'team_id' in record else None
    
    def save_detail(self, data: list):
        conn = get_db()
        inserted = 0

        # 幂等：写入前先删除当天旧快照，避免一天多次抓取产生重复行
        if data:
            snap = data[0].get('snapshot_date')
            if snap:
                conn.execute('DELETE FROM team_detail WHERE snapshot_date = ?', (snap,))

        for row in data:
            try:
                conn.execute('''
                    INSERT INTO team_detail 
                    (team_id, form_date, hall_name, sister_uid, sister_nickname, sister_level,
                     sister_uid2, sister_nickname2, sister_level2, sister_max_level2, sister_revenue,
                     drive_task_count, accompany_task_count, gift_task_count, level_achievement_count,
                     revenue_achievement_count, silver_box_achievement, days_since_formed,
                     reward_amount, dissolve_date, dissolve_reason, snapshot_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    row.get('team_id'), row.get('form_date'), row.get('hall_name'),
                    row.get('sister_uid'), row.get('sister_nickname'), row.get('sister_level'),
                    row.get('sister_uid2'), row.get('sister_nickname2'), row.get('sister_level2'),
                    row.get('sister_max_level2'), row.get('sister_revenue', 0.0),
                    row.get('drive_task_count', 0), row.get('accompany_task_count', 0),
                    row.get('gift_task_count', 0), row.get('level_achievement_count', 0),
                    row.get('revenue_achievement_count', 0), row.get('silver_box_achievement', 0),
                    row.get('days_since_formed', 0), row.get('reward_amount', 0.0),
                    row.get('dissolve_date'), row.get('dissolve_reason'), row.get('snapshot_date')
                ))
                inserted += 1
            except Exception as e:
                print(f'[WARN] 插入失败: {e}')
        
        conn.commit()
        conn.close()
        print(f'[DB] 已保存 {inserted} 条基础数据明细')
    
    def crawl_trend(self, metric: str = 'new_team_count', hall: str = 'all',
                    date_type: int = 1) -> list:
        """
        抓取折线图趋势数据 (/sisters/getlineData)
        ✅ 【不需要登录】公开API，Cookie 过期也能正常抓取
        数据：留存率、解散率、新成团数等时间序列数据
        """
        url = f'{self.BASE_URL}/sisters/getlineData?group={hall}&game_id=all&date_type={date_type}&ad_id=0&ad=%E6%80%BB%E8%A7%88&data_start=0&data_end=0'
        print(f'[Crawl] 抓取趋势数据: {metric}, type={date_type}')
        
        try:
            resp = self.session.get(url, timeout=15)
            if self._check_login(resp.text):
                raise Exception('Cookie已过期')
            
            data = resp.json()
            dates = data.get('date', [])
            values = data.get('data', [])
            title = data.get('title', 'unknown')
            
            records = []
            for d, v in zip(dates, values):
                records.append({
                    'metric_name': metric,
                    'hall_name': hall,
                    'date_type': date_type,
                    'date_label': d,
                    'value': float(v) if v is not None else 0.0,
                })
            
            print(f'[Crawl] 趋势数据: {title}, {len(records)} 个数据点')
            log_crawl('trend_data', 'success', len(records))
            return records
            
        except Exception as e:
            print(f'[ERROR] 趋势数据抓取失败: {e}')
            log_crawl('trend_data', 'failed', error_message=str(e))
            raise
    
    def save_trend(self, data: list):
        conn = get_db()
        inserted = 0
        
        for row in data:
            try:
                conn.execute('''
                    INSERT OR REPLACE INTO trend_data 
                    (metric_name, hall_name, date_type, date_label, value)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    row['metric_name'], row['hall_name'], row['date_type'],
                    row['date_label'], row['value']
                ))
                inserted += 1
            except Exception as e:
                print(f'[WARN] 插入失败: {e}')
        
        conn.commit()
        conn.close()
        print(f'[DB] 已保存 {inserted} 条趋势数据')

    def aggregate_hall_stats(self) -> list:
        """
        从 team_detail 表聚合分厅统计数据
        ⚠️ 依赖 crawl_detail() 先执行，确保 team_detail 有最新数据
        """
        conn = get_db()
        snapshot_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            # 按大厅聚合：统计各厅的团数、进行中数、解散数、总流水、总奖励
            # 按 team_id 去重（防御历史快照中的重复行）
            cursor = conn.execute('''
                SELECT 
                    hall_name,
                    COUNT(*) as team_count,
                    SUM(CASE WHEN dissolve_date = '' OR dissolve_date IS NULL THEN 1 ELSE 0 END) as active_count,
                    SUM(CASE WHEN dissolve_date != '' AND dissolve_date IS NOT NULL THEN 1 ELSE 0 END) as dissolved_count,
                    SUM(sister_revenue) as total_revenue,
                    SUM(reward_amount) as total_reward
                FROM team_detail
                WHERE rowid IN (SELECT MAX(rowid) FROM team_detail
                                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM team_detail)
                                GROUP BY team_id)
                GROUP BY hall_name
                ORDER BY team_count DESC
            ''')
            
            rows = cursor.fetchall()
            stats = []
            for row in rows:
                stats.append({
                    'snapshot_date': snapshot_date,
                    'hall_name': row['hall_name'],
                    'team_count': row['team_count'],
                    'active_count': row['active_count'],
                    'dissolved_count': row['dissolved_count'],
                    'total_revenue': round(row['total_revenue'] or 0, 2),
                    'total_reward': round(row['total_reward'] or 0, 2),
                })
            
            print(f'[Aggregate] 聚合完成: {len(stats)} 个大厅')
            return stats
            
        except Exception as e:
            print(f'[ERROR] 分厅聚合失败: {e}')
            raise
        finally:
            conn.close()
    
    def save_hall_stats(self, data: list):
        conn = get_db()
        inserted = 0
        
        for row in data:
            try:
                conn.execute('''
                    INSERT OR REPLACE INTO hall_stats
                    (snapshot_date, hall_name, team_count, active_count, dissolved_count, total_revenue, total_reward)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    row['snapshot_date'], row['hall_name'], row['team_count'],
                    row['active_count'], row['dissolved_count'],
                    row['total_revenue'], row['total_reward']
                ))
                inserted += 1
            except Exception as e:
                print(f'[WARN] 插入失败: {e}')
        
        conn.commit()
        conn.close()
        print(f'[DB] 已保存 {inserted} 条分厅统计数据')


    def crawl_hall_daily_revenue(self) -> list:
        """
        抓取大厅日流水（/roomnew/indextest/4 大厅主题页）
        该页展示最近一个完整天的全部大厅数据，含「厅总流水」字段
        """
        url = f'{self.BASE_URL}/roomnew/indextest/4'
        print(f'[Crawl] 抓取大厅日流水: {url}')
        try:
            resp = self.session.get(url, timeout=90)
            if self._check_login(resp.text):
                raise Exception('Cookie已过期，需要重新登录')
            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.find_all('table')
            if not tables:
                raise Exception('页面未找到数据表格')
            table = tables[0]
            rows = table.find_all('tr')
            headers = [c.get_text(strip=True) for c in rows[0].find_all(['td', 'th'])]
            col = {name: i for i, name in enumerate(headers)}
            data = []
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all('td')]
                if len(cells) < len(headers):
                    continue
                try:
                    revenue = float(cells[col['厅总流水']].replace(',', '') or 0)
                except (ValueError, KeyError):
                    revenue = 0.0
                data.append({
                    'date': cells[col['日期']],
                    'hall_id': cells[col['大厅ID']],
                    'hall_name': cells[col['大厅名称']],
                    'hall_revenue': revenue,
                })
            print(f'[Crawl] 大厅日流水抓取完成: {len(data)} 个厅, 日期 {data[0]["date"] if data else "-"}')
            log_crawl('hall_revenue_daily', 'success', len(data))
            return data
        except Exception as e:
            print(f'[ERROR] 大厅日流水抓取失败: {e}')
            log_crawl('hall_revenue_daily', 'failed', error_message=str(e))
            raise

    def save_hall_daily_revenue(self, data: list):
        conn = get_db()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS hall_revenue_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                hall_id TEXT,
                hall_name TEXT,
                hall_revenue REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, hall_id)
            )
        ''')
        inserted = 0
        for d in data:
            conn.execute(
                'INSERT OR REPLACE INTO hall_revenue_daily (date, hall_id, hall_name, hall_revenue) VALUES (?, ?, ?, ?)',
                (d['date'], d['hall_id'], d['hall_name'], d['hall_revenue']))
            inserted += 1
        conn.commit()
        conn.close()
        print(f'[DB] 已保存 {inserted} 条大厅日流水')


def run_all():
    print('=' * 50)
    print('姐妹团数据抓取开始')
    print(f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)
    
    crawler = SistersCrawler()
    
    print('\n--- [1/4] 统计数据 ---')
    stats_data = crawler.crawl_stats()
    crawler.save_stats(stats_data)
    
    print('\n--- [2/4] 基础数据明细 ---')
    detail_data = crawler.crawl_detail()
    crawler.save_detail(detail_data)
    
    print('\n--- [3/4] 趋势数据 ---')
    trend_data = crawler.crawl_trend(metric='new_team_count', date_type=1)
    crawler.save_trend(trend_data)
    
    print('\n--- [4/5] 分厅统计聚合 ---')
    hall_stats = crawler.aggregate_hall_stats()
    crawler.save_hall_stats(hall_stats)

    print('\n--- [5/5] 大厅日流水 ---')
    try:
        hall_revenue = crawler.crawl_hall_daily_revenue()
        crawler.save_hall_daily_revenue(hall_revenue)
    except Exception as e:
        print(f'[WARN] 大厅日流水抓取失败（不影响主流程）: {e}')
    
    print('\n' + '=' * 50)
    print('全部抓取完成')
    print('=' * 50)


if __name__ == '__main__':
    from db import init_db
    init_db()
    run_all()
