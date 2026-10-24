from __future__ import annotations

import hashlib
import logging

from psycopg import sql

from . import config, db
from .llm import LLM, FakeLLM


class CachedLLM(LLM):
    """LLM wrapper that caches completions in the `llm_cache` table."""

    def __init__(self, inner: LLM) -> None:
        self.inner = inner
        self.enabled = True
        self.model_name = getattr(inner, "last_provider", type(inner).__name__)

        try:
            # Validate that we can obtain a connection; any error disables cache.
            with db.company_conn() as _:
                pass
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("LLM cache disabled: %s", exc)
            self.enabled = False

    def _hash_prompt(self, system: str, user: str) -> str:
        data = f"{system}\x00{user}".encode()
        return hashlib.sha256(data).hexdigest()

    def complete(self, system: str, user: str) -> str:
        if not self.enabled or isinstance(self.inner, FakeLLM):
            return self.inner.complete(system, user)

        prompt_hash = self._hash_prompt(system, user)
        tenant_id = config.get_settings().company_id

        try:
            with db.company_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    sql.SQL(
                        "SELECT response FROM llm_cache WHERE tenant_id=%s AND prompt_hash=%s"
                    ),
                    (tenant_id, prompt_hash),
                )
                row = cur.fetchone()
                if row:
                    return row[0]

                # No cached value – call inner LLM.
                response = self.inner.complete(system, user)
                if response:
                    cur.execute(
                        sql.SQL(
                            "INSERT INTO llm_cache (tenant_id, prompt_hash, model, response) "
                            "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, prompt_hash) DO NOTHING"
                        ),
                        (tenant_id, prompt_hash, getattr(self.inner, "last_provider", type(self.inner).__name__), response),
                    )
                return response
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("LLM cache error, falling back: %s", exc)
            return self.inner.complete(system, user)
