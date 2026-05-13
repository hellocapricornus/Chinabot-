"""
Chinabot_main.py - 主程序入口
"""
import os
import sys
import logging
import asyncio
from pathlib import Path
from telethon import TelegramClient
from Chinabot_utils import load_config, save_config, beijing_format, beijing_now
from Chinabot_db import ChinabotDB
from Chinabot_commands import ChinabotCommands
from Chinabot_forwarder import ChinabotForwarder
from Chinabot_handlers import ChinabotHandlers
from Chinabot_countries import get_all_countries

def setup_logging(cfg: dict):
    lc = cfg.get('logging', {})
    Path(lc.get('file', 'Chinabot_data/Chinabot_logs/bot.log')).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, lc.get('level', 'INFO')),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[logging.FileHandler(lc['file'], encoding='utf-8'), logging.StreamHandler(sys.stdout)]
    )
    logging.getLogger('telethon').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class ChinabotApp:
    def __init__(self, config_path: str = "Chinabot_config.yaml"):
        self.config_path = config_path
        self.config = None
        self.client = None
        self.db = None
        self.commands = None
        self.forwarder = None
        self.handlers = None
        self.tasks = []

    def initialize(self):
        logger.info("=" * 50)
        logger.info(f"Chinabot 初始化 - {beijing_format(beijing_now())}")
        logger.info("=" * 50)

        self.config = load_config(self.config_path)

        # 合并内置国家（用户自定义优先）
        builtin = {c['name']: c for c in get_all_countries()}
        user = {c['name']: c for c in self.config.get('countries', [])}
        self.config['countries'] = list({**builtin, **user}.values())
        save_config(self.config, self.config_path)

        setup_logging(self.config)

        db_path = self.config.get('database', {}).get('path', 'Chinabot_data/Chinabot_data.db')
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = ChinabotDB(db_path)

        tg = self.config.get('telegram', {})
        self.client = TelegramClient(tg.get('session_name','chinabot_session'), tg['api_id'], tg['api_hash'])
        self.commands = ChinabotCommands(self.config, self.db, config_path=self.config_path)

        logger.info("所有模块初始化完成")

    async def start(self):
        logger.info("正在启动...")
        await self.client.start()

        me = await self.client.get_me()
        logger.info(f"已登录: {me.first_name} (@{me.username}) ID:{me.id}")
        if self.config.get('admin', {}).get('owner_id', 0) != me.id:
            self.config['admin']['owner_id'] = me.id
            save_config(self.config, self.config_path)
            logger.info(f"已更新 owner_id: {me.id}")

        self.forwarder = ChinabotForwarder(self.client, self.config, self.db)
        self.commands.set_client(self.client)
        self.handlers = ChinabotHandlers(self.client, self.config, self.db, self.commands, self.forwarder)
        self.handlers.register()
        await self.handlers.classify_groups()

        self.tasks.append(asyncio.create_task(self.handlers.periodic_cleanup()))
        self.tasks.append(asyncio.create_task(self.handlers.periodic_pinned()))
        await self.forwarder.update_pinned()
        self.db.backup()

        logger.info(f"启动完成! 监听 {self.db.get_stats()['channel_groups']} 个群")
        await self.client.run_until_disconnected()

    async def stop(self):
        logger.info("正在停止...")
        for t in self.tasks:
            t.cancel()
            try: await t
            except: pass
        if self.client:
            await self.client.disconnect()
        logger.info("已停止")

async def main():
    app = ChinabotApp()
    try:
        app.initialize()
        await app.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.error(f"运行错误: {e}", exc_info=True)
    finally:
        await app.stop()

if __name__ == "__main__":
    Path("Chinabot_data/Chinabot_logs").mkdir(parents=True, exist_ok=True)
    asyncio.run(main())