from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from businesses.models import BusinessVertical
from organizations.models import OrganizationMember, Role
from staff.models import StaffAvailability, StaffTimeOff, Weekday


class SchedulingAPITestCase(APITestCase):
    def _register(self, email: str, organization_name: str):
        response = self.client.post(
            reverse("auth-register"),
            {
                "email": email,
                "password": "StrongPass123",
                "organization_name": organization_name,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    def _auth(self, token: str):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _create_business(self, name: str = "Ada Salon"):
        response = self.client.post(
            reverse("business-list"),
            {"name": name, "vertical": BusinessVertical.SALON},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_location(self, business_id, name: str = "Downtown", timezone_name="Asia/Kolkata"):
        response = self.client.post(
            reverse("location-list", kwargs={"business_id": business_id}),
            {"name": name, "timezone": timezone_name},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_staff(self, business_id, location_id, display_name: str = "Priya"):
        response = self.client.post(
            reverse("staff-list", kwargs={"business_id": business_id}),
            {"display_name": display_name, "location_id": location_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _login_as_role(self, owner_email: str, role: str, member_email: str):
        owner = User.objects.get(email=owner_email)
        member = User.objects.create_user(
            email=member_email,
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=member,
            role=role,
        )
        login = self.client.post(
            reverse("auth-login"),
            {"email": member_email, "password": "StrongPass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self._auth(login.data["access"])
        return member


class StaffAvailabilityAPITests(SchedulingAPITestCase):
    def test_owner_crud_and_validation(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        staff = self._create_staff(business["id"], location["id"])

        created = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "location_id": location["id"],
                "weekday": Weekday.MONDAY,
                "starts_at": "09:00:00",
                "ends_at": "17:00:00",
                "organization_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["weekday"], Weekday.MONDAY)
        availability_id = created.data["id"]

        listing = self.client.get(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            )
        )
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)

        patched = self.client.patch(
            reverse(
                "staff-availability-detail",
                kwargs={
                    "business_id": business["id"],
                    "staff_id": staff["id"],
                    "availability_id": availability_id,
                },
            ),
            {"ends_at": "18:00:00"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["ends_at"], "18:00:00")

        bad_window = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "location_id": location["id"],
                "weekday": Weekday.TUESDAY,
                "starts_at": "17:00:00",
                "ends_at": "09:00:00",
            },
            format="json",
        )
        self.assertEqual(bad_window.status_code, status.HTTP_400_BAD_REQUEST)

        deleted = self.client.delete(
            reverse(
                "staff-availability-detail",
                kwargs={
                    "business_id": business["id"],
                    "staff_id": staff["id"],
                    "availability_id": availability_id,
                },
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StaffAvailability.objects.filter(pk=availability_id).exists())

    def test_overlap_rejected_same_staff_location_weekday(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        staff = self._create_staff(business["id"], location["id"])

        first = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "location_id": location["id"],
                "weekday": Weekday.MONDAY,
                "starts_at": "09:00:00",
                "ends_at": "13:00:00",
            },
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        overlap = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "location_id": location["id"],
                "weekday": Weekday.MONDAY,
                "starts_at": "12:00:00",
                "ends_at": "17:00:00",
            },
            format="json",
        )
        self.assertEqual(overlap.status_code, status.HTTP_400_BAD_REQUEST)

        # Non-overlapping same day is allowed.
        afternoon = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "location_id": location["id"],
                "weekday": Weekday.MONDAY,
                "starts_at": "14:00:00",
                "ends_at": "17:00:00",
            },
            format="json",
        )
        self.assertEqual(afternoon.status_code, status.HTTP_201_CREATED)

    def test_staff_and_location_must_share_business(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        # Two businesses in same org
        self._auth(org_a.data["access"])
        business_a = self._create_business("Biz A")
        location_a = self._create_location(business_a["id"], "Loc A")
        staff_a = self._create_staff(business_a["id"], location_a["id"])

        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"], "Loc B")

        response = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business_a["id"], "staff_id": staff_a["id"]},
            ),
            {
                "location_id": location_b["id"],
                "weekday": Weekday.WEDNESDAY,
                "starts_at": "10:00:00",
                "ends_at": "16:00:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_availability_tenant_isolation(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"])
        staff_b = self._create_staff(business_b["id"], location_b["id"], "Ravi")
        availability = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
            ),
            {
                "location_id": location_b["id"],
                "weekday": Weekday.FRIDAY,
                "starts_at": "09:00:00",
                "ends_at": "17:00:00",
            },
            format="json",
        ).data

        self._auth(org_a.data["access"])
        self.assertEqual(
            self.client.get(
                reverse(
                    "staff-availability-list",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "staff-availability-list",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                ),
                {
                    "location_id": location_b["id"],
                    "weekday": Weekday.SATURDAY,
                    "starts_at": "09:00:00",
                    "ends_at": "12:00:00",
                },
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                reverse(
                    "staff-availability-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "staff_id": staff_b["id"],
                        "availability_id": availability["id"],
                    },
                ),
                {"ends_at": "19:00:00"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(
                reverse(
                    "staff-availability-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "staff_id": staff_b["id"],
                        "availability_id": availability["id"],
                    },
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(StaffAvailability.objects.filter(pk=availability["id"]).exists())


class StaffTimeOffAPITests(SchedulingAPITestCase):
    def test_owner_crud_multi_day_and_validation(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        staff = self._create_staff(business["id"], location["id"])

        starts = timezone.make_aware(datetime(2026, 9, 15, 0, 0), ZoneInfo("UTC"))
        ends = timezone.make_aware(datetime(2026, 9, 20, 23, 59), ZoneInfo("UTC"))
        created = self.client.post(
            reverse(
                "staff-time-off-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "starts_at": starts.isoformat().replace("+00:00", "Z"),
                "ends_at": ends.isoformat().replace("+00:00", "Z"),
                "reason": "Annual leave",
                "tenant_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["reason"], "Annual leave")
        time_off_id = created.data["id"]

        # Same-day partial leave
        day_start = timezone.make_aware(datetime(2026, 9, 12, 14, 0), ZoneInfo("UTC"))
        day_end = timezone.make_aware(datetime(2026, 9, 12, 16, 0), ZoneInfo("UTC"))
        partial = self.client.post(
            reverse(
                "staff-time-off-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "starts_at": day_start.isoformat().replace("+00:00", "Z"),
                "ends_at": day_end.isoformat().replace("+00:00", "Z"),
                "reason": "Personal appointment",
            },
            format="json",
        )
        self.assertEqual(partial.status_code, status.HTTP_201_CREATED)

        listing = self.client.get(
            reverse(
                "staff-time-off-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            )
        )
        self.assertEqual(listing.data["count"], 2)

        bad = self.client.post(
            reverse(
                "staff-time-off-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "starts_at": ends.isoformat().replace("+00:00", "Z"),
                "ends_at": starts.isoformat().replace("+00:00", "Z"),
            },
            format="json",
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        patched = self.client.patch(
            reverse(
                "staff-time-off-detail",
                kwargs={
                    "business_id": business["id"],
                    "staff_id": staff["id"],
                    "time_off_id": time_off_id,
                },
            ),
            {"reason": "Family trip"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["reason"], "Family trip")

        deleted = self.client.delete(
            reverse(
                "staff-time-off-detail",
                kwargs={
                    "business_id": business["id"],
                    "staff_id": staff["id"],
                    "time_off_id": time_off_id,
                },
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StaffTimeOff.objects.filter(pk=time_off_id).exists())

    def test_time_off_tenant_isolation(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"])
        staff_b = self._create_staff(business_b["id"], location_b["id"], "Ravi")
        starts = timezone.now()
        ends = starts + timedelta(days=2)
        time_off = self.client.post(
            reverse(
                "staff-time-off-list",
                kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
            ),
            {
                "starts_at": starts.isoformat().replace("+00:00", "Z"),
                "ends_at": ends.isoformat().replace("+00:00", "Z"),
                "reason": "Leave",
            },
            format="json",
        ).data

        self._auth(org_a.data["access"])
        self.assertEqual(
            self.client.get(
                reverse(
                    "staff-time-off-list",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "staff-time-off-list",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                ),
                {
                    "starts_at": starts.isoformat().replace("+00:00", "Z"),
                    "ends_at": ends.isoformat().replace("+00:00", "Z"),
                },
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(
                reverse(
                    "staff-time-off-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "staff_id": staff_b["id"],
                        "time_off_id": time_off["id"],
                    },
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(StaffTimeOff.objects.filter(pk=time_off["id"]).exists())


class SchedulingPermissionTests(SchedulingAPITestCase):
    def test_manager_can_write_staff_cannot(self):
        self._register("owner@example.com", "Org A")
        owner_login = self.client.post(
            reverse("auth-login"),
            {"email": "owner@example.com", "password": "StrongPass123"},
            format="json",
        )
        self._auth(owner_login.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        staff = self._create_staff(business["id"], location["id"])

        self._login_as_role("owner@example.com", Role.MANAGER, "manager@example.com")
        created = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "location_id": location["id"],
                "weekday": Weekday.THURSDAY,
                "starts_at": "10:00:00",
                "ends_at": "16:00:00",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        starts = timezone.now() + timedelta(days=1)
        ends = starts + timedelta(hours=2)
        time_off = self.client.post(
            reverse(
                "staff-time-off-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "starts_at": starts.isoformat().replace("+00:00", "Z"),
                "ends_at": ends.isoformat().replace("+00:00", "Z"),
            },
            format="json",
        )
        self.assertEqual(time_off.status_code, status.HTTP_201_CREATED)

        self._login_as_role("owner@example.com", Role.STAFF, "staffuser@example.com")
        self.assertEqual(
            self.client.get(
                reverse(
                    "staff-availability-list",
                    kwargs={"business_id": business["id"], "staff_id": staff["id"]},
                )
            ).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "staff-availability-list",
                    kwargs={"business_id": business["id"], "staff_id": staff["id"]},
                ),
                {
                    "location_id": location["id"],
                    "weekday": Weekday.FRIDAY,
                    "starts_at": "09:00:00",
                    "ends_at": "12:00:00",
                },
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "staff-time-off-list",
                    kwargs={"business_id": business["id"], "staff_id": staff["id"]},
                ),
                {
                    "starts_at": starts.isoformat().replace("+00:00", "Z"),
                    "ends_at": ends.isoformat().replace("+00:00", "Z"),
                },
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
