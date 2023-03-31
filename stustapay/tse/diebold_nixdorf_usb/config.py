"""
configuration options for diebold usb tses
"""

from pydantic import BaseModel


class DieboldNixdorfUSBTSEConfig(BaseModel):
    diebold_nixdorf_usb_ws_url: str
    serial_number: str
    ws_timeout: float = 5

    def make(self):
        from .handler import DieboldNixdorfUSBTSE
        return DieboldNixdorfUSBTSE(self)
