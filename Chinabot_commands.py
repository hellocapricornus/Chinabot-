"""
Chinabot_commands.py - 命令处理模块
"""
import re
import logging
from typing import Dict, Any, List, Optional
from Chinabot_utils import save_config, beijing_format, beijing_now

logger = logging.getLogger(__name__)


class ChinabotCommands:
    def __init__(self, config: Dict, db, client=None, config_path: str = "Chinabot_config.yaml"):
        self.config = config
        self.db = db
        self.client = client
        self.config_path = config_path
        self._map = {
            '同事': self._colleague, 'colleague': self._colleague,
            '转发群': self._fwd, 'forward': self._fwd,
            '国家': self._country, 'country': self._country,
            '业务': self._biz, 'business': self._biz,
            '统计': self._stats, 'stats': self._stats,
            '帮助': self._help, 'help': self._help,
            '状态': self._status, 'status': self._status,
            '报价': self._query, 'quote': self._query,
            '趋势': self._trend, 'trend': self._trend,
            '更新置顶': self._refresh_pin, 'refresh': self._refresh_pin,
            '删除报价': self._del_quote, 'del': self._del_quote,
            '历史报价': self._history, 'history': self._history,
        }
        self._aliases = {
            '同事': ['同事','colleague','cl'],
            '转发群': ['转发群','forward','fw'],
            '国家': ['国家','country','ct'],
            '业务': ['业务','business','bs'],
            '统计': ['统计','stats','st'],
            '帮助': ['帮助','help','h'],
            '状态': ['状态','status'],
            '报价': ['报价','quote','q'],
        }

    def set_client(self, c): self.client = c

    def is_authorized(self, uid: int) -> bool:
        return uid == self.config.get('admin', {}).get('owner_id', 0) or \
               uid in self.config.get('admin', {}).get('colleagues', [])

    def _find_cmd(self, txt: str) -> Optional[str]:
        t = txt.lower().strip()
        if t in self._map: return t
        for name, aliases in self._aliases.items():
            if t in [a.lower() for a in aliases]: return name
        return None

    async def _del_quote(self, uid, args, cid, rf) -> str:
        if len(args) < 2:
            return "❌ 用法: /删除报价 国家名 业务名"
        country = args[0]
        business = args[1]

        # 从 daily_snapshots 删除
        with self.db._conn() as conn:
            conn.execute(
                "DELETE FROM daily_snapshots WHERE country=? AND business_type=?",
                (country, business))
            deleted = conn.rowcount if hasattr(conn, 'rowcount') else 0

        if deleted > 0:
            return f"✅ 已删除 {country} - {business} 的报价\n请手动 /更新置顶 刷新"
        return f"❌ 未找到 {country} - {business} 的报价"

    async def _refresh_pin(self, uid, args, cid, rf) -> str:
        """手动刷新置顶消息"""
        return "🔄 请使用 /refresh_pin 在转发群内执行"

    async def process(self, command: str, user_id: int, chat_id: int, reply_func=None) -> str:
        cmd = command.strip()
        if cmd in ('/', '/帮助', '/help'):
            return await self._help(user_id, [], chat_id, reply_func)

        if cmd.startswith('/'):
            cmd = cmd[1:]
        parts = cmd.strip().split()
        if not parts:
            return await self._help(user_id, [], chat_id, reply_func)

        name = self._find_cmd(parts[0])
        if name is None:
            return await self._help(user_id, [], chat_id, reply_func)

        if not self.is_authorized(user_id):
            return "❌ 你没有权限使用此命令"

        try:
            return await self._map[name](user_id, parts[1:], chat_id, reply_func)
        except Exception as e:
            logger.error(f"命令执行失败: {e}")
            return f"❌ 命令执行失败: {e}"

    async def _help(self, uid, args, cid, rf) -> str:
        return """📋 **Chinabot 命令帮助**

    **👥 同事管理**
    `/同事 add @用户名` — 添加同事
    `/同事 remove @用户名` — 删除同事
    `/同事 list` — 查看同事列表

    **📢 转发群**
    `/转发群 set` — 设置当前群为转发群
    `/转发群 remove` — 取消转发群
    `/转发群 info` — 查看转发群信息

    **🌍 国家管理**
    `/国家 add 国家名 币种 汇率低,汇率高` — 添加国家
    `/国家 remove 国家名` — 删除国家
    `/国家 list` — 查看国家列表

    **💼 业务管理**
    `/业务 add 业务名 别名1,别名2` — 添加业务
    `/业务 remove 业务名` — 删除业务
    `/业务 list` — 查看业务列表

    **💰 报价查询**
    `/报价` — 最新报价概览
    `/报价 国家名` — 查询指定国家最新报价
    `/历史报价 国家名` — 查询历史报价
    `/趋势 国家名` — 查看报价趋势
    `/删除报价 国家名 业务名` — 删除置顶报价

    **📊 系统**
    `/统计` — 统计信息
    `/状态` — 运行状态
    `/更新置顶` — 手动更新置顶消息

    💡 除 `/转发群` 外，其他命令仅限转发群内使用"""
    

    async def _colleague(self, uid, args, cid, rf) -> str:
        if not args: return "❌ 用法: /同事 add|remove|list"
        act = args[0].lower()
        cols = self.config.get('admin', {}).get('colleagues', [])

        if act == 'list':
            if not cols: return "📋 暂无同事"
            lines = ["📋 **同事列表**"]
            for i, cid_ in enumerate(cols, 1):
                try:
                    e = await self.client.get_entity(cid_)
                    lines.append(f"{i}. {e.first_name} (@{e.username or '无'}) ID:{cid_}")
                except:
                    lines.append(f"{i}. ID:{cid_}")
            return '\n'.join(lines)

        if act == 'add':
            if len(args) < 2: return "❌ 用法: /同事 add @用户名1 @用户名2 ..."
            added, failed = [], []
            for uname in args[1:]:
                uname = uname.replace('@', '').strip()
                if not uname: continue
                try:
                    e = await self.client.get_entity(f"@{uname}")
                except:
                    failed.append(f"@{uname}(找不到)")
                    continue
                if e.id in cols:
                    failed.append(f"@{uname}(已存在)")
                    continue
                cols.append(e.id)
                added.append(f"@{uname}")
            self.config['admin']['colleagues'] = cols
            save_config(self.config, self.config_path)
            msg = ""
            if added: msg += f"✅ 已添加: {', '.join(added)}\n"
            if failed: msg += f"❌ 失败: {', '.join(failed)}"
            return msg or "⚠️ 未添加任何人"

        if act == 'remove':
            if len(args) < 2: return "❌ 用法: /同事 remove @用户名1 @用户名2 ..."
            removed, failed = [], []
            for uname in args[1:]:
                uname = uname.replace('@', '').strip()
                if not uname: continue
                try:
                    e = await self.client.get_entity(f"@{uname}")
                except:
                    failed.append(f"@{uname}(找不到)")
                    continue
                if e.id not in cols:
                    failed.append(f"@{uname}(不在列表中)")
                    continue
                cols.remove(e.id)
                removed.append(f"@{uname}")
            self.config['admin']['colleagues'] = cols
            save_config(self.config, self.config_path)
            msg = ""
            if removed: msg += f"✅ 已移除: {', '.join(removed)}\n"
            if failed: msg += f"❌ 失败: {', '.join(failed)}"
            return msg or "⚠️ 未移除任何人"

        return "❌ 无效操作"

    async def _fwd(self, uid, args, cid, rf) -> str:
        if not args: return "❌ 用法: /转发群 set|remove|info"
        act = args[0].lower()
        if act == 'set':
            self.config['forward']['enabled'] = True
            self.config['forward']['group_id'] = cid
            save_config(self.config, self.config_path)
            return f"✅ 当前群已设为转发群 (ID:{cid})"
        elif act == 'remove':
            self.config['forward']['enabled'] = False
            self.config['forward']['group_id'] = 0
            self.config['forward']['pinned_message_id'] = 0
            save_config(self.config, self.config_path)
            return "✅ 转发群已取消"
        elif act == 'info':
            f = self.config['forward']
            return f"📋 转发群ID: {f['group_id']}, 置顶ID: {f.get('pinned_message_id',0)}, 启用: {f['enabled']}"
        return "❌ 无效操作"

    async def _country(self, uid, args, cid, rf) -> str:
        if not args: return "❌ 用法: /国家 add|remove|list"
        act = args[0].lower()
        countries = self.config.get('countries', [])
        if act == 'list':
            names = [c['name'] for c in countries]
            return "📋 **国家列表**\n" + '\n'.join(f"• {n}" for n in sorted(names)) if names else "📋 暂无国家"
        if act == 'remove':
            if len(args) < 2: return "❌ 用法: /国家 remove 国家名"
            n = args[1]
            self.config['countries'] = [c for c in countries if c['name'] != n]
            save_config(self.config, self.config_path)
            return f"✅ 已删除 {n}"
        if act == 'add':
            if len(args) < 2: return "❌ 用法: /国家 add 国家名 [币种] [汇率低,汇率高]"
            n = args[1]
            cur = args[2] if len(args) > 2 else ''
            rng = [0, 0]
            if len(args) > 3:
                m = re.match(r'(\d+\.?\d*)[,，](\d+\.?\d*)', args[3])
                if m: rng = [float(m.group(1)), float(m.group(2))]
            countries.append({'name': n, 'aliases': [], 'currency': cur, 'usd_rate_range': rng})
            self.config['countries'] = countries
            save_config(self.config, self.config_path)
            return f"✅ 已添加 {n}"
        return "❌ 无效操作"

    async def _biz(self, uid, args, cid, rf) -> str:
        if not args: return "❌ 用法: /业务 add|remove|list"
        act = args[0].lower()
        bizs = self.config.get('business_types', [])
        if act == 'list':
            return "📋 **业务列表**\n" + '\n'.join(f"• {b['name']}" for b in bizs) if bizs else "📋 暂无"
        if act == 'remove':
            if len(args) < 2: return "❌ 用法: /业务 remove 业务名"
            n = args[1]
            self.config['business_types'] = [b for b in bizs if b['name'] != n]
            save_config(self.config, self.config_path)
            return f"✅ 已删除 {n}"
        if act == 'add':
            if len(args) < 2: return "❌ 用法: /业务 add 业务名 [别名1,别名2]"
            n = args[1]
            aliases = [a.strip() for a in ' '.join(args[2:]).split(',') if a.strip()] if len(args) > 2 else []
            bizs.append({'name': n, 'aliases': aliases})
            self.config['business_types'] = bizs
            save_config(self.config, self.config_path)
            return f"✅ 已添加 {n}, 别名: {', '.join(aliases) or '无'}"
        return "❌ 无效操作"

    async def _stats(self, uid, args, cid, rf) -> str:
        s = self.db.get_stats()
        return f"📊 **统计**\n📝 总报价: {s['total_quotes']}\n📅 今日: {s['today_quotes']}\n📡 通道群: {s['channel_groups']}\n🕐 {beijing_format(beijing_now())}"

    async def _status(self, uid, args, cid, rf) -> str:
        fwd = self.config.get('forward', {})
        return f"🤖 **状态**\n📢 转发群: {'✅' if fwd.get('enabled') else '❌'}\n🌍 国家: {len(self.config.get('countries',[]))}个\n💼 业务: {len(self.config.get('business_types',[]))}个\n🧠 提取: 正则\n🕐 {beijing_format(beijing_now())}"

    async def _query(self, uid, args, cid, rf) -> str:
        if not args:
            snaps = self.db.get_snapshots()
            if not snaps:
                from datetime import timedelta
                for days_back in range(1, 8):
                    prev = (beijing_now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
                    snaps = self.db.get_snapshots(prev)
                    if snaps: break
            if not snaps:
                return "📋 暂无报价记录"
            by_c = {}
            for s in snaps:
                by_c.setdefault(s['country'] or '未知', []).append(s)
            return "📋 **最新报价概览**\n" + '\n'.join(f"• {c}: {len(v)}条" for c, v in by_c.items())

        first = args[0]
        biz_names = {b['name'] for b in self.config.get('business_types', [])}

        if first in biz_names:
            business = first
            country = args[1] if len(args) > 1 else None
        else:
            country = first
            business = args[1] if len(args) > 1 and args[1] in biz_names else None

        snaps = self.db.get_snapshots()
        if not snaps:
            from datetime import timedelta
            for days_back in range(1, 8):
                prev = (beijing_now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
                snaps = self.db.get_snapshots(prev)
                if snaps: break

        filtered = [s for s in snaps]
        if country:
            filtered = [s for s in filtered if s.get('country') == country]
        if business:
            filtered = [s for s in filtered if s.get('business_type') == business]

        if not filtered:
            return f"📋 未找到 {country or ''} {business or ''} 的最新报价"

        by_c = {}
        for s in filtered:
            by_c.setdefault(s['country'] or '未知', []).append(s)

        title = f"{'所有国家' if not country else country}"
        if business: title += f" - {business}"
        lines = [f"📋 **{title}** 最新报价"]
        for c, items in by_c.items():
            lines.append(f"\n> **🏳️ {c}**")
            for s in items:
                gn = s.get('group_name', '')
                link = s.get('message_link', '')
                rate, ex, fee = s.get('rate',0), s.get('exchange_rate',0), s.get('single_fee',0)
                p = f"单笔{fee}" if fee > 0 else f"{rate}/{ex}" if rate > 0 else f"{ex}"
                if link:
                    lines.append(f"  [{gn}]({link}): {p}")
                else:
                    lines.append(f"  {gn}: {p}")
        return '\n'.join(lines)

    async def _history(self, uid, args, cid, rf) -> str:
        if not args:
            return "❌ 用法: /历史报价 国家名 [业务名] [日期]\n例: /历史报价 德国 刷单 2026-05-12"

        country = args[0]
        business = None
        date = None

        if len(args) > 1:
            if re.match(r'\d{4}-\d{2}-\d{2}', args[-1]):
                date = args[-1]
                business = args[1] if len(args) > 2 else None
            else:
                business = args[1]
                if len(args) > 2 and re.match(r'\d{4}-\d{2}-\d{2}', args[-1]):
                    date = args[-1]

        q = self.db.get_quote_history(country=country, business=business, date=date, limit=30)
        if not q:
            return f"📋 未找到 {country} 的历史报价"

        lines = [f"📋 **{country}** {'最近' if not date else date} 历史报价"]
        for r in q[:20]:
            d = r.get('date','')[-5:] if r.get('date') else ''
            t = r.get('beijing_time','')[-8:]
            gn = r.get('group_name','')
            link = r.get('message_link','')
            rate, ex, fee = r.get('rate',0), r.get('exchange_rate',0), r.get('single_fee',0)
            biz = r.get('business_type','')
            qtype = r.get('quote_type','')

            if fee > 0:
                p = f"单笔{fee}"
            elif rate > 0:
                p = f"{rate}/{ex}"
            else:
                p = f"{ex}"

            if link:
                lines.append(f"• [{d} {t}] [{gn}]({link}) - {biz}: {p} {qtype}")
            else:
                lines.append(f"• [{d} {t}] {gn} - {biz}: {p} {qtype}")
        return '\n'.join(lines)

    async def _trend(self, uid, args, cid, rf) -> str:
        if len(args) < 1:
            return "❌ 用法: /趋势 国家名 [业务名]"
        country = args[0]
        business = args[1] if len(args) > 1 else None

        quotes = self.db.get_quote_history(country=country, business=business, limit=50)
        if not quotes:
            return f"📋 未找到 {country} 的报价"

        lines = [f"📈 **{country}** {('(' + business + ')') if business else ''} 趋势"]
        for r in reversed(quotes[:15]):
            d = r.get('date', '')[-5:] if r.get('date') else ''
            t = r.get('beijing_time', '')[-8:]
            ex = r.get('exchange_rate', 0)
            rate = r.get('rate', 0)
            fee = r.get('single_fee', 0)
            p = f"单笔{fee}" if fee > 0 else f"{rate}/{ex}"
            lines.append(f"• [{d} {t}] {r.get('group_name', '')}: {p}")
        return '\n'.join(lines)