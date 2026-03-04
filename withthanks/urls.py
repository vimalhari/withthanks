from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from charity import views as charity_views

# Swagger/ReDoc: open to all in DEBUG, admin-only in production.
_swagger_permissions = [permissions.AllowAny] if settings.DEBUG else [permissions.IsAdminUser]

schema_view = get_schema_view(
    openapi.Info(
        title="WithThanks API",
        default_version="v1",
        description="Personalised donor thank-you video engine",
    ),
    public=settings.DEBUG,
    permission_classes=_swagger_permissions,
)


def health_check(request):
    """Deep health check — probes DB and Redis cache.
    Returns HTTP 200 on healthy, HTTP 503 on any failure.
    Used by Coolify / container orchestrators for readiness checks.
    """
    from django.core.cache import cache
    from django.db import OperationalError, connection

    errors: dict[str, str] = {}

    # Probe PostgreSQL
    try:
        connection.ensure_connection()
        db_status = "ok"
    except OperationalError as exc:
        db_status = "error"
        errors["db"] = str(exc)

    # Probe Redis (cache backend)
    try:
        cache.get("_health_probe")
        cache_status = "ok"
    except Exception as exc:
        cache_status = "error"
        errors["cache"] = str(exc)

    healthy = not errors
    payload: dict[str, object] = {
        "status": "ok" if healthy else "error",
        "db": db_status,
        "cache": cache_status,
    }
    if errors:
        payload["detail"] = errors
    return JsonResponse(payload, status=200 if healthy else 503)


urlpatterns = [
    # Health check (used by Coolify / container orchestrators)
    path("health/", health_check, name="health_check"),
    path("meta.json", health_check),  # Prevent /meta.json 404
    # Admin
    path("admin/", admin.site.urls),
    # JWT auth
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # REST API (DRF) — async video dispatch via Celery
    path("api/", include("charity.api.urls")),
    # Analytics
    path("analytics/", include("charity.urls_analytics")),
    # Charity frontend (dashboard, campaigns, clients, invoices, etc.)
    path("charity/", include("charity.urls")),
    # Root → dashboard (login_required in the view handles auth)
    path("", charity_views.dashboard_view, name="home"),
    # Static assets
    path("favicon.ico", charity_views.favicon_view),
    path("robots.txt", charity_views.robots_view),
    # Swagger / ReDoc (AllowAny in DEBUG; IsAdminUser in production)
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema_view.without_ui(cache_timeout=0),
        name="schema-json",
    ),
    path("swagger/", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
