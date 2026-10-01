from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from catalog.public_services import (
    get_public_service,
    list_public_categories,
    list_public_services,
    serialize_public_category,
    serialize_public_service,
)
from core.pagination import StandardLimitOffsetPagination
from locations.public_services import resolve_public_location_by_slug, serialize_public_location
from staff.public_services import list_public_staff, serialize_public_staff


class PublicCatalogThrottle(AnonRateThrottle):
    scope = "public_catalog"


@method_decorator(cache_control(public=True, max_age=60), name="dispatch")
class PublicLocationDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicCatalogThrottle]

    def get(self, request, slug):
        location = resolve_public_location_by_slug(slug)
        return Response(serialize_public_location(location))


@method_decorator(cache_control(public=True, max_age=60), name="dispatch")
class PublicLocationServicesView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicCatalogThrottle]

    def get(self, request, slug):
        location = resolve_public_location_by_slug(slug)
        queryset = list_public_services(location=location)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        payload = [serialize_public_service(service, location=location) for service in page]
        return paginator.get_paginated_response(payload)


@method_decorator(cache_control(public=True, max_age=60), name="dispatch")
class PublicLocationServiceDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicCatalogThrottle]

    def get(self, request, slug, service_identifier):
        location = resolve_public_location_by_slug(slug)
        service = get_public_service(location=location, service_identifier=service_identifier)
        return Response(serialize_public_service(service, location=location))


@method_decorator(cache_control(public=True, max_age=60), name="dispatch")
class PublicLocationCategoriesView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicCatalogThrottle]

    def get(self, request, slug):
        location = resolve_public_location_by_slug(slug)
        queryset = list_public_categories(location=location)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        payload = [serialize_public_category(category) for category in page]
        return paginator.get_paginated_response(payload)


@method_decorator(cache_control(public=True, max_age=60), name="dispatch")
class PublicLocationStaffView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicCatalogThrottle]

    def get(self, request, slug):
        location = resolve_public_location_by_slug(slug)
        queryset = list_public_staff(location=location)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        payload = [serialize_public_staff(staff, location=location) for staff in page]
        return paginator.get_paginated_response(payload)
