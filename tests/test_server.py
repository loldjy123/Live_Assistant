import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

import main
from claim import BookIdentification
from pipeline import serving_schema


class FakeSession:
    async def send_client_content(self, **kwargs): pass
    async def send_realtime_input(self, **kwargs): pass
    async def send_tool_response(self, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def receive(self):
        await asyncio.Event().wait()
        yield None


def fake_client():
    return SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=lambda **kwargs:FakeSession())))


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        for name in ['index.html','app.js','processor.js','site-config.js']:
            (self.root/name).write_text('Public asset')
        (self.root/'.env').write_text('PRIVATE_KEY=never-public')
        (self.root/'claims'/'sweep').mkdir(parents=True)
        (self.root/'claims'/'sweep'/'claim_packet.json').write_text('{}')
        self.root_patch = patch.object(main,'ROOT',self.root)
        self.env_patch = patch.dict('os.environ',{},clear=False)
        self.root_patch.start()
        self.env_patch.start()
        # A developer's external storage setting must not affect these fixtures.
        import os
        os.environ.pop('CLAIMS_DIR',None)
        self.client = TestClient(TestServer(main.create_app(fake_client())))
        await self.client.start_server()
        self.origin = str(self.client.make_url('/')).rstrip('/')

    async def asyncTearDown(self):
        await self.client.close()
        self.env_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    async def test_public_assets_and_secret_isolation(self):
        for path in ['/','/app.js','/site-config.js','/claims/sweep/claim_packet.json']:
            response = await self.client.get(path)
            self.assertEqual(response.status,200,path)
            await response.read()
        for path in ['/.env','/main.py','/claims/sweep/../../.env','/claims/']:
            response = await self.client.get(path)
            self.assertEqual(response.status,404,path)
            await response.read()

    async def test_origin_and_health(self):
        response = await self.client.get('/health',headers={'Origin':'https://loldjy123.github.io'})
        self.assertEqual(response.headers['Access-Control-Allow-Origin'],'https://loldjy123.github.io')
        health = await response.json()
        self.assertTrue(health['ready'])
        self.assertEqual(health['websocket_path'], '/ws')
        response = await self.client.get('/health',headers={'Origin':'https://unrelated.example'})
        self.assertNotIn('Access-Control-Allow-Origin',response.headers)
        await response.read()
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect('/ws',origin='https://unrelated.example')

    async def test_local_preview_allowed_only_on_local_backend(self):
        origin = 'http://localhost:63342'
        response = await self.client.get('/health', headers={'Origin': origin})
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
        await response.read()
        async with self.client.ws_connect('/ws', origin=origin):
            pass
        response = await self.client.get('/health', headers={
            'Origin': origin, 'Host': 'assistant.example.com',
        })
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        await response.read()

    async def test_finish_on_shared_http_websocket_port(self):
        async def fake_generate(self, stage, contents, config):
            return SimpleNamespace(text='Unresolved books require review.')
        with patch.object(main.Pipeline,'generate',fake_generate):
            async with self.client.ws_connect('/ws',origin=self.origin) as socket:
                await socket.send_json({'locale':{'country':'United States','currency':'USD'}})
                async with asyncio.timeout(5):
                    while True:
                        data = await socket.receive_json()
                        if data.get('ready'): break
                    await socket.send_json({'command':'finish'})
                    while True:
                        data = await socket.receive_json()
                        if data.get('report_ready'): break
                # Download from the SAME server, with no second port.
                response = await self.client.get(data['report_ready']['json'])
                self.assertEqual(response.status,200)
                packet = await response.json()
                self.assertEqual(set(packet),{'sweep','books','totals'})
                response = await self.client.get(data['report_ready']['html'])
                self.assertIn('Book inventory report',await response.text())

    async def test_configured_storage_directory(self):
        import os
        with tempfile.TemporaryDirectory() as storage:
            path = Path(storage)/'saved'
            path.mkdir()
            (path/'report.html').write_text('Stored report')
            os.environ['CLAIMS_DIR']=storage
            response = await self.client.get('/claims/saved/report.html')
            self.assertEqual(await response.text(),'Stored report')

    def test_serving_schema_preserves_title_field_without_state_limits(self):
        schema = serving_schema(BookIdentification)
        self.assertIn('title',schema['$defs']['BookObservation']['properties'])
        self.assertNotIn('maxItems',json.dumps(schema))


if __name__=='__main__':unittest.main()
