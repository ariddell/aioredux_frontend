import asyncio
import json
import os
import tempfile

import aiohttp
import aioredux_shim

import aioredux_frontend
from aioredux_frontend.tests import base


# mock game for aioredux_shim
class MockGame:
    @asyncio.coroutine
    def receive_action(self, action):
        return {'type': 'MOCK_ACTION_TYPE'}

    def subscribe(self, on_change):
        return lambda: None


@asyncio.coroutine
def create_mock_game():
    return MockGame()


class TestWebsocket(base.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

        self.tempdir = tempfile.TemporaryDirectory()
        with open(os.path.join(self.tempdir.name, 'index.html'), 'w') as f:
            f.write('<html></html>')

        super().setUp()

    def tearDown(self):
        self.loop.close()
        self.loop = None
        self.tempdir.cleanup()
        super().tearDown()

    def test_rpc(self):
        loop = self.loop

        static_path = self.tempdir.name

        @asyncio.coroutine
        def go(loop):
            port = 8080
            host = '0.0.0.0'
            app = aioredux_frontend.make_app(static_path, loop)
            srv = yield from loop.create_server(app.make_handler(), host, port)

            # setup (mock) shim
            handler_coro = create_mock_game()
            shim = yield from aioredux_shim.create_shim(handler_coro, loop=loop)

            return (srv, shim)

        srv, shim = loop.run_until_complete(go(loop))

        @asyncio.coroutine
        def rpc_request(loop):
            session = aiohttp.ClientSession(loop=loop)
            ws = yield from session.ws_connect('http://localhost:8080/updates')
            ws.send_str(json.dumps({'type': 'TEST_MSG'}))

            response = None

            msg = yield from ws.receive()
            if msg.tp == aiohttp.MsgType.text:
                response = msg.data

            # close websocket and return response
            yield from ws.close()
            return response

        response = loop.run_until_complete(rpc_request(loop))
        self.assertIsNotNone(response)
        self.assertIsInstance(response, str)
        self.assertEqual(json.loads(response), {'type': 'MOCK_ACTION_TYPE'})

        srv.close()
        loop.run_until_complete(srv.wait_closed())
