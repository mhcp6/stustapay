#!/usr/bin/env python

import asyncio
import aiohttp
import contextlib
import json
import logging
import typing

from ..handler import Order, OrderSignature, TSEHandler
from .config import DieboldNixdorfUSBTSEConfig

LOGGER = logging.getLogger(__name__)


class DieboldNixdorfUSBTSE(TSEHandler):
    def __init__(self, config: DieboldNixdorfUSBTSEConfig):
        self.websocket_url = config.diebold_nixdorf_usb_ws_url
        self.websocket_timeout = config.ws_timeout
        self.background_task: typing.Optional[asyncio.Task] = None
        self.request_id = 0
        self.pending_requests: dict[int, asyncio.Future[dict]] = {}
        self._started = asyncio.Event()
        self._stop = False
        self._ws = None

    async def start(self) -> bool:
        self._stop = False
        start_result: asyncio.Future[bool] = asyncio.Future()
        self.background_task = asyncio.create_task(self.run(start_result))
        return await start_result

    async def stop(self):
        # TODO cleanly cancel the background task
        self._stop = True
        await self.background_task
        self._started.clear()

    async def run(self, start_result: asyncio.Future[bool]):
        async with contextlib.AsyncExitStack() as stack:
            def set_ws(ws):
                print(f'setting self._ws={ws}')
                self._ws = ws
            try:
                session = await stack.enter_async_context(aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.websocket_timeout, connect=self.websocket_timeout)))
                LOGGER.info(f'connecting to DN TSE at {self.websocket_url!r}')
                set_ws(await stack.enter_async_context(session.ws_connect(self.websocket_url)))
            finally:
                start_result.set_result(self._ws is not None)
            stack.callback(set_ws, None)

            receive_task = asyncio.create_task(self.recieve_loop())
            await self.request("SetDefaultClientId", ClientID="DummyDefaultClientId")
            while not self._stop:
                print('sending pingpong')
                result = await self.request("PingPong")
                print(f'result: {result!r}')
                await asyncio.sleep(1)
            await self._ws.close()
            await receive_task

    async def request(self, command: str, *, timeout: float = 5, **kwargs) -> dict:
        request_id = self.request_id
        self.request_id += 1

        request = dict(Command=command, PingPong=request_id)
        request.update(kwargs)

        LOGGER.info(f"{self}: sending request {request}")
        await self._ws.send_str(f"\x02{json.dumps(kwargs)}\x03")
        future: asyncio.Future[dict] = asyncio.Future()
        self.pending_requests[request_id] = future
        try:
            # This code is incorrect, as it does not return the result of the future but rather two sets of awaitables
            # done, pending = await asyncio.wait()
            # response = await asyncio.wait(future, timeout=timeout)
            response = await future
            LOGGER.info(f"{self}: got response {response}")
            return response
        except asyncio.TimeoutError:
            error_message = f"{self}: timeout while waiting for response to {request}"
            LOGGER.error(error_message)
            raise asyncio.TimeoutError(error_message)

    async def recieve_loop(self):
        """
        Receives and processes websocket messages.
        Messages that we receive from the websocket are expected to be responses to requests
        that we sent through the request() method.
        """
        async for msg in self._ws:
            msg: aiohttp.WSMessage
            if msg.type == aiohttp.WSMsgType.TEXT:
                msg.data: str
                if not msg.data or msg.data[0] != "\x02" or msg.data[-1] != "\x03":
                    LOGGER.error(f"{self}: Badly-formatted message: {msg}")
                    continue
                try:
                    data = json.loads(msg.data[1:-1])
                except json.decoder.JSONDecodeError:
                    LOGGER.error(f"{self}: Invalid JSON: {msg}")
                    continue
                if not isinstance(data, dict):
                    LOGGER.error(f"{self}: JSON data is not a dict: {msg}")
                    continue
                message_id = data.pop("PingPong")
                if not isinstance(message_id, int):
                    LOGGER.error(f"{self}: JSON data has no int PingPong field: {msg}")
                    continue
                future = self.pending_requests.pop(message_id)
                if future is None:
                    LOGGER.error(f"{self}: Response does not match any pending request: {msg}")
                    continue
                future.set_result(data)
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                LOGGER.info(f"{self}: websocket connection has been closed: {msg}")
                # TODO recover?
            elif msg.type == aiohttp.WSMsgType.ERROR:
                LOGGER.error(f"{self}: websocket connection has errored: {msg}")
                # TODO recover?
            else:
                LOGGER.error(f"{self}: unexpected websocket message type: {msg}")

    async def reset(self) -> bool:
        await self.stop()
        return await self.start()

    async def register_client_id(self, client_id: str):
        result = await self.request("RegisterClientID", ClientID=client_id)
        if result["Status"] != "ok":
            raise RuntimeError(f"{self}: Could not register client ID: {result}")

    async def deregister_client_id(self, client_id: str):
        result = await self.request("DeRegisterClientID", ClientID=client_id)
        if result["Status"] != "ok":
            raise RuntimeError(f"{self}: Could not deregister client ID: {result}")

    async def sign_order(self, order: Order) -> OrderSignature:
        raise NotImplementedError()

    async def get_client_ids(self) -> list[str]:
        result = await self.request("GetDeviceStatus")
        if result["Status"] != "ok":
            raise RuntimeError(f"{self}: Could not query device status: {result}")
        result = result["ClientIDs"]
        if not isinstance(result, list) or any(not isinstance(x, str) for x in result):
            raise RuntimeError(f"{self}: invalid device status: {result}")
        return result

    def __str__(self):
        return f'DieboldNixdorfUSBTSEHandler({self.websocket_url})'
