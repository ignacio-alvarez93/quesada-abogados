"""Instagram · fase de análisis tras la recogida (TI-4C.3E3A2).

Único llamador nominal autorizado (POST_COLLECTION_CALLERS) del servicio de
clasificación post-recogida. El controlador del Collector solo recibe un
callable after_collection(event) y nunca conoce el servicio analítico.

El evento es neutral respecto del proveedor: run_id, collection_status,
browser_released, domain_code y observation_ids del run. Construir la
composición no abre la base, no lee ajustes ni lanza navegador: la ruta de
la DB de configuración existente y el servicio se resuelven perezosamente
en la primera invocación. Devuelve solo la proyección sanitizada y
provisional del servicio (códigos y contadores), nunca scoring.
"""


class InstagramPostCollectionOrchestrator:
    def __init__(self, *, db_path_provider, service_factory):
        self._db_path_provider = db_path_provider
        self._service_factory = service_factory
        self._service = None

    def __call__(self, event):
        # Invoked sequentially by the controller's single-flight worker.
        if self._service is None:
            self._service = self._service_factory()
        result = self._service.classify_after_collection(
            db_path=self._db_path_provider(),
            domain_code=event.get("domain_code"),
            collection_ok=event.get("collection_status") == "SUCCESS",
            browser_closed=event.get("browser_released") is True,
            observation_ids=tuple(event.get("observation_ids") or ()),
        )
        return dict(result.projection(), run_id=event.get("run_id"))


def _crm_db_path():
    from backend.services.config_service import DB_PATH

    return DB_PATH


def _crm_service():
    from backend.services.trend_post_collection_service import TrendPostCollectionService

    return TrendPostCollectionService()


def create_post_collection_hook():
    """Lazy CRM wiring for create_crm_instagram_control(); opens nothing."""
    return InstagramPostCollectionOrchestrator(db_path_provider=_crm_db_path, service_factory=_crm_service)
