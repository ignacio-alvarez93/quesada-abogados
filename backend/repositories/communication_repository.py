"""
Contrato de persistencia del módulo de Comunicaciones.

Los servicios de dominio dependen de este contrato, nunca de SQLite
o Supabase directamente.
"""

from typing import Protocol

from backend.communications.models import (
    CommunicationAccount,
    CommunicationMessage,
    CommunicationMessageAttempt,
    CommunicationThread,
)


class CommunicationRepository(Protocol):
    def ensure_schema(self) -> None:
        ...

    def save_account(
        self,
        account: CommunicationAccount,
    ) -> CommunicationAccount:
        ...

    def get_account_by_code(
        self,
        code: str,
    ) -> CommunicationAccount | None:
        ...

    def get_or_create_thread(
        self,
        thread: CommunicationThread,
    ) -> CommunicationThread:
        ...

    def get_thread(
        self,
        thread_id: int,
    ) -> CommunicationThread | None:
        ...

    def list_threads(
        self,
        *,
        account_id: int | None = None,
        client_id: int | None = None,
        limit: int = 100,
    ) -> list[CommunicationThread]:
        ...

    def create_message(
        self,
        message: CommunicationMessage,
    ) -> CommunicationMessage:
        ...

    def get_message(
        self,
        message_id: int,
    ) -> CommunicationMessage | None:
        ...

    def list_messages(
        self,
        thread_id: int,
        *,
        limit: int = 200,
    ) -> list[CommunicationMessage]:
        ...

    def update_message_status(
        self,
        message_id: int,
        status: str,
        *,
        sent_by: str | None = None,
    ) -> CommunicationMessage:
        ...

    def create_attempt(
        self,
        attempt: CommunicationMessageAttempt,
    ) -> CommunicationMessageAttempt:
        ...

    def list_attempts(
        self,
        message_id: int,
    ) -> list[CommunicationMessageAttempt]:
        ...
