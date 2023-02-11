"""
context injection for the http-api with FastAPI.
"""

from dataclasses import dataclass
from typing import Union, AsyncGenerator, Optional

import asyncpg
from fastapi import Request, Depends, WebSocket
from starlette.types import ASGIApp, Scope, Receive, Send

from stustapay.core.config import Config
from stustapay.core.service.products import ProductService
from stustapay.core.service.tax_rates import TaxRateService
from stustapay.core.service.transaction import TransactionService


@dataclass
class Context:
    """
    provides access to data injected by the ContextMiddleware
    into each request.
    """

    db_pool: asyncpg.Pool
    config: Config
    transaction_service: Optional[TransactionService] = None
    product_service: Optional[ProductService] = None
    tax_rate_service: Optional[TaxRateService] = None


class ContextMiddleware:
    """
    FastAPI middleware to make any variable available in a request.
    Works through ASGI magic: https://www.starlette.io/middleware/

    # Usage:
    from fastapi import FastAPI, Request, Depends
    api = FastAPI()
    api.add_middleware(ContextMiddleware,
                       db_pool=asyncpg.create_pool(...)
                       example_query="select version();"
                       example_value="rolf")

    # define dependency extractor
    def get_context(request: Request) -> Any:
        return request.state.context

    def get_db_pool(request: Request) -> asyncpg.Pool:
        return request.state.context.db_pool

    async def get_db_conn(
        db_pool: asyncpg.Pool = Depends(get_db_pool),
    ) -> asyncpg.Connection:
    async with db_pool.acquire() as conn:
        yield conn

    # in the request:
    @router.get("/dbversion")
    async def dbver(req: Request,
                    conn=Depends(get_db_conn),
                    ctx=Depends(get_context)):
        query = req.state.context.example_query
        # another way:
        # example_value == ctx.example_value
        dbver = await conn.fetchrow(query)
        return {"db_version": f"{dbver[0]}"}
    """

    def __init__(
            self,
            app: ASGIApp,
            **kwargs,
    ) -> None:
        self._app = app

        # store whatever else we need in request handling
        self.state = Context(**kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # build the request object that is available in the request handler
        # it magically gets passed through the "scope" parameter...
        # https://www.starlette.io/middleware/
        if scope["type"] == "http":
            req: Union[Request, WebSocket] = Request(scope, receive, send)
        elif scope["type"] == "websocket":
            req = WebSocket(scope, receive, send)
        else:
            return await self._app(scope, receive, send)

        # add links in the request.state to our shared members
        req.state.context = self.state

        await self._app(scope, receive, send)


def get_context(request: Request):
    return request.state.context


def get_db_pool(request: Request) -> asyncpg.Pool:
    return request.state.context.db_pool


def get_transaction_service(request: Request) -> TransactionService:
    return request.state.context.transaction_service


def get_product_service(request: Request) -> ProductService:
    return request.state.context.product_service


def get_tax_rate_service(request: Request) -> TaxRateService:
    return request.state.context.tax_rate_service


async def get_db_conn(
        db_pool: asyncpg.Pool = Depends(get_db_pool),
) -> AsyncGenerator[Union[asyncpg.Connection, asyncpg.pool.PoolConnectionProxy], None]:
    async with db_pool.acquire() as conn:
        yield conn