"""
Chinabot_db.py - 数据库模块
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from Chinabot_utils import beijing_now, beijing_format, beijing_date_str

logger = logging.getLogger(__name__)


class ChinabotDB:
    def __init__(self, db_path: str = "Chinabot_data/Chinabot_data.db"):
        self.db_path = db_path
        self._init()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init(self):
        with self._conn() as conn:
            c = conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS quote_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER, group_name TEXT,
                message_id INTEGER, message_link TEXT,
                country TEXT, business_type TEXT,
                rate REAL DEFAULT 0, exchange_rate REAL DEFAULT 0,
                single_fee REAL DEFAULT 0, quote_type TEXT DEFAULT '代收',
                currency TEXT, settlement TEXT,
                sender_id INTEGER, sender_name TEXT,
                original_text TEXT, confidence REAL DEFAULT 0.8,
                beijing_time TEXT, date TEXT, created_at TEXT
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS daily_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER, group_name TEXT,
                country TEXT, business_type TEXT,
                rate REAL DEFAULT 0, exchange_rate REAL DEFAULT 0,
                single_fee REAL DEFAULT 0, quote_type TEXT DEFAULT '代收',
                currency TEXT, settlement TEXT,
                message_link TEXT, sender_name TEXT,
                date TEXT, updated_at TEXT,
                UNIQUE(group_id, country, business_type, date)
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS group_monitor (
                group_id INTEGER PRIMARY KEY,
                group_name TEXT,
                member_count INTEGER,
                is_monitored INTEGER DEFAULT 1,
                added_at TEXT,
                updated_at TEXT
            )''')

            c.execute('''CREATE INDEX IF NOT EXISTS idx_snap_date ON daily_snapshots(date)''')
            c.execute('''CREATE INDEX IF NOT EXISTS idx_quote_date ON quote_records(date)''')

        logger.info("数据库初始化完成")

    # ========== 报价记录 ==========
    def add_quote(self, data: Dict) -> int:
        with self._conn() as conn:
            now = beijing_format(beijing_now())
            today = beijing_date_str()
            conn.execute('''INSERT INTO quote_records
                (group_id,group_name,message_id,message_link,country,business_type,
                 rate,exchange_rate,single_fee,quote_type,currency,settlement,
                 sender_id,sender_name,original_text,confidence,
                 beijing_time,date,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (data.get('group_id'), data.get('group_name'),
                 data.get('message_id'), data.get('message_link'),
                 data.get('country'), data.get('business_type'),
                 data.get('rate', 0), data.get('exchange_rate', 0),
                 data.get('single_fee', 0), data.get('quote_type', '代收'),
                 data.get('currency', ''), data.get('settlement', ''),
                 data.get('sender_id'), data.get('sender_name'),
                 data.get('original_text', ''), data.get('confidence', 0.8),
                 now, today, now))
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_snapshot(self, data: Dict):
        with self._conn() as conn:
            now = beijing_format(beijing_now())
            today = beijing_date_str()
            conn.execute('''INSERT OR REPLACE INTO daily_snapshots
                (group_id,group_name,country,business_type,
                 rate,exchange_rate,single_fee,quote_type,currency,settlement,
                 message_link,sender_name,date,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (data.get('group_id'), data.get('group_name'),
                 data.get('country'), data.get('business_type'),
                 data.get('rate', 0), data.get('exchange_rate', 0),
                 data.get('single_fee', 0), data.get('quote_type', '代收'),
                 data.get('currency', ''), data.get('settlement', ''),
                 data.get('message_link'), data.get('sender_name'),
                 today, now))

    def get_snapshots(self, date: str = None) -> List[Dict]:
        with self._conn() as conn:
            if date:
                rows = conn.execute(
                    "SELECT * FROM daily_snapshots WHERE date=? ORDER BY country, business_type",
                    (date,)).fetchall()
            else:
                # 不限日期，返回所有最新快照
                rows = conn.execute('''
                    SELECT * FROM daily_snapshots 
                    WHERE (group_id, country, business_type, updated_at) IN (
                        SELECT group_id, country, business_type, MAX(updated_at)
                        FROM daily_snapshots GROUP BY group_id, country, business_type
                    )
                    ORDER BY country, business_type
                ''').fetchall()
            return [dict(r) for r in rows]

    def get_quote_history(self, country: str = None, business: str = None,
                          date: str = None, limit: int = 50) -> List[Dict]:
        with self._conn() as conn:
            q = "SELECT * FROM quote_records WHERE 1=1"
            params = []
            if country:
                q += " AND country=?"; params.append(country)
            if business:
                q += " AND business_type=?"; params.append(business)
            if date:
                q += " AND date=?"; params.append(date)
            q += " ORDER BY beijing_time DESC LIMIT ?"; params.append(limit)
            return [dict(r) for r in conn.execute(q, params).fetchall()]

    # ========== 群组管理 ==========
    def add_monitored_group(self, group_id: int, group_name: str, member_count: int):
        with self._conn() as conn:
            now = beijing_format(beijing_now())
            conn.execute('''INSERT OR REPLACE INTO group_monitor
                (group_id,group_name,member_count,is_monitored,added_at,updated_at)
                VALUES(?,?,?,1,?,?)''',
                (group_id, group_name, member_count, now, now))

    def is_monitored(self, group_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT is_monitored FROM group_monitor WHERE group_id=?",
                (group_id,)).fetchone()
            return row is not None and row[0] == 1

    def get_monitored_groups(self) -> List[Dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM group_monitor WHERE is_monitored=1").fetchall()]

    def remove_monitored_group(self, group_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM group_monitor WHERE group_id=?", (group_id,))
            today = beijing_date_str()
            conn.execute("DELETE FROM daily_snapshots WHERE group_id=? AND date=?",
                        (group_id, today))
            conn.execute("DELETE FROM quote_records WHERE group_id=? AND date=?",
                        (group_id, today))

    # ========== 统计 ==========
    def get_stats(self) -> Dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM quote_records").fetchone()[0]
            today = conn.execute(
                "SELECT COUNT(*) FROM quote_records WHERE date=?",
                (beijing_date_str(),)).fetchone()[0]
            groups = conn.execute(
                "SELECT COUNT(*) FROM group_monitor WHERE is_monitored=1").fetchone()[0]
            return {'total_quotes': total, 'today_quotes': today, 'channel_groups': groups}

    def backup(self):
        import shutil
        from pathlib import Path
        backup_dir = Path("Chinabot_data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = backup_dir / f"Chinabot_{ts}.db"
        shutil.copy2(self.db_path, dst)
        # 保留最近7个
        backups = sorted(backup_dir.glob("Chinabot_*.db"))
        for old in backups[:-7]:
            old.unlink()
        logger.info(f"数据库已备份到 {dst}")