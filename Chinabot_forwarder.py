"""
Chinabot_forwarder.py - 转发和置顶消息管理
"""
import logging
from typing import Dict, Any, Optional
from telethon import TelegramClient
from Chinabot_utils import beijing_now, beijing_format, beijing_date_str, truncate_text, save_config
from Chinabot_db import ChinabotDB

logger = logging.getLogger(__name__)

EMOJI_COUNTRY = {
    '坦桑尼亚':'🇹🇿','肯尼亚':'🇰🇪','印度':'🇮🇳','阿联酋':'🇦🇪','尼日利亚':'🇳🇬',
    '美国':'🇺🇸','德国':'🇩🇪','日本':'🇯🇵','韩国':'🇰🇷','越南':'🇻🇳','泰国':'🇹🇭',
    '印尼':'🇮🇩','马来西亚':'🇲🇾','菲律宾':'🇵🇭','新加坡':'🇸🇬','英国':'🇬🇧',
    '法国':'🇫🇷','意大利':'🇮🇹','西班牙':'🇪🇸','俄罗斯':'🇷🇺','巴西':'🇧🇷',
    '墨西哥':'🇲🇽','阿根廷':'🇦🇷','土耳其':'🇹🇷','埃及':'🇪🇬','南非':'🇿🇦',
    '巴基斯坦':'🇵🇰','澳大利亚':'🇦🇺','加拿大':'🇨🇦',
}

EMOJI_BIZ = {
    '刷单':'📦','精刷':'✨','大区':'🌍','盗刷':'⚠️','渗透':'🔍',
    '换汇':'💱','换汇杀':'💀','无视':'🚫','公检法':'⚖️',
    '一类':'1️⃣','二类':'2️⃣','三类':'3️⃣',
}


class ChinabotForwarder:
    def __init__(self, client: TelegramClient, config: Dict, db: ChinabotDB):
        self.client = client
        self.config = config
        self.db = db
        self.fwd = config.get('forward', {})
        self.countries = config.get('countries', [])
        self.max_members = config.get('channel_group', {}).get('max_members', 50)

    def _fwd_id(self) -> Optional[int]:
        if self.fwd.get('enabled') and self.fwd.get('group_id'):
            return self.fwd['group_id']
        return None

    def _emoji_country(self, name: str) -> str:
        return EMOJI_COUNTRY.get(name, '🏳️')

    def _emoji_biz(self, name: str) -> str:
        return EMOJI_BIZ.get(name, '💼')

    async def send_notification(self, quote: Dict, changes: list = None) -> bool:
        fwd_id = self._fwd_id()
        if not fwd_id:
            return False

        c = quote.get('country','未知')
        b = quote.get('business_type','未知')
        rate = quote.get('rate', 0)
        ex = quote.get('exchange_rate', 0)
        fee = quote.get('single_fee', 0)
        qtype = quote.get('quote_type', '代收')
        cur = quote.get('currency', '')
        settlement = quote.get('settlement', '')
        group = quote.get('group_name', '')
        link = quote.get('message_link', '')
        sender = quote.get('sender_name', '')

        parts = []
        if fee > 0:
            parts.append(f'💳 单笔: <b>{fee}</b>')
        if rate > 0:
            parts.append(f'📊 费率: <b>{rate}</b>')
        if ex > 0:
            parts.append(f'💱 汇率: <b>{ex}</b>')
        if settlement:
            parts.append(f'📋 结算: {settlement}')

        msg = f'🆕 <b>新报价</b> {self._emoji_country(c)} {c} | {self._emoji_biz(b)} {b}\n'
        msg += '\n'.join(parts) if parts else '无价格数据'
        msg += f'\n\n📍 <a href="{link}">{group}</a>\n👤 {sender}\n🕐 {beijing_format(beijing_now())}\n🏷️ {qtype}'
        if changes:
            msg += f'\n📈 <b>变化:</b> {", ".join(changes)}'

        try:
            await self.client.send_message(fwd_id, msg, parse_mode='HTML', link_preview=False)
            logger.info(f"新报价通知已发送: {c} {b}")
            return True
        except Exception as e:
            logger.error(f"发送通知失败: {e}")
            return False

    async def clean_large_groups(self):
        """清理超过人数限制的群"""
        for g in self.db.get_monitored_groups():
            try:
                chat = await self.client.get_entity(g['group_id'])

                # 判断群类型，用对应的方式获取人数
                if hasattr(chat, 'participants_count'):
                    # 超级群/频道
                    cnt = chat.participants_count or 0
                else:
                    # 普通群，跳过检查（普通群人数上限200，一般不超50）
                    continue

                if cnt > self.max_members:
                    self.db.remove_monitored_group(g['group_id'])
                    logger.info(f"清理大群: {g['group_name']} ({cnt}人)")
            except Exception as e:
                logger.debug(f"跳过群 {g['group_name']}: {e}")

    def generate_summary(self, date: str = None) -> str:
        snaps = self.db.get_snapshots()

        if not snaps:
            return '<b>📊 报价汇总</b>\n\n<blockquote>暂无报价数据</blockquote>'

        grouped = {}
        for s in snaps:
            country = s['country'] or '未知'
            biz = s['business_type'] or ''
            if country not in grouped:
                grouped[country] = {}
            if biz not in grouped[country]:
                grouped[country][biz] = []
            grouped[country][biz].append(s)

        lines = [f'<b>📊 报价汇总</b>', f'更新于 {beijing_format(beijing_now())}', '']

        for country in sorted(grouped.keys()):
            biz_dict = grouped[country]
            lines.append(f'<blockquote><b>{self._emoji_country(country)} {country}</b></blockquote>')

            for biz in sorted(biz_dict.keys()):
                items = biz_dict[biz]
                if biz:
                    lines.append(f'  · <b>{biz}</b>')
                for s in items:
                    gn = truncate_text(s.get('group_name', ''), 20)
                    link = s.get('message_link', '')
                    rate, ex, fee = s.get('rate',0), s.get('exchange_rate',0), s.get('single_fee',0)
                    qtype = s.get('quote_type', '代收')
                    cur = s.get('currency', '')
                    settle = s.get('settlement', '')

                    if qtype == '代付' and fee > 0:
                        p = f"单笔{fee}"
                        if rate > 0: p += f" 费{rate}"
                        if ex > 0: p += f" 汇{ex}"
                    elif rate > 0 and ex > 0:
                        p = f"费{rate} 汇{ex}"
                    elif ex > 0:
                        p = f"汇{ex}"
                    elif fee > 0:
                        p = f"单笔{fee}"
                    else:
                        continue
                    # 不显示货币缩写
                    if settle: p += f" {settle}"
                    tp = "代付" if qtype == '代付' else ""

                    if link:
                        line = f'  <a href="{link}">{gn}</a>: {p} {tp}'
                    else:
                        line = f'  {gn}: {p} {tp}'
                    lines.append(line)
            lines.append("")

        lines.append(f'共 <b>{len(snaps)}</b> 条 | 覆盖 <b>{len(grouped)}</b> 个国家')
        lines.append(f'<i>🔄 每5分钟自动刷新 | 上次更新: {beijing_format(beijing_now())}</i>')
        return '\n'.join(lines)

    async def update_pinned(self) -> bool:
        fwd_id = self._fwd_id()
        if not fwd_id:
            return False
        try:
            await self.clean_large_groups()
            summary = self.generate_summary()
            pinned_id = self.fwd.get('pinned_message_id', 0)

            if pinned_id:
                try:
                    await self.client.edit_message(
                        fwd_id, pinned_id, summary,
                        parse_mode='HTML', link_preview=False
                    )
                    logger.info(f"置顶已更新: {pinned_id}")
                    return True
                except Exception as e:
                    logger.warning(f"编辑置顶失败: {e}，将重新创建")

            # 只有没有置顶消息时才新建
            msg = await self.client.send_message(
                fwd_id, summary,
                parse_mode='HTML', link_preview=False
            )
            await self.client.pin_message(fwd_id, msg.id)
            self.config['forward']['pinned_message_id'] = msg.id
            save_config(self.config)
            logger.info(f"新置顶已创建: {msg.id}")
            return True

        except Exception as e:
            logger.error(f"更新置顶失败: {e}", exc_info=True)
            return False