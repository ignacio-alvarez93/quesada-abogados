"""
Contrato mínimo para proveedores de correo.
"""

from abc import ABC
from abc import abstractmethod


class BaseEmailProvider(ABC):
    @abstractmethod
    def test_connection(self):
        raise NotImplementedError

    @abstractmethod
    def sync_incoming(self):
        raise NotImplementedError
