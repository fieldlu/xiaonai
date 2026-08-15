#!/usr/bin/env python3
"""Ultra-stable WS bridge: heartbeat + instant reconnect."""
import asyncio, logging, json, sys
import websockets

NAP_CAT_WS = 'ws://127.0.0.1:3001'
PLUGIN_WS = 'ws://127.0.0.1:18799/onebot'

logging.basicConfig(level=logging.INFO, format='[ws-bridge] %(message)s')
log = logging.getLogger('ws-bridge')

async def forward(src, dst, name):
    try:
        async for msg in src:
            await dst.send(msg)
    except Exception as e:
        log.warning(f'{name} forward lost: {e}')

async def keepalive(ws, name):
    """Send periodic pings to keep WS alive."""
    while True:
        await asyncio.sleep(15)
        try:
            await ws.ping()
        except Exception as e:
            log.warning(f'{name} ping failed: {e}')
            break

async def bridge():
    while True:
        try:
            async with websockets.connect(NAP_CAT_WS) as napcat:
                log.info('Connected to NapCat WS')
                try:
                    async with websockets.connect(PLUGIN_WS) as plugin:
                        log.info('Connected to Plugin WS')
                        # Create forwarding tasks AND keepalive
                        f1 = asyncio.create_task(forward(napcat, plugin, 'NapCat->Plugin'))
                        f2 = asyncio.create_task(forward(plugin, napcat, 'Plugin->NapCat'))
                        k1 = asyncio.create_task(keepalive(napcat, 'NapCat'))
                        k2 = asyncio.create_task(keepalive(plugin, 'Plugin'))
                        # Wait for ANY to fail, then reconnect all
                        done, _ = await asyncio.wait([f1, f2, k1, k2], return_when=asyncio.FIRST_COMPLETED)
                        for t in done:
                            try:
                                await t
                            except:
                                pass
                except Exception as e:
                    log.warning(f'Plugin WS: {e}')
        except Exception as e:
            log.warning(f'NapCat WS: {e}')
        log.info('Reconnecting...')
        await asyncio.sleep(0)  # Instant reconnect

if __name__ == '__main__':
    log.info('Starting ultra-stable bridge')
    asyncio.run(bridge())
