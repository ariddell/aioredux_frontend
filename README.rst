=================
aioredux-frontend
=================

aioredux frontend

Tiny package to accompany aioredux. Allows you to run a webserver which
forwards actions to something that's using a aioredux Store via AMQP. Allows
client to subscribe to updates from said store.  Essentially a mechanism for
avoiding ``node`` on the server.

The idea here is that the aioredux Store is the "backend". There's
another package ``aioredux-backend`` which provides a shim for
communicating with an aioredux store.

*Requires rabbitmq to be running on localhost on the standard port.*

* Free software: Mozilla Public License

Usage
-----
::

    import aioredux_frontend
    port = 8080
    host = '0.0.0.0'
    app = aioredux_frontend.make_app(static_path, loop)
    srv = yield from loop.create_server(app.make_handler(), host, port)
    logger.info('HTTP server listening on http://{}:{}'.format(host, port))
    return srv

If using gunicorn, you can point gunicorn at a variable ``app`` where ``app =
aioredux_frontend.make_app(static_path)``::

    gunicorn main:app --worker-class aiohttp.worker.GunicornWebWorker --workers 8

Features
--------

* TODO
