"""
Persistencia de la configuración del colector de Instagram.

Escribe únicamente en la tabla config_global ya existente. Nunca crea la base,
la tabla ni ejecuta migraciones; toda dependencia SQLite queda encapsulada aquí.
"""

import json
import sqlite3
from typing import Protocol

from database.connection import get_existing_connection


class InstagramCollectorSettingsWriter(Protocol):
    """Contrato portable inyectado en la capa de aplicación."""

    def save(self, key: str, value: str) -> None:
        ...


class SettingsStoreUnavailable(ValueError):
    """La base o la tabla de configuración no existen; no se crean."""


class SQLiteInstagramCollectorSettingsRepository:
    """Upsert atómico en config_global existente (fail-closed)."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    def save(self, key, value):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Clave de configuración inválida")
        if not isinstance(value, str):
            raise ValueError("Valor de configuración inválido")
        try:
            parsed = json.loads(value)
        except ValueError:
            raise ValueError("Valor de configuración inválido") from None
        if not isinstance(parsed, dict):
            raise ValueError("Valor de configuración inválido")
        try:
            connection = get_existing_connection(self.db_path)
        except sqlite3.OperationalError:
            raise SettingsStoreUnavailable("Base de configuración no disponible") from None
        try:
            connection.execute(
                "INSERT INTO config_global (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (key, value),
            )
            connection.commit()
        except BaseException as error:
            connection.rollback()
            if isinstance(error, sqlite3.OperationalError) and str(error).startswith("no such table"):
                raise SettingsStoreUnavailable("Tabla de configuración no disponible") from None
            raise
        finally:
            connection.close()
