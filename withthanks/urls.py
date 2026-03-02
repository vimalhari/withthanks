from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

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
    return JsonResponse({"status": "ok"})


urlpatterns = [
    # Health check (used by Coolify / container orchestrators)
    path("health/", health_check, name="health_check"),

    # Admin
    path("admin/", admin.site.urls),

    # JWT auth
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Charity API + UI
    path("api/", include("charity.api.urls")),
    path("", include("charity.urls")),

    # Swagger / ReDoc (AllowAny in DEBUG; IsAdminUser in production)
    re_path(r"^swagger(?P<format>\.json|\.yaml)$", schema_view.without_ui(cache_timeout=0), name="schema-json"),
    path("swagger/", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

