'''Rudimentary tests'''

import asyncio
import os
import tempfile

import aiohttp

import aioredux_frontend
from aioredux_frontend.tests import base


class TestBasic(base.TestCase):

    host = 'localhost'
    port = 8080  # tests are run in parallel; avoid overlapping ports

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

    def test_make_app(self):
        loop = self.loop
        port = self.port
        host = self.host

        static_path = self.tempdir.name

        @asyncio.coroutine
        def go(loop):
            app = aioredux_frontend.make_app(static_path, loop=loop)
            srv = yield from loop.create_server(app.make_handler(), host, port)
            return srv

        srv = loop.run_until_complete(go(loop))
        self.assertIsInstance(srv, asyncio.base_events.Server)

        srv.close()
        loop.run_until_complete(srv.wait_closed())

    def test_index(self):
        loop = self.loop
        port = self.port
        host = self.host

        static_path = self.tempdir.name

        @asyncio.coroutine
        def go(loop):
            app = aioredux_frontend.make_app(static_path, loop=loop)
            srv = yield from loop.create_server(app.make_handler(), host, port)
            return srv

        srv = loop.run_until_complete(go(loop))
        self.assertIsInstance(srv, asyncio.base_events.Server)
        request = loop.run_until_complete(aiohttp.get('http://{}:{}'.format(host, port), loop=loop))
        text = loop.run_until_complete(request.text())
        self.assertEqual(text, '<html></html>')

        srv.close()
        loop.run_until_complete(srv.wait_closed())
