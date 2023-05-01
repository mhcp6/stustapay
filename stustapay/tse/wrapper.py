import asyncio
import logging
from typing import Callable
import typing
import traceback

import asyncpg

from stustapay.core.schema.order import Order
from .handler import TSEHandler, TSESignatureRequest
from .kassenbeleg_v1 import Kassenbeleg_V1


LOGGER = logging.getLogger(__name__)


class TSEWrapper:
    def __init__(self, name: str, factory_function: Callable[[], TSEHandler]):
        # most of these members will be set in run().

        # The TSE name (database TSE id and TSE config entry)
        self.name = name
        # The factory function that constructs the inner TSE handler object
        self._factory_function = factory_function
        # Inner TSE handler (constructed by factory function)
        self._tse_handler: typing.Optional[TSEHandler] = None
        # The async task that contains run()
        self._task: asyncio.Task = None
        # All tills that are registered to the TSE (according to the TSE).
        self._tills = set[str]()
        # Postgresql connection object
        self._conn: asyncpg.Connection = None
        # Set to True to stop execution in a controlled manner
        self._stop = False
        # Set this event to notify that new orders are available in the DB
        self._orders_available_event = asyncio.Event()

    def start(self, db_pool: asyncpg.Pool):
        self._task = asyncio.create_task(self.run(db_pool))

    async def stop(self):
        self._stop = True
        self._orders_available_event.set()
        await self._task

    def notify_maybe_orders_available(self):
        self._orders_available_event.set()

    async def run(self, db_pool: asyncpg.Pool):
        try:
            await self._run_internal(db_pool)
        except Exception:
            LOGGER.error(
                f'TSE wrapper {self.name!r} exc!!!:\n\n{traceback.format_exc()}'
            )

    async def _run_internal(self, db_pool: asyncpg.Pool):
        """
        Connects to the wrapped TSE and calls _tse_handler_loop.
        This repeats until self._stop is set.
        """
        async with db_pool.acquire() as conn:
            conn: asyncpg.Connection
            self._conn = conn
            while True:
                # connect to the TSE
                try:
                    async with self._factory_function() as tse_handler:
                        if tse_handler is not None:
                            self._tse_handler = tse_handler
                            await self._tse_handler_loop()
                except:
                    LOGGER.error(f'{self.name!r}: {traceback.format_exc()}')
                if self._stop:
                    return
                LOGGER.error(f'{self.name!r}: waiting before reconnect')
                await asyncio.sleep(2)

    async def _tse_handler_loop(self):
        """
        Loops on self._tse_handler until the connection breaks down
        or self._stop is set.
        """
        # get the list of tills that are registered to the TSE
        self._tills = set(await self._tse_handler.get_client_ids())

        # List of tills which are registered to the TSE but not
        # listed as assigned to the TSE in the database.
        # These tills need to be unregistered from the TSE.
        extra_tills = set(self._tills)
        for row in await self._conn.fetch("select name from till where tse_id=$1", self.name):
            till = row["name"]
            extra_tills.discard(till)  # no need to unregister this till
            if till not in self._tills:
                # let's register the till with the TSE!
                await self._till_add(till)
        # Unregister all of the extra tills
        for till in sorted(extra_tills):
            await self._till_remove(till)

        # The TSE is now ready to be used.
        # Ready to execute signatures from the database.

        while not self._stop:
            LOGGER.info(f'TSE {self.name!r}: getting next request')
            next_request = await self._grab_next_request()
            LOGGER.info(f'TSE {self.name!r}: {next_request=!r}')

            if next_request is not None:
                result = await self._sign(next_request)
                LOGGER.info(f'signature result: {result!r}')
                # TODO evaluate result (aborted?)

            # TODO break out of while loop if the TSE connection has failed somehow

    async def _grab_next_request(self, timeout: float=5) -> typing.Optional[TSESignatureRequest]:
        """
        Waits until the 'order available' event is set,
        then fetches the next TSE signature request for this TSE from the database,
        marks it as 'pending' and fetches all the details, returning them as a TSESignatureRequest.

        Checks anyway after the timeout has elapsed.
        Returns None if no signature is pending.
        """
        # wait until an order is potentially available
        try:
            await asyncio.wait_for(self._orders_available_event.wait(), timeout=timeout)
            self._orders_available_event.clear()
            LOGGER.info(f'TSE wrapper {self.name}: orders available - maybe for us? checking!')
        except asyncio.TimeoutError:
            LOGGER.info(f'TSE wrapper {self.name}: timeout while waiting for orders available, but checking anyway')

        if self._stop:
            return None

        async with self._conn.transaction(isolation='serializable'):
            # the following two statements should be equivalent.
            # for testing purposes we run both statements to make sure that
            # they actually are. TODO remove the first one (next_sig_alt).
            next_sig_alt = await self._conn.fetchrow(
                """
                with currently_signing as (
                    select
                        till_id
                    from
                        tse_signature
                        join ordr on ordr.id = tse_signature.id
                    where tse_signature.signature_status = 'pending'
                ),
                todo_signatures as (
                    select
                        ordr.id, till_id, till.name as till_name
                    from
                        tse_signature
                        join ordr on ordr.id = tse_signature.id
                        join till on ordr.till_id = till.id
                    where
                        tse_signature.signature_status = 'todo'
                        and till.tse_id = $1
                )
                select
                    id as order_id, till_name
                from
                    todo_signatures
                where
                    not exists (
                        select
                            1
                        from
                            currently_signing
                        where
                            currently_signing.till_id = todo_signatures.till_id
                    )
                order by id
                limit 1
                """,
                self.name
            )
            next_sig = await self._conn.fetchrow(
                """
                with currently_signing as (
                    select
                        till_id
                    from
                        tse_signature
                        join ordr on ordr.id=tse_signature.id
                    where
                        tse_signature.signature_status = 'pending'
                )
                select
                    ordr.id as order_id,
                    till.name as till_name
                from
                    tse_signature
                    join ordr on ordr.id=tse_signature.id
                    join till on ordr.till_id=till.id
                where
                    tse_signature.signature_status='todo' and
                    till.tse_id = $1 and
                    not exists (
                        select
                            1
                        from
                            currently_signing
                        where
                            currently_signing.till_id=ordr.till_id
                    )
                order by ordr.id
                limit 1
                """,
                self.name
            )
            assert next_sig_alt == next_sig
            del next_sig_alt
            if next_sig is None:
                # no orders are available, return None
                return None
            else:
                # set the orders available event;
                # that way, next time this function is called it will run instantly
                # instead of first waiting on the event.
                self._orders_available_event.set()

            order_id = next_sig['order_id']
            till_name = next_sig['till_name']

            await self._conn.execute("update tse_signature set signature_status='pending', tse_id=$1 where id=$2", self.name, order_id)

        return await self._make_signature_request(self._conn, order_id, till_name)

    async def _make_signature_request(self, conn: asyncpg.Connection, order_id: int, till_name: str):
        """
        Collects all required information for signing the order,
        and passes the signing request to the TSE.
        """
        zahlungsart = await conn.fetchval("select order_type.zahlungsart from ordr join order_type on ordr.order_type = order_type.name where ordr.id=1")
        if zahlungsart is None:
            raise RuntimeError(f"invalid order {order_id!r}")
        beleg = Kassenbeleg_V1()
        total = 0
        for row in await conn.fetch("select quantity*price as total_price, tax_name from lineitem where order_id = $1", order_id):
            beleg.add_line_item(row['total_price'], row['tax_name'])
            total += row['total_price']
        # TODO: get currency from database config
        beleg.add_zahlung(total, zahlungsart=zahlungsart, waehrung="EUR")

        return TSESignatureRequest(
            order_id=order_id,
            till_name=till_name,
            process_type=beleg.get_process_type(),
            process_data=beleg.get_process_data(),
        )

    async def _sign(self, signing_request: TSESignatureRequest):
        # must be called when the TSE is connected and operational.
        if signing_request.till_name not in self._tills:
            await self._till_add(signing_request.till_name)
        # TODO handle failures
        # (return None if the signature was cleanly aborted,
        #  e.g. because self._tse_handler is no longer valid)
        result = await self._tse_handler.sign(signing_request)
        LOGGER.info(f'{self.name!r}: signature done ({signing_request})')
        return result

    async def _till_add(self, till):
        LOGGER.info(f'{self.name!r}: adding till {till!r}')
        await self._tse_handler.register_client_id(till)
        await self._conn.execute("insert into till_tse_history (till_name, tse_id, what) values ($1, $2, 'register')", till, self.name)
        self._tills.add(till)

    async def _till_remove(self, till):
        LOGGER.info(f'{self.name!r}: removing till {till!r}')
        await self._tse_handler.deregister_client_id(till)
        await self._conn.execute("insert into till_tse_history (till_name, tse_id, what) values ($1, $2, 'deregister')", till, self.name)
        self._tills.remove(till)
