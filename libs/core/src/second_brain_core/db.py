from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import psycopg


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Any:
        with psycopg.connect(self.dsn) as conn:
            yield conn
