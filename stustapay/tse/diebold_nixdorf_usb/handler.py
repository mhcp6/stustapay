#!/usr/bin/env python

import asyncio
import aiohttp
import base64
import contextlib
import json
import logging
import typing

from ..handler import TSEHandler, TSESignature, TSESignatureRequest
from .config import DieboldNixdorfUSBTSEConfig

LOGGER = logging.getLogger(__name__)


class RequestError(RuntimeError):
    def __init__(self, name: str, request: dict, response: dict):
        self.name = name
        try:
            self.code = int(response['Code'])
        except (KeyError, ValueError):
            self.code = None
        self.description = response.get('Description')
        super().__init__(f'{name!r}: request {request} failed: {self.description} (code {self.code})')


class DieboldNixdorfUSBTSE(TSEHandler):
    def __init__(self, name: str, config: DieboldNixdorfUSBTSEConfig):
        self.websocket_url = config.ws_url
        self.websocket_timeout = config.ws_timeout
        self.background_task: typing.Optional[asyncio.Task] = None
        self.request_id = 0
        self.pending_requests: dict[int, asyncio.Future[dict]] = {}
        self.password: str = config.password
        self.serial_number: str
        self._started = asyncio.Event()
        self._stop = False
        self._ws = None
        self._name = name

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
            try:
                session = await stack.enter_async_context(aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.websocket_timeout, connect=self.websocket_timeout)))

                try:
                    LOGGER.info(f'{self._name!r}: connecting to {self.websocket_url}')
                    self._ws = await stack.enter_async_context(session.ws_connect(self.websocket_url))
                except aiohttp.ClientError as exc:
                    LOGGER.error(f'{self._name!r}: Failed to connect to DN USB TSE: {exc}')
                    start_result.set_result(False)
                    return

                receive_task = asyncio.create_task(self.recieve_loop())
                async def await_receive_task():
                    await receive_task
                stack.push_async_callback(await_receive_task)
                stack.push_async_callback(self._ws.close)

                await self.request("SetDefaultClientID", ClientID="DummyDefaultClientId")
                start_result.set_result(True)
            except:
                start_result.set_result(False)
                raise

            while not self._stop:
                await self.request("PingPong")
                await asyncio.sleep(1)

    async def request(self, command: str, *, timeout: float = 5, **kwargs) -> dict:
        request_id = self.request_id
        self.request_id += 1

        request = dict(Command=command, PingPong=request_id)
        request.update(kwargs)

        LOGGER.info(f"{self}: >> {request}")
        await self._ws.send_str(f"\x02{json.dumps(request)}\x03\n")
        future: asyncio.Future[dict] = asyncio.Future()
        self.pending_requests[request_id] = future
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            LOGGER.info(f"{self}: << {response}")
            command_back = response.pop('Command')
            if command_back != command:
                raise RuntimeError(f'{self}: wrong command returned while processing {request}: {response}')
            status = response.pop('Status')
            if status != 'ok':
                raise RequestError(self._name, request, response)
            return response
        except asyncio.TimeoutError:
            error_message = f"{self}: timeout while waiting for response to {request}"
            LOGGER.error(error_message)
            raise asyncio.TimeoutError(error_message) from None

    async def request_with_password(self, *args, **kwargs):
        kwargs["Password"] = base64.b64encode(self.password.encode('utf-8')).decode('ascii')
        return await self.request(*args, **kwargs)

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
                if not msg.data.startswith("\x02") or not msg.data.endswith("\x03\n"):
                    LOGGER.error(f"{self}: Badly-formatted message: {msg!r}")
                    continue
                try:
                    data = json.loads(msg.data[1:-2])
                except json.decoder.JSONDecodeError:
                    LOGGER.error(f"{self}: Invalid JSON: {msg!r}")
                    continue
                if not isinstance(data, dict):
                    LOGGER.error(f"{self}: JSON data is not a dict: {data!r}")
                    continue
                message_id = data.pop("PingPong")
                if not isinstance(message_id, int):
                    LOGGER.error(f"{self}: JSON data has no int PingPong field: {msg!r}")
                    continue
                future = self.pending_requests.pop(message_id)
                if future is None:
                    LOGGER.error(f"{self}: Response does not match any pending request: {msg!r}")
                    continue
                future.set_result(data)
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                LOGGER.info(f"{self}: websocket connection has been closed: {msg!r}")
                # TODO recover?
            elif msg.type == aiohttp.WSMsgType.ERROR:
                LOGGER.error(f"{self}: websocket connection has errored: {msg!r}")
                # TODO recover?
            else:
                LOGGER.error(f"{self}: unexpected websocket message type: {msg!r}")

    async def reset(self) -> bool:
        await self.stop()
        return await self.start()

    async def register_client_id(self, client_id: str):
        await self.request_with_password("RegisterClientID", ClientID=client_id)

    async def deregister_client_id(self, client_id: str):
        await self.request_with_password("DeregisterClientID", ClientID=client_id)

    async def sign(self, request: TSESignatureRequest) -> TSESignature:
        LOGGER.info(f"{self}: signing {request}")
        await self.request_with_password(
            "StartTransaction",
            ClientID=request.till_name
        )
        await self.request_with_password(
            "FinishTransaction",
            ClientID=request.till_name,
            Data={"ReceiptNumber": request.receipt_number}
        )
        raise NotImplementedError()

    async def get_client_ids(self) -> list[str]:
        result = await self.request_with_password("GetDeviceStatus")
        try:
            result = result["ClientIDs"]
        except KeyError:
            raise RuntimeError(f"{self._name!r}: GetDeviceStatus did not return ClientIDs") from None
        if not isinstance(result, list) or any(not isinstance(x, str) for x in result):
            raise RuntimeError(f"{self}: GetDeviceStatus returned bad result: {result}")
        try:
            # hide the default dummy client id
            result.remove("DummyDefaultClientId")
        except ValueError:
            raise RuntimeError(f"TSE does not have 'DummyDefaultClientId' registered") from None
        return result

    def __str__(self):
        return f'DieboldNixdorfUSBTSEHandler({self.websocket_url!r})'
