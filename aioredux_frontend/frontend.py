import asyncio
import logging
import os
import uuid

import aioamqp
import aiohttp.web
import ujson as json


logger = logging.getLogger(__name__)


@asyncio.coroutine
def index(request, index_html):
    return aiohttp.web.Response(body=index_html)


class UpdatesHandler:

    def __init__(self, loop=None):
        self.transport = None
        self.protocol = None
        if loop is not None:
            # this is needed as there is no other way to pass a loop to aioamqp
            asyncio.set_event_loop(loop)

    def __del__(self):
        if self.transport is not None:
            asyncio.ensure_future(self.protocol.close())

    @asyncio.coroutine
    def __call__(self, request):
        if self.transport is None:
            self.transport, self.protocol = yield from aioamqp.connect('localhost')
        resp = aiohttp.web.WebSocketResponse()
        ok, protocol = resp.can_prepare(request)
        if not ok:
            raise RuntimeError('Unable to prepare websocket response')
        yield from resp.prepare(request)
        logger.info('WebSocket connection ready, protocol: {}'.format(protocol))

        # subscribe to amqp updates
        # XXX: can updates channel be shared by all sockets?
        updates_channel = yield from self.protocol.channel()
        updates_exchange_name = 'updates'
        updates_queue_name = str(uuid.uuid4())
        yield from updates_channel.queue_declare(updates_queue_name, exclusive=True)
        try:
            yield from updates_channel.queue_bind(updates_queue_name, updates_exchange_name, routing_key='')
        except aioamqp.exceptions.ChannelClosed as e:
            logger.critical('No exchange with name `{}` found. Unable to continue.'.format(updates_exchange_name))
            return resp

        @asyncio.coroutine
        def on_updates(body, envelope, properties):
            if not resp.closed:
                resp.send_str(body.decode('utf8'))
        asyncio.ensure_future(updates_channel.basic_consume(updates_queue_name, callback=on_updates))

        # setup amqp rpc
        # rpc queue already exists on other side
        rpc_channel = yield from self.protocol.channel()  # different channel for rpc
        rpc_queue_name = 'rpc_queue'
        result_queue_name = str(uuid.uuid4())  # unique queue for websocket
        yield from rpc_channel.queue_declare(result_queue_name, exclusive=True)

        correlation_ids = set()

        @asyncio.coroutine
        def on_response(body, envelope, properties):
            # correlation_id must be defined to avoid stale responses
            assert getattr(properties, 'correlation_id') is not None, (body, properties)
            if not resp.closed and properties.correlation_id in correlation_ids:
                resp.send_str(body.decode('utf8'))
                correlation_ids.remove(properties.correlation_id)

        asyncio.ensure_future(rpc_channel.basic_consume(result_queue_name, callback=on_response))

        # websocket receive loop
        try:
            while True:
                msg = yield from resp.receive()
                if msg.tp == aiohttp.MsgType.text:
                    action = json.loads(msg.data)
                    # rpc
                    correlation_id = str(uuid.uuid4())
                    correlation_ids.add(correlation_id)
                    properties = {'reply_to': result_queue_name, 'correlation_id': correlation_id}
                    asyncio.ensure_future(rpc_channel.basic_publish(json.dumps(action),
                                                                    '',
                                                                    routing_key=rpc_queue_name,
                                                                    properties=properties))
        except RuntimeError as e:
            if not resp.closed:
                logging.critical('Exception during websocket receive() loop: {}'.format(e))
        finally:
            logger.info('WebSocket connection closed')
            yield from rpc_channel.close()
            yield from updates_channel.close()
        return resp


def make_app(static_path, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()
    app = aiohttp.web.Application(loop=loop)

    index_html_filename = os.path.join(static_path, 'index.html')
    with open(index_html_filename, 'rb') as f:
        index_html = f.read()

    import functools
    app.router.add_route('GET', '/', functools.partial(index, index_html=index_html))
    app.router.add_route('GET', '/updates', UpdatesHandler(loop=loop))

    app.router.add_static('/', static_path)
    return app
