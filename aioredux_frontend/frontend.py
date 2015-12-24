import asyncio
import logging
import os
import socket
import uuid

import aioamqp
import aiohttp.web
import ujson as json


logger = logging.getLogger(__name__)


@asyncio.coroutine
def index(request, index_html):
    return aiohttp.web.Response(body=index_html)


class UpdatesHandler:

    def __init__(self, amqp_host, amqp_port, amqp_namespace=None, loop=None):
        self.amqp_host, self.amqp_port = amqp_host, amqp_port
        self.transport = None
        self.protocol = None
        self.updates_exchange_name = '{}_updates'.format(amqp_namespace) if amqp_namespace else 'updates'
        self.rpc_queue_name = '{}_rpc_queue'.format(amqp_namespace) if amqp_namespace else 'rpc_queue'
        if loop is not None:
            # this is needed as there is no other way to pass a loop to aioamqp
            asyncio.set_event_loop(loop)

    def __del__(self):
        if self.transport is not None:
            asyncio.ensure_future(self.protocol.close())

    @asyncio.coroutine
    def __call__(self, request):
        resp = aiohttp.web.WebSocketResponse()
        ok, protocol = resp.can_prepare(request)
        if not ok:
            raise RuntimeError('Unable to prepare websocket response')
        yield from resp.prepare(request)
        logger.info('WebSocket connection ready, protocol: {}'.format(protocol))

        if self.protocol is None or not self.protocol.is_open:
            try:
                self.transport, self.protocol = yield from aioamqp.connect(host=self.amqp_host, port=self.amqp_port)
            except (socket.gaierror, ConnectionRefusedError):
                logger.critical('Unable to connect to AMQP server. Closing websocket.')
                yield from resp.close()
                return resp

        # wire AMQP updates queue
        updates_exchange_name = self.updates_exchange_name
        updates_queue_name = str(uuid.uuid4())
        try:
            updates_channel = yield from self.protocol.channel()
            yield from updates_channel.exchange_declare(updates_exchange_name, 'fanout')
            yield from updates_channel.queue_declare(updates_queue_name, exclusive=True)
            yield from updates_channel.queue_bind(updates_queue_name, updates_exchange_name, routing_key='')
        except aioamqp.ChannelClosed:
            logger.critical('Unable to setup updates queue or exchange with AMQP server. Closing websocket.')
            yield from self.protocol.close()
            yield from resp.close()
            return resp

        @asyncio.coroutine
        def on_updates(channel, body, envelope, properties):
            if not resp.closed:
                resp.send_str(body.decode('utf8'))
        asyncio.ensure_future(updates_channel.basic_consume(queue_name=updates_queue_name, callback=on_updates))

        # wire AMQP rpc queue
        rpc_queue_name = self.rpc_queue_name
        result_queue_name = str(uuid.uuid4())  # unique queue for websocket
        correlation_ids = set()
        try:
            rpc_channel = yield from self.protocol.channel()
            yield from rpc_channel.queue_declare(result_queue_name, exclusive=True)
        except aioamqp.ChannelClosed:
            logger.critical('Unable to setup rpc queue with AMQP server. Closing websocket.')
            yield from self.protocol.close()
            yield from resp.close()
            return resp

        @asyncio.coroutine
        def on_response(channel, body, envelope, properties):
            # correlation_id must be defined to avoid stale responses
            assert getattr(properties, 'correlation_id') is not None, (body, properties)
            if not resp.closed and properties.correlation_id in correlation_ids:
                resp.send_str(body.decode('utf8'))
                correlation_ids.remove(properties.correlation_id)
        asyncio.ensure_future(rpc_channel.basic_consume(queue_name=result_queue_name, callback=on_response))

        # websocket receive loop
        try:
            while True:
                if not self.protocol.is_open:
                    yield from resp.close()
                    break
                if not rpc_channel.is_open or not updates_channel.is_open:
                    # close the connection (and all channels)
                    yield from self.protocol.close(timeout=1)
                    yield from resp.close()
                    break
                try:
                    msg = yield from asyncio.wait_for(resp.receive(), timeout=1)
                except asyncio.TimeoutError:
                    continue
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


def make_app(static_path, amqp_host='localhost', amqp_port=5672, amqp_namespace=None, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()
    app = aiohttp.web.Application(loop=loop)

    index_html_filename = os.path.join(static_path, 'index.html')
    with open(index_html_filename, 'rb') as f:
        index_html = f.read()

    import functools
    app.router.add_route('GET', '/', functools.partial(index, index_html=index_html))
    app.router.add_route('GET', '/updates', UpdatesHandler(amqp_host, amqp_port, amqp_namespace, loop=loop))

    app.router.add_static('/', static_path)
    return app
