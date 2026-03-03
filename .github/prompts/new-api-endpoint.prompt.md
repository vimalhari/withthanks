---
description: "Generate a new DRF API endpoint with JWT auth and proper permissions"
---

# New API Endpoint

Create a DRF API endpoint following WithThanks conventions.

## Requirements
- Use DRF `APIView` or `@api_view` decorator.
- Apply appropriate permission class: `IsCharityMember` or `IsCharityAdmin`.
- Validate input at the serializer level.
- Return proper HTTP status codes.
- For async operations, return `202 Accepted` with a Celery task ID.
- Add Swagger documentation with `@swagger_auto_schema`.

## Serializer Template
```python
from rest_framework import serializers

class ${1:Name}Serializer(serializers.Serializer):
    """Serializer for ${2:description}."""

    # Add fields here
    field_name = serializers.CharField(max_length=255)

    def validate_field_name(self, value):
        # Add field-level validation
        return value

    def validate(self, attrs):
        # Add cross-field validation
        return attrs
```

## View Template
```python
from __future__ import annotations

import logging

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from charity.permissions import IsCharityMember

logger = logging.getLogger(__name__)


class ${3:Name}APIView(APIView):
    """${4:Description}."""

    permission_classes = [IsCharityMember]

    @swagger_auto_schema(
        request_body=${1}Serializer,
        responses={200: "Success response description"},
    )
    def post(self, request):
        serializer = ${1}Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Process validated data
        data = serializer.validated_data

        return Response({"status": "ok"}, status=status.HTTP_200_OK)
```

## After Creating
1. Add the URL pattern in `charity/api/urls.py`.
2. Test with `curl` or Swagger UI at `/swagger/`.
