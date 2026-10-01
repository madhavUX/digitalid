from rest_framework import serializers


class QuickCardWriteSerializer(serializers.Serializer):
    slug = serializers.SlugField(max_length=255, required=False)
    headline = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    logo_url = serializers.URLField(required=False, allow_blank=True, default="")
    cover_image_url = serializers.URLField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    whatsapp = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    website_url = serializers.URLField(required=False, allow_blank=True, default="")
    google_maps_url = serializers.URLField(required=False, allow_blank=True, default="")
    instagram_url = serializers.URLField(required=False, allow_blank=True, default="")
    facebook_url = serializers.URLField(required=False, allow_blank=True, default="")
    is_published = serializers.BooleanField(required=False, default=False)


class QuickCardUpdateSerializer(serializers.Serializer):
    headline = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    logo_url = serializers.URLField(required=False, allow_blank=True)
    cover_image_url = serializers.URLField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    whatsapp = serializers.CharField(max_length=32, required=False, allow_blank=True)
    website_url = serializers.URLField(required=False, allow_blank=True)
    google_maps_url = serializers.URLField(required=False, allow_blank=True)
    instagram_url = serializers.URLField(required=False, allow_blank=True)
    facebook_url = serializers.URLField(required=False, allow_blank=True)
    # Explicitly reject slug changes at the serializer boundary.
    slug = serializers.SlugField(max_length=255, required=False)


class QuickCardEventSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=16)
    cta = serializers.CharField(max_length=16, required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        extra = set(self.initial_data) - {"event_type", "cta"}
        if extra:
            raise serializers.ValidationError("Unexpected fields.")
        event_type = str(attrs.get("event_type") or "").strip().upper()
        raw_cta = attrs.get("cta")
        cta = "" if raw_cta in (None, "") else str(raw_cta).strip().upper()
        if event_type not in {"PAGE_VIEW", "CTA_CLICK"}:
            raise serializers.ValidationError({"event_type": "Unknown event type."})
        allowed = {"BOOK", "WHATSAPP", "CALL", "DIRECTIONS", "REVIEW", "SHARE"}
        if event_type == "PAGE_VIEW":
            if cta:
                raise serializers.ValidationError({"cta": "Page views do not take a CTA."})
            return {"event_type": event_type, "cta": ""}
        if cta not in allowed:
            raise serializers.ValidationError({"cta": "Unknown CTA."})
        return {"event_type": event_type, "cta": cta}
