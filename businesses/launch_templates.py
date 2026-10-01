"""Application-level website template registry (no DB tables)."""

from __future__ import annotations

from businesses.models import WebsiteTemplateKey

WEBSITE_TEMPLATES: dict[str, dict[str, str]] = {
    WebsiteTemplateKey.SALON_MODERN: {
        "key": WebsiteTemplateKey.SALON_MODERN,
        "label": "Modern",
        "industry": "salon",
        "description": "Clean, contemporary salon layout.",
        "preview_blurb": "Large hero, strong CTA, generous whitespace.",
    },
    WebsiteTemplateKey.SALON_CLASSIC: {
        "key": WebsiteTemplateKey.SALON_CLASSIC,
        "label": "Classic",
        "industry": "salon",
        "description": "Timeless salon presentation.",
        "preview_blurb": "Structured layout, service list, local-business feel.",
    },
    WebsiteTemplateKey.SALON_LUXURY: {
        "key": WebsiteTemplateKey.SALON_LUXURY,
        "label": "Luxury",
        "industry": "salon",
        "description": "Elevated, premium salon look.",
        "preview_blurb": "Image-forward hero, elegant typography, premium CTA.",
    },
}


def list_website_templates() -> list[dict[str, str]]:
    return list(WEBSITE_TEMPLATES.values())


def is_valid_template_key(key: str | None) -> bool:
    return bool(key) and key in WEBSITE_TEMPLATES
