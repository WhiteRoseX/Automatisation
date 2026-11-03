"""Verify the non-Qt asyncio motor thread and clean shutdown."""
import asyncio
import unittest
from telepilot.local_web.server import CoreRunner

class Engine:
    enabled = False
    stopping = False
    async def run(self):
        while not self.stopping:
            await asyncio.sleep(.02)

class Gateway:
    connected = False
    async def close(self):
        return None

class DB:
    def setting(self, key, default=''):
        return default

class Service:
    def __init__(self):
        self.engine=Engine()
        self.gateway=Gateway()
        self.db=DB()
    async def command(self, name, **args):
        return name if name != 'snapshot' else self.snapshot()
    def snapshot(self):
        return {'channels': [], 'connected': False}

class RunnerTests(unittest.TestCase):
    def test_commands_and_stop_without_qt(self):
        runner=CoreRunner(Service())
        runner.start()
        self.assertEqual(runner.execute('sync_channels', {}), 'sync_channels')
        self.assertEqual(runner.snapshot()['channels'], [])
        runner.stop()
        self.assertFalse(runner.thread.is_alive())
