"""
Chinabot_utils.py - 工具函数模块
"""
import os
import re
import yaml
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)

def beijing_format(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BEIJING_TZ)
    else:
        dt = dt.astimezone(BEIJING_TZ)
    return dt.strftime(fmt)

def beijing_date_str() -> str:
    return beijing_now().strftime("%Y-%m-%d")

def load_config(path: str = "Chinabot_config.yaml") -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_config(config: Dict[str, Any], path: str = "Chinabot_config.yaml") -> bool:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False

def clean_message_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff]', '', text.strip())
    text = re.sub(r'\s+', ' ', text)
    return text

def get_channel_message_link(chat_id: int, message_id: int) -> str:
    cid = str(chat_id).replace('-100', '').replace('-', '')
    return f"https://t.me/c/{cid}/{message_id}"

def truncate_text(text: str, max_len: int = 30) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len-3] + "..."