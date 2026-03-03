---
description: DRF API development conventions for the WithThanks REST API
applyTo: "charity/api/**/*.py"
---

# API Development Instructions

## API Architecture
- API views live in `charity/api/views.py` and `charity/api/views_reports.py`.
- Serializers in `charity/api/serializers.py`.
- URL routes in `charity/api/urls.py`, mounted at `/api/` in `withthanks/urls.py`.
- API documentation auto-generated via `drf-yasg` (Swagger at `/swagger/`, ReDoc at `/redoc/`).

## Authentication
- JWT authentication via `djangorestframework-simplejwt`.
- Token endpoint: `POST /api/token/` → returns `access` and `refresh` tokens.
- Refresh endpoint: `POST /api/token/refresh/`.
- Use `Authorization: Bearer <access_token>` header.

## Permissions
- Default: `rest_framework.permissions.IsAuthenticated`.
- Custom permissions in `charity/permissions.py`:
  - `IsCharityMember` — user must be an active member of at least one charity.
  - `IsCharityAdmin` — user must have an Admin role in at least one charity.
- Apply on views:
  ```python
  from charity.permissions import IsCharityMember

  class MyAPIView(APIView):
      permission_classes = [IsCharityMember]
  ```

## Serializer Patterns
- **Ingest serializers** (write-only): Use `serializers.Serializer` with explicit fields.
- **CRUD serializers** (read/write): Use `serializers.ModelSerializer`.
- Always validate at the serializer level, not in views.
- For bulk operations, nest serializers with `many=True`:
  ```python
  class BulkSerializer(serializers.Serializer):
      items = ItemSerializer(many=True)
  ```

## View Patterns
- Use DRF `APIView` or `@api_view` decorators.
- Return `Response` with explicit status codes:
  ```python
  from rest_framework import status
  from rest_framework.response import Response

  return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)
  ```
- For async jobs, return `202 Accepted` with a task ID for polling.
- Task status endpoint: `GET /api/tasks/<task_id>/`.

## Response Format
- Success: `{"key": "value", ...}` or `{"results": [...], "count": N}`.
- Error: Let DRF's default exception handler format `{"detail": "Error message"}`.
- Bulk ingest: `{"batch_id": 123, "task_id": "celery-task-uuid", "count": 5}`.

## Multi-Tenancy in API
- Always resolve the charity from the authenticated user's memberships.
- Never trust `charity_id` from the request body without verifying user membership.
- Validate charity access in the serializer's `validate_charity_id` method.

## Swagger Documentation
- Add `@swagger_auto_schema` decorators for non-trivial endpoints to document request/response schemas.
- Keep security definition as Bearer token (configured in `SWAGGER_SETTINGS`).
