from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from organizations.services import create_organization_with_owner, resolve_current_membership


def issue_tokens(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


@transaction.atomic
def register_user(
    *,
    email: str,
    password: str,
    organization_name: str,
    first_name: str = "",
    last_name: str = "",
) -> dict:
    email = email.lower().strip()
    organization_name = organization_name.strip()

    if User.objects.filter(email=email).exists():
        raise ValidationError({"email": "A user with this email already exists."})
    if not organization_name:
        raise ValidationError({"organization_name": "This field may not be blank."})

    validate_password(password)

    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
    )
    organization, membership = create_organization_with_owner(
        name=organization_name,
        owner=user,
    )
    return {
        "user": user,
        "organization": organization,
        "membership": membership,
        "tokens": issue_tokens(user),
    }


def login_user(*, email: str, password: str) -> dict:
    user = authenticate(username=email.lower().strip(), password=password)
    if user is None or not user.is_active:
        raise AuthenticationFailed("Invalid email or password.")

    membership = resolve_current_membership(user)
    return {
        "user": user,
        "organization": membership.organization if membership else None,
        "membership": membership,
        "tokens": issue_tokens(user),
    }
