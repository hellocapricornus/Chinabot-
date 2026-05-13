"""
Chinabot_extractor.py - 报价提取器（纯关键词+正则）
"""
import re
import logging
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

RE_SLASH = re.compile(r'(?<!\d)(\d+\.?\d*)\s*/\s*(\d+\.?\d*)(?!\d)')
RE_SPACE = re.compile(r'(?<!\d)(\d+\.?\d*)\s+(\d+\.?\d*)(?!\d)')
RE_DASH  = re.compile(r'(?<!\d)(\d+\.?\d*)\s*-\s*(\d+\.?\d*)(?!\d)')
RE_RATE_WORD  = re.compile(r'(?:费率|费)\s*(\d+\.?\d*)')
RE_EXCH_WORD  = re.compile(r'(?:代收)?(?:汇率|汇|二道汇率|点位)\s*(\d+\.?\d*)')
RE_PERCENT    = re.compile(r'(\d+\.?\d*)\s*%')
RE_SINGLE_FEE = re.compile(r'单笔费用\s*([\d.]+)\s*([WwKk百千万]?)')
RE_RANGE = re.compile(r'单笔\s*([\d.]+)\s*[Ww万]?\s*[-~到]\s*([\d.]+)\s*[Ww万]?')
RE_SETTLEMENT = re.compile(r'(进算|拖算)')
SKIP = ['还没上班', '稍等', '等一下', '没有', '不报', '不知道', '休息', '明天', '暂停', '不接']


class QuoteExtractor:
    def __init__(self, countries: List[Dict], businesses: List[Dict], colleagues: List[int], owner_id: int = 0):
        self.colleagues = colleagues
        self.owner_id = owner_id

        self.country_map = {}
        for c in countries:
            for kw in [c['name']] + c.get('aliases', []):
                self.country_map[kw.lower()] = c['name']

        self.biz_map = {}
        for b in businesses:
            for kw in [b['name']] + b.get('aliases', []):
                self.biz_map[kw.lower()] = b['name']

        self.country_config = {c['name']: c for c in countries}

    def is_colleague(self, uid: int) -> bool:
        return uid in self.colleagues or uid == self.owner_id

    def find_country(self, text: str) -> Optional[str]:
        t = text.lower()
        best = None
        best_len = 0
        sep = ' \n\r,，.。!！?？:：;；-、()（）[]【】\t🔥✅💯⚠️❗❓➡️👉👈☝️💱💰📊🆕'
        for kw, name in self.country_map.items():
            idx = t.find(kw)
            if idx == -1:
                continue
            before = t[idx-1] if idx > 0 else ' '
            after = t[idx+len(kw)] if idx+len(kw) < len(t) else ' '
            before_ok = idx == 0 or before in sep or ord(before) > 127
            after_ok = idx+len(kw) == len(t) or after in sep or ord(after) > 127
            if before_ok and after_ok and len(kw) > best_len:
                best = name
                best_len = len(kw)
        return best

    def find_business(self, text: str) -> Optional[str]:
        t = text.lower()
        best = None
        best_len = 0
        for kw, name in self.biz_map.items():
            if kw in t and len(kw) > best_len:
                best = name
                best_len = len(kw)
        return best

    def _smart_rate_exchange(self, a: float, b: float, country_config: Dict = None) -> Tuple[float, float]:
        rng = country_config.get('usd_rate_range', [0, 0]) if country_config else [0, 0]
        def in_range(v):
            return rng[0] > 0 and rng[0] * 0.3 <= v <= rng[1] * 2.0
        a_in = in_range(a)
        b_in = in_range(b)
        if a_in and not b_in:
            return (b, a)
        if b_in and not a_in:
            return (a, b)
        if a_in and b_in:
            center = (rng[0] + rng[1]) / 2
            a_dist = abs(a - center) / center
            b_dist = abs(b - center) / center
            if a_dist <= b_dist:
                return (b, a)
            else:
                return (a, b)
        if rng[0] > 0:
            if abs(b - rng[0]) < abs(a - rng[0]):
                return (a, b)
            else:
                return (b, a)
        if b <= 20 and a > b:
            return (a, b)
        return (a, b)

    def parse_rate_exchange(self, text: str, country_config: Dict = None) -> Optional[Tuple[float, float]]:
        m = RE_SLASH.search(text)
        if m:
            return self._smart_rate_exchange(float(m.group(1)), float(m.group(2)), country_config)
        m = RE_SPACE.search(text)
        if m:
            return self._smart_rate_exchange(float(m.group(1)), float(m.group(2)), country_config)
        m = RE_DASH.search(text)
        if m:
            return self._smart_rate_exchange(float(m.group(1)), float(m.group(2)), country_config)
        rate = None; exchange = None
        m = RE_RATE_WORD.search(text)
        if m: rate = float(m.group(1))
        m = RE_EXCH_WORD.search(text)
        if m: exchange = float(m.group(1))
        m = RE_PERCENT.search(text)
        if m and rate is None: rate = float(m.group(1))
        if rate is not None or exchange is not None:
            return (rate or 0, exchange or 0)
        return None

    def parse_single_fee(self, text: str) -> Optional[float]:
        if '单笔费用' not in text:
            return None
        m = RE_SINGLE_FEE.search(text)
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2).lower() if m.group(2) else ''
        if unit in ('w', '万'): val *= 10000
        elif unit == 'k': val *= 1000
        elif unit == '百': val *= 100
        elif unit == '千': val *= 1000
        return val

    def parse_range(self, text: str) -> Optional[str]:
        m = RE_RANGE.search(text)
        if m:
            return f"{m.group(1)}W-{m.group(2)}W"
        return None

    def parse_settlement(self, text: str) -> Optional[str]:
        m = RE_SETTLEMENT.search(text)
        return m.group(1) if m else None

    def has_skip(self, text: str) -> bool:
        return any(kw in text for kw in SKIP)

    def split_multi_quotes(self, text: str) -> list:
        t = text.lower()
        positions = []
        for kw, name in self.country_map.items():
            idx = t.find(kw)
            if idx != -1:
                positions.append((idx, len(kw), kw))
        positions.sort()

        filtered = []
        for i, (pos, length, kw) in enumerate(positions):
            overlapped = False
            for j, (pos2, length2, kw2) in enumerate(positions):
                if i != j and pos2 <= pos < pos2 + length2:
                    overlapped = True
                    break
            if not overlapped:
                filtered.append((pos, kw))

        if len(filtered) <= 1:
            logger.info(f"=== split: only 1 segment, returning full text")
            return [text] if text.strip() else []

        result = []
        for i, (pos, kw) in enumerate(filtered):
            start = pos
            end = filtered[i+1][0] if i+1 < len(filtered) else len(text)
            segment = text[start:end].strip()
            if segment:
                result.append(segment)
        return result

    def _extract_single(self, text: str, group_name: str = "") -> Optional[Dict]:
        if not text or self.has_skip(text):
            return None

        text = re.sub(r'https?://\S+', '', text)

        country = self.find_country(text) or self.find_country(group_name)

        # 盘口类型优先
        business = None
        m = re.search(r'盘口类型[：:]\s*(.+)', text)
        if m:
            biz_text = m.group(1).strip().rstrip('！!')
            biz_text = re.sub(r'^接', '', biz_text)
            business = self.find_business(biz_text) or biz_text
        if not business:
            business = self.find_business(text)

        cfg = self.country_config.get(country, {}) if country else {}
        result = {
            'country': country,
            'business_type': business or '',
            'rate': 0,
            'exchange_rate': 0,
            'single_fee': 0,
            'quote_type': '代收',
            'currency': cfg.get('currency', ''),
            'settlement': '',
        }

        re_parsed = self.parse_rate_exchange(text, cfg)
        if re_parsed:
            result['rate'] = re_parsed[0]
            result['exchange_rate'] = re_parsed[1]

        fee = self.parse_single_fee(text)
        if fee:
            result['single_fee'] = fee
            result['quote_type'] = '代付'

        s = self.parse_settlement(text)
        if s:
            result['settlement'] = s

        if result['exchange_rate'] == 0 and cfg:
            rng = cfg.get('usd_rate_range', [0, 0])
            pure = re.match(r'^\s*(\d+\.?\d*)\s*$', text.strip())
            if pure:
                v = float(pure.group(1))
                if rng[0] > 0 and rng[0] * 0.3 <= v <= rng[1] * 2.0:
                    result['exchange_rate'] = v
                elif rng[0] == 0 and v > 10:
                    result['exchange_rate'] = v

        m = re.search(r'(?:代收)?汇率\s*(\d+\.?\d*)', text)
        if result['exchange_rate'] == 0 and m:
            result['exchange_rate'] = float(m.group(1))
        m = re.search(r'点位[:\s]*代收\s*(\d+\.?\d*)', text)
        if m and result['rate'] == 0:
            result['rate'] = float(m.group(1))

        if result['exchange_rate'] == 0 and result['single_fee'] == 0 and result['rate'] == 0:
            return None

        return result

    def _merge_multi(self, results: List[Dict]) -> Dict:
        """合并多条报价为一条多报价记录"""
        if not results:
            return None
        merged = dict(results[0])
        merged['multi_quotes'] = results
        return merged

    def extract(self, text: str, group_name: str = "") -> Optional[Dict]:
        if not text or self.has_skip(text):
            return None

        text = re.sub(r'https?://\S+', '', text)

        # 多报价拆分
        segments = self.split_multi_quotes(text)
        if len(segments) > 1:
            results = []
            for seg in segments:
                r = self._extract_single(seg, group_name)
                if r:
                    results.append(r)
            if results:
                return self._merge_multi(results)
            return None

        return self._extract_single(text, group_name)

    def merge(self, messages: List[Dict]) -> Optional[Dict]:
        result = None
        for msg in sorted(messages, key=lambda m: m.get('timestamp', '')):
            e = self.extract(msg.get('text', ''), msg.get('group_name', ''))
            if not e:
                continue
            if result is None:
                result = e
            else:
                if e['exchange_rate'] > 0: result['exchange_rate'] = e['exchange_rate']
                if e['rate'] > 0: result['rate'] = e['rate']
                if e['single_fee'] > 0:
                    result['single_fee'] = e['single_fee']
                    result['quote_type'] = '代付'
                if e.get('business_type'): result['business_type'] = e['business_type']
                if e['settlement']: result['settlement'] = e['settlement']
        return result