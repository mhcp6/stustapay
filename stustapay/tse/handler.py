"""
Defines the interface for the handlers for the various TSEs
"""
import abc
import dataclasses


@dataclasses.dataclass
class TSESignatureRequest:
    order_id: int
    till_name: str
    process_type: str
    process_data: str
    receipt_number: int


@dataclasses.dataclass
class TSESignature:
    tse_transaction: str
    tse_signaturenr: str
    tse_start: str
    tse_end: str
    tse_serial: str
    tse_hashalgo: str
    tse_signature: str


class TSEHandler(abc.ABC):
    """
    Abstract base class for various TSE handlers (e.g. DieboldNixdorfUSB)
    """

    @abc.abstractmethod
    async def start(self) -> bool:
        """
        Starts communication with the TSE.

        This method shall only return when requests such as register_client_id()
        can be sent to the TSE.

        This method shall return True if the TSE was started successfully.
        On failure, awaiting stop() will yield the exception.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def stop(self):
        """
        Stops communication with the TSE
        """
        raise NotImplementedError()

    async def __aenter__(self):
        start_result = await self.start()
        if start_result:
            return self
        else:
            return None

    async def __aexit__(self, *_):
        await self.stop()

    @abc.abstractmethod
    async def reset(self):
        """
        Resets the connection to the TSE or the TSE itself to attempt and fix any errors
        that prevent it from being usable.

        This will be called by the TSEMuxer if the TSE times out on signature requests
        or if it produces some other errors.

        Like with start(), this method shall only return when requests can be sent again,
        it will return True iff the TSE was reset successfully and awaiting stop() will
        yield the exception that occured during resetting when False was returned.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def register_client_id(self, client_id: str):
        """
        Registers a client ID with this TSE module.
        This enables the TSE to sign order for this client ID in the future.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def deregister_client_id(self, client_id: str):
        """
        Deregisters a client ID from this TSE module.
        This means that the TSE will no longer be able to sign orders
        from this Client ID in the future.
        """

    @abc.abstractmethod
    async def sign(self, request: TSESignatureRequest) -> TSESignature:
        """
        Signs the given request using the TSE,
        returning the signature object.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def get_client_ids(self) -> list[str]:
        """
        Returns all registered client ids.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def __str__(self):
        raise NotImplementedError()
