from frontend.components.instagram_collector_panel import instagram_collector_panel
from frontend.components.trend_intelligence_analytics_panel import trend_intelligence_analytics_panel


def _card_title(control):
    controls = getattr(getattr(control, "content", None), "controls", None) or []
    return getattr(controls[0], "value", None) if controls else None


def marketing_trend_intelligence_view(page, service, trends=None):
    # Analytics is optional and read-only; it is built first so the Collector
    # refresh stays the last scheduled task, and inserted before "Resultados".
    analytics = trend_intelligence_analytics_panel(page, trends) if trends is not None else None
    view = instagram_collector_panel(page, service)
    if analytics is not None:
        controls = view.content.controls
        index = next((i for i, c in enumerate(controls) if _card_title(c) == "Resultados"), len(controls))
        controls.insert(index, analytics)
    return view
