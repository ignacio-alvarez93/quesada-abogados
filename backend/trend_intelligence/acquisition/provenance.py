"""
Structured provenance for acquired observations.

Provenance answers, for any TrendObservationInput produced by the
acquisition layer:
- which collector/version produced it (collector_key/collector_version)
- which provider it came from (provider)
- which physical source identity it was resolved against (source_identity)

Provenance is embedded under the reserved "acquisition" metadata key so
it never leaks provider-specific payload shapes into scoring, which only
reads signals/temporal metrics and ignores observation metadata.
"""

PROVENANCE_KEY = "acquisition"


def build_provenance(*, collector_key, collector_version, provider, source_identity):
    collector_key = str(collector_key or "").strip()
    collector_version = str(collector_version or "").strip()
    provider = str(provider or "").strip()
    source_identity = str(source_identity or "").strip()

    if not collector_key:
        raise ValueError("collector_key obligatorio")

    if not collector_version:
        raise ValueError("collector_version obligatorio")

    if not source_identity:
        raise ValueError("source_identity obligatorio")

    return {
        "collector_key": collector_key,
        "collector_version": collector_version,
        "provider": provider,
        "source_identity": source_identity,
    }


def with_provenance(metadata, provenance):
    merged = dict(metadata or {})
    merged[PROVENANCE_KEY] = dict(provenance)
    return merged
