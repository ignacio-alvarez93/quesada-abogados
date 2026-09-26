"""Resolución canónica de identidades externas en relaciones Knowledge.

Una referencia observada en una fuente no tiene por qué coincidir con
la identidad canónica del provider que finalmente la materializa.

Ejemplo:

    DOUE-L-2024-80617
        ->
    EUR_LEX:32024L1233

Reglas:

- aliases DOUE -> CELEX únicamente cuando han sido verificados;
- nunca se intenta deducir un CELEX a partir del número DOUE;
- identidades desconocidas permanecen unsupported;
- el crosswalk conserva evidencia oficial de ambos extremos;
- resolución y reverse lookup son deterministas y sin HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass

from .source_registry import (
    knowledge_source_exists,
)


@dataclass(
    frozen=True,
    slots=True,
)
class VerifiedRelationAlias:
    """Alias externo verificado contra una identidad Knowledge."""

    alias_external_id: str

    source_key: str
    external_id: str

    alias_evidence_uri: str
    target_evidence_uri: str

    @property
    def canonical_key(
        self,
    ) -> str:
        return (
            f"{self.source_key}:"
            f"{self.external_id}"
        )


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeRelationIdentity:
    """Resultado canónico de resolver una relación externa."""

    observed_external_id: str

    source_key: str
    external_id: str

    resolution_kind: str

    @property
    def canonical_key(
        self,
    ) -> str:
        return (
            f"{self.source_key}:"
            f"{self.external_id}"
        )

    @property
    def used_alias(
        self,
    ) -> bool:
        return (
            self.observed_external_id
            != self.external_id
        )


VERIFIED_RELATION_ALIASES: tuple[
    VerifiedRelationAlias,
    ...,
] = (
    VerifiedRelationAlias(
        alias_external_id=(
            "DOUE-L-2024-80617"
        ),
        source_key="EUR_LEX",
        external_id="32024L1233",
        alias_evidence_uri=(
            "https://www.boe.es/"
            "buscar/doc.php?"
            "id=DOUE-L-2024-80617"
        ),
        target_evidence_uri=(
            "https://eur-lex.europa.eu/"
            "legal-content/ES/ALL/"
            "?uri=CELEX:32024L1233"
        ),
    ),
    VerifiedRelationAlias(
        alias_external_id=(
            "DOUE-L-2011-82719"
        ),
        source_key="EUR_LEX",
        external_id="32011L0098",
        alias_evidence_uri=(
            "https://www.boe.es/"
            "buscar/doc.php?"
            "id=DOUE-L-2011-82719"
        ),
        target_evidence_uri=(
            "https://eur-lex.europa.eu/"
            "legal-content/ES/ALL/"
            "?uri=CELEX:32011L0098"
        ),
    ),
)


_ALIAS_INDEX = {
    entry.alias_external_id: entry
    for entry
    in VERIFIED_RELATION_ALIASES
}


_DIRECT_RELATION_PREFIXES: tuple[
    tuple[str, str],
    ...,
] = (
    (
        "BOE-A-",
        "BOE_CONSOLIDATED",
    ),
)


def get_verified_relation_alias(
    alias_external_id: str,
) -> VerifiedRelationAlias | None:
    identifier = str(
        alias_external_id or ""
    ).strip()

    if not identifier:
        return None

    return _ALIAS_INDEX.get(
        identifier
    )


def resolve_relation_identity(
    external_id: str,
) -> KnowledgeRelationIdentity | None:
    """Resuelve una identidad observada hacia Knowledge.

    Fail-closed: un DOUE no registrado en VERIFIED_RELATION_ALIASES
    no se transforma ni se inventa.
    """

    observed = str(
        external_id or ""
    ).strip()

    if not observed:
        return None

    alias = (
        get_verified_relation_alias(
            observed
        )
    )

    if alias is not None:
        if not knowledge_source_exists(
            alias.source_key
        ):
            return None

        return KnowledgeRelationIdentity(
            observed_external_id=observed,
            source_key=alias.source_key,
            external_id=alias.external_id,
            resolution_kind=(
                "VERIFIED_ALIAS"
            ),
        )

    for (
        prefix,
        source_key,
    ) in _DIRECT_RELATION_PREFIXES:
        if not observed.startswith(
            prefix
        ):
            continue

        if not knowledge_source_exists(
            source_key
        ):
            return None

        return KnowledgeRelationIdentity(
            observed_external_id=observed,
            source_key=source_key,
            external_id=observed,
            resolution_kind="DIRECT",
        )

    return None


def list_relation_aliases_for_identity(
    source_key: str,
    external_id: str,
) -> tuple[str, ...]:
    """Reverse lookup canónico -> aliases externos verificados."""

    normalized_source = str(
        source_key or ""
    ).strip()

    normalized_external = str(
        external_id or ""
    ).strip()

    if (
        not normalized_source
        or not normalized_external
    ):
        return ()

    return tuple(
        sorted(
            entry.alias_external_id
            for entry
            in VERIFIED_RELATION_ALIASES
            if (
                entry.source_key
                == normalized_source
                and entry.external_id
                == normalized_external
            )
        )
    )
