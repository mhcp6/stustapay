from typing import Iterable, Callable, Tuple
import functools
import logging

import yaml
from pydantic import BaseModel

from .diebold_nixdorf_usb.config import DieboldNixdorfUSBTSEConfig
from .handler import TSEHandler
from ..core.config import DatabaseConfig


class TSEList(BaseModel):
    diebold_nixdorf_usb: dict[str, DieboldNixdorfUSBTSEConfig]

    def all_factories(self) -> Iterable[Tuple[str, Callable[[], TSEHandler]]]:
        """
        Returns tuples of (name, function that constructs that TSEHandler)
        """
        names_seen = set()
        for tse_type_list in [self.diebold_nixdorf_usb]:
            for name, config in tse_type_list.items():
                if name in names_seen:
                    raise ValueError(f"duplicate TSE name {name!r}")
                names_seen.add(name)
                yield name, config.factory


class Config(BaseModel):
    database: DatabaseConfig
    tses: TSEList


def read_config(config_path: str) -> Config:
    with open(config_path, "r") as config_file:
        content = yaml.safe_load(config_file)
        config = Config(**content)
        return config
