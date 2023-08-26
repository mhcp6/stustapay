import asyncio

from stustapay.core.args import Parser

from .config import read_config
from .signature_processor import SignatureProcessor
from .simulator import Simulator
from .tse_switchover import TseSwitchover
from .fix_wrong_till_id_in_money_transfer import FixWrongMoneyTransfer


def main():
    """
    main entry point for launching the administration server
    """
    parser = Parser()

    parser.add_argument("-c", "--config-path", default="tse.yaml")

    ### module registration
    parser.add_subcommand("signature_processor", SignatureProcessor)
    parser.add_subcommand("simulator", Simulator)
    parser.add_subcommand("tse_switchover", TseSwitchover)
    parser.add_subcommand("fix_wrong_money_transfer", FixWrongMoneyTransfer)
    ### / module registration

    loop = asyncio.new_event_loop()

    args = parser.parse_args(loop)

    config = read_config(vars(args)["config_path"])

    args.run_subcommand(loop, config=config)


if __name__ == "__main__":
    main()
