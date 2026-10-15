"""drf-spectacular's settings: how the OpenAPI schema the frontend client is
generated from names and shapes its components."""

SPECTACULAR_SETTINGS = {
    "TITLE": "Jasmin Platform API",
    "DESCRIPTION": "CSA Management Platform API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # THE KEY SETTING - Don't split request/response into separate schemas
    "COMPONENT_SPLIT_REQUEST": False,
    "COMPONENT_SPLIT_PATCH": True,  # all-optional ``Patched…`` PATCH bodies
    # Map your enum classes to prevent duplicates
    "ENUM_NAME_OVERRIDES": {
        "MovementTypeEnum": "apps.commissioning.models.choices.MovementTypeOptions",
        "CultivationOriginEnum": "apps.commissioning.models.choices.CultivationOriginOptions",
        "DeliveryCycleEnum": "apps.commissioning.models.choices.DeliveryCycleOptions",
        "ShareTypeVariationSizeEnum": "apps.commissioning.models.choices.ShareTypeVariationSizeOptions",
        "UnitEnum": "apps.commissioning.models.choices.UnitOptions",
        "PaymentCycleEnum": "apps.commissioning.models.choices.PaymentCycleOptions",
        "VegetableSizeEnum": "apps.commissioning.models.choices.VegetableSizeOptions",
        "ShareTypeEnum": "apps.commissioning.models.choices.ShareOptions",
        # All the *_day fields across SharesDeliveryDay / OrdersDeliveryDay /
        # Order / Share / etc. use the same DayNumberOptions choice set.
        # Without this override, spectacular auto-generates ~8 distinct
        # enum names (HarvestingDayEnum, WashingDayEnum, etc.) that all
        # describe the same Monday-to-Sunday set — one shared
        # ``DayNumberEnum`` keeps the generated TS client cleaner.
        "DayNumberEnum": "apps.commissioning.models.choices.DayNumberOptions",
        # Three unrelated models each have a ``kind`` CharField with its
        # own choice set; without these overrides spectacular falls back
        # to hash-suffixed names like ``Kind085Enum``.
        "OpsChecklistKindEnum": "apps.shared.super_admin.models.OpsChecklistItem.KIND_CHOICES",
        "ExternalCodeMappingKindEnum": "apps.commissioning.models.imports.ExternalCodeMapping.KIND_CHOICES",
        "ConsentKindEnum": "apps.commissioning.models.choices.ConsentKind",
        "TicketStatusEnum": "apps.shared.support.models.TicketStatus",
        "TicketPriorityEnum": "apps.shared.support.models.TicketPriority",
        "AuthorKindEnum": "apps.shared.support.models.AuthorKind",
        # Two request bodies have a ``model`` ChoiceField with different choice
        # sets: bulk (un)finalize and bulk documents. Once a field name carries
        # two sets, spectacular hash-suffixes every set that has no override,
        # so both are named here — keeping the existing ``ModelEnum`` (bulk
        # documents, ``BulkDocumentRequestSerializer.model``) stable.
        "BulkFinalizeRequestModelEnum": "apps.commissioning.serializers.finalize_serializer.FINALIZABLE_MODEL_NAMES",
        "ModelEnum": ["delivery_note", "invoice"],
    },
    "COMPONENT_NO_READ_ONLY_REQUIRED": True,
    "SCHEMA_PATH_PREFIX": "/api/",
    "ENUM_ADD_EXPLICIT_BLANK_NULL_CHOICE": False,
    "SCHEMA_COERCE_PATH_PK": True,
    # Postprocessing to handle any remaining edge cases
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        # Auto-inject canonical 4xx error responses (400/401/403/404)
        # into every operation so the orval-generated frontend client
        # carries a typed ErrorResponse for every endpoint without us
        # having to litter every viewset with ``responses={400: ...}``.
        # Explicit per-view declarations always win — the hook uses
        # setdefault. See ``core.openapi`` for the rules.
        "core.openapi.inject_canonical_error_responses",
    ],
}
