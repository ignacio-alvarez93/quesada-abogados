"""
Motor de recurrencia para avisos de Calendar.

La regla de recurrencia está separada de calendar_alerts.

Un aviso sigue siendo un aviso normal.
La recurrencia describe cuándo deben existir futuras
ocurrencias de ese aviso.

Unidades soportadas:
    DAY
    WEEK
    MONTH
    YEAR

Finalización:
    NEVER
    DATE
    COUNT
"""

import calendar
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


FREQUENCY_DAY = "DAY"
FREQUENCY_WEEK = "WEEK"
FREQUENCY_MONTH = "MONTH"
FREQUENCY_YEAR = "YEAR"

VALID_FREQUENCIES = {
    FREQUENCY_DAY,
    FREQUENCY_WEEK,
    FREQUENCY_MONTH,
    FREQUENCY_YEAR,
}


END_NEVER = "NEVER"
END_DATE = "DATE"
END_COUNT = "COUNT"

VALID_END_TYPES = {
    END_NEVER,
    END_DATE,
    END_COUNT,
}


def _connect(
    db_path=DEFAULT_DB_PATH,
):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    return conn


@contextmanager
def _connection(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    owns_connection = conn is None

    connection = (
        conn
        if conn is not None
        else _connect(db_path)
    )

    try:
        yield connection

        if owns_connection:
            connection.commit()

    except Exception:
        if owns_connection:
            connection.rollback()

        raise

    finally:
        if owns_connection:
            connection.close()


def _text(value):
    return str(
        value or ""
    ).strip()


def _upper(value):
    return _text(value).upper()


def _normalize_datetime(
    value,
    *,
    required=False,
):
    if isinstance(
        value,
        datetime,
    ):
        return value.replace(
            microsecond=0
        )

    raw = _text(value)

    if not raw:
        if required:
            raise ValueError(
                "La fecha es obligatoria."
            )

        return None

    try:
        return datetime.fromisoformat(
            raw.replace(
                "T",
                " ",
            )
        ).replace(
            microsecond=0
        )

    except ValueError as exc:
        raise ValueError(
            "Fecha/hora de recurrencia "
            "no válida."
        ) from exc


def ensure_schema(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
                calendar_alert_recurrences (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    root_alert_id INTEGER
                        NOT NULL,

                    frequency_unit TEXT
                        NOT NULL
                        CHECK (
                            frequency_unit IN (
                                'DAY',
                                'WEEK',
                                'MONTH',
                                'YEAR'
                            )
                        ),

                    interval_value INTEGER
                        NOT NULL
                        DEFAULT 1
                        CHECK (
                            interval_value >= 1
                        ),

                    end_type TEXT
                        NOT NULL
                        DEFAULT 'NEVER'
                        CHECK (
                            end_type IN (
                                'NEVER',
                                'DATE',
                                'COUNT'
                            )
                        ),

                    end_date TEXT,

                    max_occurrences INTEGER,

                    anchor_at TEXT NOT NULL,
                    anchor_day INTEGER,

                    next_occurrence_at TEXT,
                    last_occurrence_at TEXT,

                    occurrences_generated INTEGER
                        NOT NULL
                        DEFAULT 1,

                    activo INTEGER
                        NOT NULL
                        DEFAULT 1,

                    created_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    updated_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (
                        root_alert_id
                    )
                    REFERENCES calendar_alerts(id)
                )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX
                IF NOT EXISTS
                ux_calendar_alert_recurrences_root
            ON calendar_alert_recurrences(
                root_alert_id
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX
                IF NOT EXISTS
                idx_calendar_alert_recurrences_next
            ON calendar_alert_recurrences(
                activo,
                next_occurrence_at
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
                calendar_alert_recurrence_occurrences (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    recurrence_id INTEGER
                        NOT NULL,

                    alert_id INTEGER
                        NOT NULL,

                    occurrence_index INTEGER
                        NOT NULL,

                    occurrence_at TEXT
                        NOT NULL,

                    created_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (
                        recurrence_id
                    )
                    REFERENCES
                        calendar_alert_recurrences(id),

                    FOREIGN KEY (
                        alert_id
                    )
                    REFERENCES calendar_alerts(id)
                )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX
                IF NOT EXISTS
                ux_calendar_alert_recurrence_occurrence_index
            ON calendar_alert_recurrence_occurrences(
                recurrence_id,
                occurrence_index
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX
                IF NOT EXISTS
                ux_calendar_alert_recurrence_occurrence_alert
            ON calendar_alert_recurrence_occurrences(
                alert_id
            )
            """
        )


def _month_occurrence(
    anchor,
    months,
):
    """
    Calcula siempre desde la fecha ancla.

    Ejemplo:
        31 enero
        28 febrero
        31 marzo

    No:
        31 enero
        28 febrero
        28 marzo
    """

    month_index = (
        anchor.year * 12
        + anchor.month
        - 1
        + int(months)
    )

    year = (
        month_index // 12
    )

    month = (
        month_index % 12
        + 1
    )

    last_day = (
        calendar.monthrange(
            year,
            month,
        )[1]
    )

    day = min(
        anchor.day,
        last_day,
    )

    return anchor.replace(
        year=year,
        month=month,
        day=day,
    )


def _year_occurrence(
    anchor,
    years,
):
    year = (
        anchor.year
        + int(years)
    )

    last_day = (
        calendar.monthrange(
            year,
            anchor.month,
        )[1]
    )

    day = min(
        anchor.day,
        last_day,
    )

    return anchor.replace(
        year=year,
        day=day,
    )


def occurrence_at(
    anchor_at,
    *,
    frequency_unit,
    interval_value=1,
    occurrence_index=1,
):
    """
    Devuelve la ocurrencia N.

    occurrence_index=1
        es la propia fecha ancla.

    occurrence_index=2
        es la primera repetición.
    """

    anchor = _normalize_datetime(
        anchor_at,
        required=True,
    )

    frequency = _upper(
        frequency_unit
    )

    if frequency not in VALID_FREQUENCIES:
        raise ValueError(
            "Frecuencia de recurrencia "
            "no válida."
        )

    interval = int(
        interval_value
    )

    if interval < 1:
        raise ValueError(
            "El intervalo debe ser "
            "igual o superior a 1."
        )

    index = int(
        occurrence_index
    )

    if index < 1:
        raise ValueError(
            "El índice de ocurrencia "
            "debe ser igual o superior a 1."
        )

    multiplier = (
        (index - 1)
        * interval
    )

    if frequency == FREQUENCY_DAY:
        return (
            anchor
            + timedelta(
                days=multiplier
            )
        )

    if frequency == FREQUENCY_WEEK:
        return (
            anchor
            + timedelta(
                weeks=multiplier
            )
        )

    if frequency == FREQUENCY_MONTH:
        return _month_occurrence(
            anchor,
            multiplier,
        )

    return _year_occurrence(
        anchor,
        multiplier,
    )


def preview_occurrences(
    anchor_at,
    *,
    frequency_unit,
    interval_value=1,
    end_type=END_NEVER,
    end_date=None,
    max_occurrences=None,
    limit=5,
):
    """
    Devuelve las próximas ocurrencias
    incluyendo la fecha raíz.
    """

    frequency = _upper(
        frequency_unit
    )

    clean_end_type = (
        _upper(end_type)
        or END_NEVER
    )

    if frequency not in VALID_FREQUENCIES:
        raise ValueError(
            "Frecuencia no válida."
        )

    if clean_end_type not in VALID_END_TYPES:
        raise ValueError(
            "Finalización de recurrencia "
            "no válida."
        )

    interval = int(
        interval_value
    )

    if interval < 1:
        raise ValueError(
            "El intervalo debe ser "
            "igual o superior a 1."
        )

    maximum = None

    if clean_end_type == END_COUNT:
        if max_occurrences in (
            None,
            "",
        ):
            raise ValueError(
                "Debes indicar el número "
                "máximo de repeticiones."
            )

        maximum = int(
            max_occurrences
        )

        if maximum < 1:
            raise ValueError(
                "El número de repeticiones "
                "debe ser superior a 0."
            )

    end_at = None

    if clean_end_type == END_DATE:
        end_at = _normalize_datetime(
            end_date,
            required=True,
        )

    preview_limit = max(
        1,
        int(limit),
    )

    items = []

    index = 1

    while len(items) < preview_limit:
        if (
            maximum is not None
            and index > maximum
        ):
            break

        value = occurrence_at(
            anchor_at,
            frequency_unit=frequency,
            interval_value=interval,
            occurrence_index=index,
        )

        if (
            end_at is not None
            and value > end_at
        ):
            break

        items.append(
            value
        )

        index += 1

    return items


def create_recurrence(
    *,
    root_alert_id,
    anchor_at,
    frequency_unit,
    interval_value=1,
    end_type=END_NEVER,
    end_date=None,
    max_occurrences=None,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    anchor = _normalize_datetime(
        anchor_at,
        required=True,
    )

    frequency = _upper(
        frequency_unit
    )

    clean_end_type = (
        _upper(end_type)
        or END_NEVER
    )

    if frequency not in VALID_FREQUENCIES:
        raise ValueError(
            "Frecuencia no válida."
        )

    if clean_end_type not in VALID_END_TYPES:
        raise ValueError(
            "Finalización no válida."
        )

    interval = int(
        interval_value
    )

    if interval < 1:
        raise ValueError(
            "El intervalo debe ser "
            "igual o superior a 1."
        )

    clean_end_date = None

    if clean_end_type == END_DATE:
        parsed_end = _normalize_datetime(
            end_date,
            required=True,
        )

        if parsed_end < anchor:
            raise ValueError(
                "La fecha final no puede "
                "ser anterior al primer aviso."
            )

        clean_end_date = (
            parsed_end.isoformat(
                sep=" "
            )
        )

    clean_max = None

    if clean_end_type == END_COUNT:
        if max_occurrences in (
            None,
            "",
        ):
            raise ValueError(
                "Debes indicar el número "
                "de repeticiones."
            )

        clean_max = int(
            max_occurrences
        )

        if clean_max < 1:
            raise ValueError(
                "El número de repeticiones "
                "debe ser superior a 0."
            )

    next_at = occurrence_at(
        anchor,
        frequency_unit=frequency,
        interval_value=interval,
        occurrence_index=2,
    )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        cursor = connection.execute(
            """
            INSERT INTO
                calendar_alert_recurrences (
                    root_alert_id,
                    frequency_unit,
                    interval_value,
                    end_type,
                    end_date,
                    max_occurrences,
                    anchor_at,
                    anchor_day,
                    next_occurrence_at,
                    last_occurrence_at,
                    occurrences_generated,
                    activo,
                    updated_at
                )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                1,
                1,
                CURRENT_TIMESTAMP
            )
            """,
            (
                int(root_alert_id),
                frequency,
                interval,
                clean_end_type,
                clean_end_date,
                clean_max,
                anchor.isoformat(
                    sep=" "
                ),
                anchor.day,
                next_at.isoformat(
                    sep=" "
                ),
                anchor.isoformat(
                    sep=" "
                ),
            ),
        )

        recurrence_id = int(
            cursor.lastrowid
        )

        connection.execute(
            """
            INSERT INTO
                calendar_alert_recurrence_occurrences (
                    recurrence_id,
                    alert_id,
                    occurrence_index,
                    occurrence_at
                )
            VALUES (
                ?,
                ?,
                1,
                ?
            )
            """,
            (
                recurrence_id,
                int(root_alert_id),
                anchor.isoformat(
                    sep=" "
                ),
            ),
        )

        return get_recurrence(
            recurrence_id,
            conn=connection,
            db_path=db_path,
        )


def get_recurrence(
    recurrence_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        row = connection.execute(
            """
            SELECT *
            FROM calendar_alert_recurrences
            WHERE id = ?
            """,
            (
                int(recurrence_id),
            ),
        ).fetchone()

        return (
            dict(row)
            if row
            else None
        )


def get_recurrence_for_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        row = connection.execute(
            """
            SELECT r.*
            FROM calendar_alert_recurrences r
            LEFT JOIN
                calendar_alert_recurrence_occurrences o
              ON o.recurrence_id = r.id
            WHERE
                r.root_alert_id = ?
                OR o.alert_id = ?
            LIMIT 1
            """,
            (
                int(alert_id),
                int(alert_id),
            ),
        ).fetchone()

        return (
            dict(row)
            if row
            else None
        )


def list_occurrences(
    recurrence_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        rows = connection.execute(
            """
            SELECT *
            FROM calendar_alert_recurrence_occurrences
            WHERE recurrence_id = ?
            ORDER BY occurrence_index
            """,
            (
                int(recurrence_id),
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


def register_occurrence(
    recurrence_id,
    *,
    alert_id,
    occurrence_index,
    occurrence_at,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    clean_at = _normalize_datetime(
        occurrence_at,
        required=True,
    )

    index = int(
        occurrence_index
    )

    if index < 1:
        raise ValueError(
            "Índice de ocurrencia no válido."
        )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        connection.execute(
            """
            INSERT INTO
                calendar_alert_recurrence_occurrences (
                    recurrence_id,
                    alert_id,
                    occurrence_index,
                    occurrence_at
                )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(recurrence_id),
                int(alert_id),
                index,
                clean_at.isoformat(
                    sep=" "
                ),
            ),
        )

        return connection.execute(
            """
            SELECT *
            FROM calendar_alert_recurrence_occurrences
            WHERE
                recurrence_id = ?
                AND occurrence_index = ?
            """,
            (
                int(recurrence_id),
                index,
            ),
        ).fetchone()


def update_progress(
    recurrence_id,
    *,
    occurrences_generated,
    last_occurrence_at,
    next_occurrence_at=None,
    activo=True,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    last_at = _normalize_datetime(
        last_occurrence_at,
        required=True,
    )

    next_at = _normalize_datetime(
        next_occurrence_at,
        required=False,
    )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        connection.execute(
            """
            UPDATE calendar_alert_recurrences
            SET
                occurrences_generated = ?,
                last_occurrence_at = ?,
                next_occurrence_at = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(occurrences_generated),
                last_at.isoformat(
                    sep=" "
                ),
                (
                    next_at.isoformat(
                        sep=" "
                    )
                    if next_at
                    else None
                ),
                1 if activo else 0,
                int(recurrence_id),
            ),
        )

        return get_recurrence(
            recurrence_id,
            conn=connection,
            db_path=db_path,
        )


def occurrence_allowed(
    recurrence,
    occurrence_index,
    occurrence_datetime,
):
    if not recurrence:
        return False

    if not int(
        recurrence.get("activo")
        or 0
    ):
        return False

    index = int(
        occurrence_index
    )

    value = _normalize_datetime(
        occurrence_datetime,
        required=True,
    )

    end_type = _upper(
        recurrence.get("end_type")
    )

    if end_type == END_COUNT:
        maximum = int(
            recurrence.get(
                "max_occurrences"
            )
            or 0
        )

        return (
            maximum > 0
            and index <= maximum
        )

    if end_type == END_DATE:
        end_at = _normalize_datetime(
            recurrence.get("end_date"),
            required=True,
        )

        return value <= end_at

    return True
