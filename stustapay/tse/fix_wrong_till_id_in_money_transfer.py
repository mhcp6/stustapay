import asyncio
import contextlib
import curses

# import functools
import logging
from curses import wrapper
from datetime import datetime

import asyncpg

from stustapay.core.database import Connection, create_db_pool
from stustapay.core.subcommand import SubCommand

from .config import Config

LOGGER = logging.getLogger(__name__)


class FixWrongMoneyTransfer(SubCommand):
    @staticmethod
    def argparse_register(subparser):
        subparser.add_argument("-s", "--show", action="store_true", default=False, help="only show status")
        subparser.add_argument("-n", "--nc", action="store_true", default=False, help="curses interface")
        subparser.add_argument("--disable", action="store_true", default=False, help="disable a failed TSE")
        subparser.add_argument("--tse", type=str, default=None, help="TSE name to disable")

    def __init__(self, args, config: Config, **rest):
        del rest  # unused

        self.config = config
        self.show = args.show
        self.nc = args.nc
        self.tse_to_disable = args.tse
        self.disable = args.disable
        self.db_pool: asyncpg.Pool = None
        # contains event objects for each object that is waiting for new events.

    async def run(self) -> None:
        pool = await create_db_pool(self.config.database)
        self.db_pool = pool

        async with contextlib.AsyncExitStack() as aes:
            psql: Connection = await aes.enter_async_context(pool.acquire())

            # alle problematischen transaktionen suchen:
            orders_to_correct = await psql.fetch(
                "select till.name, till.description, till.id as till_id, order_items.total_price as amount, ordr.id as order_id from ordr join till on ordr.till_id = till.id join order_items on ordr.id=order_items.order_id where till.name like '%Finan%' order by name"
            )

            for wrong_ordr in orders_to_correct:
                amount = wrong_ordr["amount"]
                wrong_order_id = wrong_ordr["order_id"]
                wrong_till_id = wrong_ordr["till_id"]

                transaction = await psql.fetchrow("select * from transaction where order_id=$1", wrong_order_id)
                # jetzt hier den sourceaccount oder targetaccount nehmen und den kassierer auflösen, wir wollen nämlich an die kasse rann
                # wenn der betrag positiv ist -> target account
                # wenn der betrag negativ ist -> source account
                # booked_at auch mit speichern
                if amount == 0:
                    print(f"no money transfered in order {wrong_order_id}")
                    continue
                elif amount > 0:
                    cashier_account_id = transaction["target_account"]
                elif amount < 0:
                    cashier_account_id = transaction["source_account"]

                booking_time = transaction["booked_at"]

                # jetzt die cashier id nehmen und dann prüfen in welcher schicht dieser kassierer war, dafür braucht man die Zeit
                cashier = await psql.fetchrow("select * from cashier where cashier_account_id=$1", cashier_account_id)

                # uhaaaaaaaaaa, da steht nicht die kasse drin!!!
                # also müssen wir die start und endzeit extrahieren und dann mit diesen daten in der ordr tabelle nachschauen, welche orders auf dem Kassierer in dem Zeitraum waren -> till_id
                shift = await psql.fetchrow(
                    "select * from cashier_shift where cashier_id = $1 and ended_at>$2 and started_at<$2",
                    cashier["id"],
                    booking_time,
                )

                # so, jetzt haben wir die Schicht, jetzt holen wir uns alle orders aus der schicht
                orders_on_relevant_till = await psql.fetch(
                    "select * from ordr where cashier_id=$1 and booked_at>$2 and booked_at<$3",
                    cashier["id"],
                    shift["started_at"],
                    shift["ended_at"],
                )
                lost_till = None

                # und dann prüfen wir, ob die alle die gleiche till_id haben
                for o in orders_on_relevant_till:
                    if not lost_till:
                        lost_till = o["till_id"]
                    if lost_till != o["till_id"]:
                        print(
                            f"--- multiple till ids in this shift, something is strange, ordr {wrong_order_id}, first till {lost_till}, later till {o['till_id']}, cashier {cashier['id']}"
                        )
                        break

                print(
                    f"ordr {wrong_order_id} mit Betrag {amount} wurde auf till {wrong_till_id} gebucht, muss aber auf till {lost_till} gebucht werden"
                )

            LOGGER.info("exiting")

        await pool.close()
