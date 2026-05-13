"""
Chinabot_handlers.py - 消息处理模块（重写版）
"""
import time
import logging
import asyncio
from telethon import events
from telethon.tl.types import Channel, Chat
from telethon.tl.functions.channels import GetFullChannelRequest

from Chinabot_utils import beijing_now, beijing_format, beijing_date_str, get_channel_message_link, save_config
from Chinabot_extractor import QuoteExtractor

logger = logging.getLogger(__name__)

QUESTION_WORDS = ['什么价', '多少钱', '价格', '报价', '汇率', '询价', '问价', '点位', 'today', 'rate', 'price']


class ChinabotHandlers:
    def __init__(self, client, config, db, commands, forwarder):
        self.client = client
        self.config = config
        self.db = db
        self.commands = commands
        self.forwarder = forwarder

        self.owner_id = config.get('admin', {}).get('owner_id', 0)
        self.colleagues = config.get('admin', {}).get('colleagues', [])
        self.max_members = config.get('channel_group', {}).get('max_members', 50)
        self.countries = config.get('countries', [])
        self.businesses = config.get('business_types', [])

        self.extractor = QuoteExtractor(self.countries, self.businesses, self.colleagues, self.owner_id)

        # 上下文缓存: {group_id: [msgs]}
        self.context = {}
        self.processed = set()
        self._pending_question = {}  # {group_id: {country, business, is_daifu, timestamp, messages: []}}

        logger.info("消息处理器初始化完成")

    def register(self):
        @self.client.on(events.NewMessage)
        async def on_msg(event):
            try:
                chat = await event.get_chat()
                sender = await event.get_sender()
                txt = event.message.text or ''

                if event.is_private:
                    if txt.startswith('/'):
                        await self._cmd(event.message, chat, sender)
                    return
                if not (event.is_group or event.is_channel):
                    return
                if txt.startswith('/'):
                    await self._cmd(event.message, chat, sender)
                    return
                await self._handle(event)
            except Exception as e:
                logger.error(f"消息处理异常: {e}", exc_info=True)

        @self.client.on(events.ChatAction)
        async def on_leave(event):
            """退出群组时清理该群的所有报价"""
            try:
                if event.user_left and event.user_id == self.owner_id:
                    cid = event.chat_id
                    self.db.remove_monitored_group(cid)
                    logger.info(f"已退出群组 {cid}，清理报价数据")
                    await self.forwarder.update_pinned()
            except Exception as e:
                logger.error(f"退出群组处理异常: {e}")

        logger.info("事件处理器注册完成")

    async def _cmd(self, msg, chat, sender):
        sid = sender.id if sender else 0
        cid = chat.id
        txt = msg.text or ''

        # 获取命令名（去掉/和参数）
        cmd_name = txt.split()[0][1:] if txt.startswith('/') else ''
        # 特殊命令：手动刷新置顶
        if cmd_name in ('更新置顶', 'refresh'):
            await self.forwarder.update_pinned()
            await self.client.send_message(cid, "✅ 置顶消息已刷新")
            return

        # 转发群管理命令不受限制
        fwd_cmds = {'转发群', 'forward', 'fw', '黑名单', 'blacklist'}

        # 如果不是转发群命令，检查是否在转发群
        fwd_id = self.config.get('forward', {}).get('group_id', 0)
        if fwd_id and cmd_name not in fwd_cmds and cid != fwd_id:
            return  # 静默忽略

        text = await self.commands.process(txt, sid, cid)
        await self.client.send_message(cid, text, parse_mode='markdown')

    async def _handle(self, event):
        msg = event.message
        chat = await event.get_chat()
        sender = await event.get_sender()

        cid = chat.id
        cname = getattr(chat, 'title', '未知群')
        sid = sender.id if sender else 0
        sname = getattr(sender, 'first_name', '未知')
        txt = msg.text or ''
        if not txt:
            return

        # 去重
        key = (cid, msg.id)
        if key in self.processed:
            return
        self.processed.add(key)

        # 自动注册
        if not self.db.is_monitored(cid):
            try:
                full = await self.client(GetFullChannelRequest(chat))
                cnt = full.full_chat.participants_count or 0
            except:
                cnt = 0
            if cnt <= self.max_members:
                self.db.add_monitored_group(cid, cname, cnt)
                logger.info(f"注册通道群: {cname} ({cnt}人)")
            else:
                logger.info(f"跳过群(>{self.max_members}人): {cname}")
                return

        # 缓存消息
        if cid not in self.context:
            self.context[cid] = []
        self.context[cid].append({
            'sender_id': sid, 'sender_name': sname,
            'text': txt, 'timestamp': beijing_format(beijing_now()),
            'group_name': cname,
        })
        # 保留今天
        today = beijing_date_str()
        self.context[cid] = [m for m in self.context[cid] if m['timestamp'].startswith(today)]
        if len(self.context[cid]) > 1000:
            self.context[cid] = self.context[cid][-500:]

        # 判断角色
        is_colleague = self.extractor.is_colleague(sid)
        is_question = any(kw in txt.lower() for kw in QUESTION_WORDS) or '?' in txt or '？' in txt

        if is_colleague and is_question:
            new_country = self.extractor.find_country(txt)
            new_biz = self.extractor.find_business(txt)

            # 提到了新国家或新业务 → 重置缓存
            if new_country or new_biz:
                self._pending_question[cid] = {
                    'country': new_country,
                    'business': new_biz,
                    'is_daifu': '代付' in txt,
                    'messages': [],
                }
            else:
                # 追问，保留之前的缓存；如果没有缓存则创建
                if cid not in self._pending_question:
                    self._pending_question[cid] = {
                        'country': None, 'business': None,
                        'is_daifu': False, 'messages': [],
                    }
            return

        # 客户消息 → 提取报价
        if not is_colleague:
            extracted = self.extractor.extract(txt, cname)
            if not extracted:
                return

            pending = self._pending_question.get(cid)

            # 处理多报价
            if extracted.get('multi_quotes'):
                for i, single in enumerate(extracted['multi_quotes']):
                    if pending:
                        if pending['country']:
                            single['country'] = pending['country']
                        if pending['business']:
                            single['business_type'] = pending['business']
                        if pending['is_daifu']:
                            single['quote_type'] = '代付'
                    await self._save_and_notify(single, msg, cid, cname, sname)
                return

            if pending:
                if pending['country']:
                    extracted['country'] = pending['country']
                if pending['business']:
                    extracted['business_type'] = pending['business']
                if pending['is_daifu']:
                    extracted['quote_type'] = '代付'

                pending['messages'].append(extracted)
                merged = self.extractor.merge(pending['messages'])
                if merged:
                    if pending['country']:
                        merged['country'] = pending['country']
                    if pending['business']:
                        merged['business_type'] = pending['business']
                    if pending['is_daifu']:
                        merged['quote_type'] = '代付'
                    await self._save_and_notify(merged, msg, cid, cname, sname)
            else:
                await self._save_and_notify(extracted, msg, cid, cname, sname)

    async def _save_and_notify(self, data, msg, cid, cname, sname):
        # 查旧价格
        old_snaps = self.db.get_snapshots()
        old_rate, old_ex, old_fee = 0, 0, 0
        for snap in old_snaps:
            if (snap['group_id'] == cid and 
                snap['country'] == data.get('country') and
                snap['business_type'] == data.get('business_type')):
                old_rate = snap.get('rate', 0)
                old_ex = snap.get('exchange_rate', 0)
                old_fee = snap.get('single_fee', 0)
                break

        # 去重
        new_rate, new_ex, new_fee = data.get('rate',0), data.get('exchange_rate',0), data.get('single_fee',0)
        if (old_rate == new_rate and old_ex == new_ex and old_fee == new_fee):
            return

        data.update({
            'group_id': cid, 'group_name': cname,
            'message_id': msg.id, 'message_link': get_channel_message_link(cid, msg.id),
            'sender_name': sname, 'original_text': msg.text or '',
            'confidence': 0.8,
        })
        self.db.add_quote(data)
        self.db.update_snapshot(data)

        # 构建变化提示
        changes = []
        if old_rate or old_ex or old_fee:
            if new_rate != old_rate:
                arrow = '↓' if new_rate < old_rate else '↑'
                changes.append(f'费率 {old_rate}→{new_rate} {arrow}')
            if new_ex != old_ex:
                arrow = '↓' if new_ex < old_ex else '↑'
                changes.append(f'汇率 {old_ex}→{new_ex} {arrow}')
            if new_fee != old_fee:
                changes.append(f'单笔 {old_fee}→{new_fee}')

        await self.forwarder.send_notification(data, changes if changes else None)

        # 异常汇率告警（不变）
        country_cfg = None
        for c in self.countries:
            if c['name'] == data.get('country'):
                country_cfg = c
                break
        if country_cfg and data.get('exchange_rate', 0) > 0:
            rng = country_cfg.get('usd_rate_range', [0, 0])
            ex = data['exchange_rate']
            if rng[0] > 0 and (ex < rng[0] * 0.1 or ex > rng[1] * 3.0):
                fwd_id = self.config.get('forward', {}).get('group_id', 0)
                if fwd_id:
                    await self.client.send_message(
                        fwd_id,
                        f"⚠️ **汇率异常告警**\n"
                        f"国家: {data['country']}\n"
                        f"汇率: {ex} {data.get('currency', '')}\n"
                        f"参考范围: {rng[0]}-{rng[1]}\n"
                        f"来源: [{data.get('group_name', '')}]({data.get('message_link', '')})",
                        parse_mode='markdown', link_preview=False
                    )

        await self.forwarder.update_pinned()

        logger.info(f"报价提取: {data.get('country')} {data.get('business_type')}")

    def _is_group(self, chat) -> bool:
        return isinstance(chat, (Chat, Channel)) and not getattr(chat, 'broadcast', False)

    async def classify_groups(self):
        logger.info("分类群组...")
        dialogs = await self.client.get_dialogs()
        ch = 0
        for d in dialogs:
            chat = d.entity
            if not self._is_group(chat):
                continue
            cid = chat.id
            cname = getattr(chat, 'title', '未知')
            try:
                full = await self.client(GetFullChannelRequest(chat))
                cnt = full.full_chat.participants_count or 0
            except:
                cnt = 10
            if cnt <= self.max_members:
                self.db.add_monitored_group(cid, cname, cnt)
                ch += 1
            else:
                self.db.remove_monitored_group(cid)
        logger.info(f"分类完成: {ch}个通道群")

    async def periodic_cleanup(self):
        while True:
            try:
                today = beijing_date_str()
                for cid in list(self.context.keys()):
                    self.context[cid] = [m for m in self.context[cid] if m['timestamp'].startswith(today)]
                if len(self.processed) > 50000:
                    self.processed.clear()
                now = beijing_now()
                if now.hour == 2 and now.minute == 0:
                    self.db.backup()
            except Exception as e:
                logger.error(f"清理异常: {e}")
            await asyncio.sleep(3600)

    async def periodic_pinned(self):
        while True:
            try:
                now = beijing_now()
                if now.hour == 9 and now.minute < 5:
                    await self.forwarder.update_pinned()
                    logger.info("9点全量刷新置顶")
                await asyncio.sleep(300)
            except Exception as e:
                logger.error(f"置顶更新异常: {e}")
                await asyncio.sleep(60)
