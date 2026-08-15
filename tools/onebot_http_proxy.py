#!/usr/bin/env python3
"""OneBot HTTP API proxy: HTTP -> NapCat WebSocket. v2 - CQ to array conversion."""
import json, asyncio, logging, re
from aiohttp import web
import websockets

NAP_CAT_WS = 'ws://127.0.0.1:3001'
HTTP_PORT = 3000
from cq_convert import cq_to_array, cq_array_convert

logging.basicConfig(level=logging.INFO, format='[onebot-proxy] %(message)s')
log = logging.getLogger('onebot-proxy')


async def handle_api(request):
    path = request.path.lstrip('/')
    body = await request.json() if request.can_read_body else {}
    action = path if path else body.get('action', '')
    params = body.get('params', {k: v for k, v in body.items() if k not in ('action', 'echo')})
    echo = body.get('echo', '')

    # Convert CQ codes to array format for send message actions
    if action in ('send_group_msg', 'send_private_msg'):
        msg = params.get('message')
        if isinstance(msg, str):
            converted = cq_to_array(msg)
            if isinstance(converted, list):
                params['message'] = converted
                log.info('CQ_CONVERTED string->array len=%d', len(converted))
        elif isinstance(msg, list):
            converted = cq_array_convert(msg)
            if converted != msg:
                params['message'] = converted
                log.info('CQ_CONVERTED array->array segments=%d', len(converted))

    try:
        async with websockets.connect(NAP_CAT_WS) as ws:
            await ws.recv()
            payload = {'action': action, 'params': params, 'echo': echo or f'p_{id(request)}'}
            await ws.send(json.dumps(payload))
            async with asyncio.timeout(10):
                while True:
                    resp = json.loads(await ws.recv())
                    if resp.get('echo') == payload['echo']:
                        return web.json_response(resp)
    except asyncio.TimeoutError:
        return web.json_response({'status': 'failed', 'retcode': -1, 'message': 'timeout'})
    except Exception as e:
        return web.json_response({'status': 'failed', 'retcode': -2, 'message': str(e)})


async def handle_get_status(request):
    try:
        async with websockets.connect(NAP_CAT_WS) as ws:
            await ws.recv()
            payload = {'action': 'get_status', 'echo': 'status'}
            await ws.send(json.dumps(payload))
            async with asyncio.timeout(5):
                while True:
                    resp = json.loads(await ws.recv())
                    if resp.get('echo') == 'status':
                        return web.json_response(resp)
    except:
        return web.json_response({'status': 'failed', 'data': {}})


async def main():
    app = web.Application()
    app.router.add_post('/{path:.*}', handle_api)
    app.router.add_get('/get_status', handle_get_status)
    app.router.add_get('/get_login_info', handle_api)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', HTTP_PORT)
    await site.start()
    log.info('OneBot HTTP API proxy on :%d -> NapCat WS', HTTP_PORT)
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
