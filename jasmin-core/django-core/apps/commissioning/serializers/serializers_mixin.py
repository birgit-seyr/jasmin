from django.db import models
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..utils import (
    build_storage_fields,
    extract_storage_fields_from_data,
)
from ..utils.deletion_utils import bulk_deletable_pks, can_delete_instance


def mask_capacity_for_anonymous(
    data: dict, request, *, internal_fields: tuple[str, ...] = ()
) -> None:
    """Anonymous (public registration) reads must not leak exact occupancy,
    the raw capacity, or internal logistics fields — mutate ``data`` in place
    to an availability-only view.

    ``capacity_by_week`` collapses to ``{occupied: 0, free: 99|0}`` (a busy
    week still reads full, an open one still reads available, but the exact
    subscriber count is gone), ``capacity`` is dropped, and any
    ``internal_fields`` are removed. No-op for authenticated requests —
    office/member keep the exact numbers.
    """
    if request is None or getattr(request.user, "is_authenticated", False):
        return
    capacity_by_week = data.get("capacity_by_week")
    if isinstance(capacity_by_week, dict):
        data["capacity_by_week"] = {
            key: {"occupied": 0, "free": 99 if (entry or {}).get("free", 0) > 0 else 0}
            for key, entry in capacity_by_week.items()
        }
    data["capacity"] = None
    for field in internal_fields:
        data.pop(field, None)


class DeletableListSerializer(serializers.ListSerializer):
    """ListSerializer that pre-computes ``can_be_deleted`` in bulk.

    The naive per-row implementation in :class:`DeletableMixin` walks
    ``model._meta.related_objects`` and calls ``.exists()`` per relation
    — i.e. R queries per row, an O(N*R) N+1 on list endpoints.

    This list serializer collapses that to **R queries total** (one per
    reverse relation, with ``filter(fk__in=all_pks)``). Each child
    serializer's ``get_can_be_deleted`` then reads the precomputed set
    instead of hitting the DB.

    Falls back to the per-instance path when any relation isn't a plain
    reverse FK / O2O (generic relations, m2m through-models with extra
    state, etc.) so behaviour stays identical to ``can_delete_instance``.
    """

    # Set on `self` once `to_representation` runs; child serializers read it.
    _bulk_deletable_pks: set | None = None
    _bulk_failed: bool = False

    def to_representation(self, data):
        instances = list(data)
        if instances:
            self._compute_bulk_deletable(instances)
        return super().to_representation(instances)

    def _compute_bulk_deletable(self, instances: list) -> None:
        model = type(instances[0])
        pks = [obj.pk for obj in instances]
        # Plain reverse FK / O2O reduce to one ``filter(fk__in=pks)`` per
        # relation; m2m and exotic managers make the helper return
        # ``failed=True`` and we fall back to the per-instance path. Presence
        # of ANY related row => not deletable (PROTECT or not), matching
        # ``can_delete_instance``.
        deletable, failed = bulk_deletable_pks(model, pks)
        if failed:
            self._bulk_failed = True
            return
        self._bulk_deletable_pks = deletable


class DeletableMixin:
    """Mixin to add ``can_be_deleted`` to serializers.

    Works with ``fields = '__all__'`` by injecting the field in
    ``get_fields()``. On list endpoints, the bulk
    :class:`DeletableListSerializer` precomputes deletability with R
    queries (one per reverse relation) instead of N*R — see
    ``apps/payments/tests/test_query_count_locks.py`` for the lock.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Auto-wire the bulk ListSerializer for any subclass that hasn't
        # already specified its own. We touch the subclass's own Meta
        # only — never the parent's — to avoid leaking across siblings.
        meta = cls.__dict__.get("Meta")
        if meta is None:
            return
        if not hasattr(meta, "list_serializer_class"):
            meta.list_serializer_class = DeletableListSerializer

    def get_fields(self):
        fields = super().get_fields()
        fields["can_be_deleted"] = serializers.SerializerMethodField()
        # Wire up the method manually since the field is added dynamically
        fields["can_be_deleted"].bind("can_be_deleted", self)
        fields["can_be_deleted"].parent = self
        return fields

    def get_can_be_deleted(self, obj) -> bool:
        # Bulk path: parent ListSerializer precomputed for the whole page.
        parent = getattr(self, "parent", None)
        if (
            isinstance(parent, DeletableListSerializer)
            and not parent._bulk_failed
            and parent._bulk_deletable_pks is not None
        ):
            return obj.pk in parent._bulk_deletable_pks
        # Detail / create / update path — single instance, single check.
        can_delete, _ = can_delete_instance(obj)
        return can_delete


class NameFieldMixin:
    """Mixin to automatically add related name fields."""

    # Define which name fields you want (override in subclass if needed)
    NAME_FIELDS = []  # e.g., [('share_article_name', 'share_article.name')]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_name_fields()

    def _add_name_fields(self):
        """Automatically add name fields defined in NAME_FIELDS."""
        for field_config in self.NAME_FIELDS:
            if isinstance(field_config, tuple):
                field_name, source = field_config
            else:
                field_name = field_config
                # Auto-detect source: 'share_article_name' → 'share_article.name'
                source = f"{field_name.replace('_name', '')}.name"

            self.fields[field_name] = serializers.CharField(
                source=source, read_only=True
            )


class UserNameFieldMixin:
    """Inject ``<fk>_name`` CharFields resolving a user FK to its ``username``
    (read-only, null-safe) — the audit-name pattern (``created_by`` /
    ``admin_confirmed_by`` / ``cancelled_by``). Mirrors :class:`NameFieldMixin`
    via a ``USER_NAME_FIELDS`` list; each ``<fk>_name`` auto-derives source
    ``<fk>.username``. (Distinct from :class:`CreatedByNameMixin`, which renders
    full-name-preferred for the reseller documents — these audit fields
    deliberately show the raw username.)"""

    USER_NAME_FIELDS: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in self.USER_NAME_FIELDS:
            source = f"{field_name.removesuffix('_name')}.username"
            self.fields[field_name] = serializers.CharField(
                source=source, read_only=True, allow_null=True
            )


class MemberStringFieldMixin:
    """Provides ``get_member_string`` for a ``member_string =
    SerializerMethodField()`` — a human-readable ``# <number> - <first> <last>``
    label (name only when the member has no number yet). Subclasses override
    ``_resolve_member(obj)`` (default ``obj.member``); the formatter is shared so
    the label can't drift across the subscription / coop-share / loan rows."""

    def _resolve_member(self, obj):
        return obj.member

    @staticmethod
    def _format_member_string(member) -> str:
        if member is None:
            return ""
        first = member.first_name or ""
        last = member.last_name or ""
        if member.member_number is not None:
            return f"# {member.member_number} - {first} {last}".rstrip()
        return f"{first} {last}".strip()

    def get_member_string(self, obj) -> str:
        return self._format_member_string(self._resolve_member(obj))


class ShareTypeVariationStringMixin:
    """Provides ``get_share_type_variation_string`` for a
    ``share_type_variation_string = SerializerMethodField()`` — the combined
    ``<ShareType name> - <size>`` label the abos tables show for a variation,
    mirrored on the delivery-pause rows so a pause reads the same way as the
    subscription it affects. Subclasses override ``_resolve_variation(obj)``
    (default ``obj.share_type_variation``); the formatter is shared so the
    label can't drift between the two serializers."""

    def _resolve_variation(self, obj):
        return obj.share_type_variation

    @staticmethod
    def _format_variation_string(variation) -> str:
        if variation is None:
            return ""
        return f"{variation.share_type.name} - {variation.size}"

    def get_share_type_variation_string(self, obj) -> str:
        return self._format_variation_string(self._resolve_variation(obj))


class DynamicPrefixPassthroughMixin:
    """Re-attach undeclared dynamic dict keys onto a ``Serializer``'s output.

    A plain declared-field ``Serializer`` drops any source key it doesn't
    declare. Several tour / matrix serializers are fed dicts carrying
    per-variation and per-box-combination count keys (``variation_<id>`` /
    ``combo_<key>``) built at the service layer, which the frontend reads by
    iteration. Subclasses list the prefixes in ``DYNAMIC_KEY_PREFIXES``; the
    mixin's ``to_representation`` merges the matching source keys back in (only
    when serializing a dict, and only keys not already declared). Subclasses
    that need to layer further post-processing (e.g. anonymous masking) call
    ``super().to_representation(instance)`` first."""

    DYNAMIC_KEY_PREFIXES: tuple[str, ...] = ()

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if isinstance(instance, dict) and self.DYNAMIC_KEY_PREFIXES:
            for key, value in instance.items():
                if key.startswith(self.DYNAMIC_KEY_PREFIXES) and key not in ret:
                    ret[key] = value
        return ret


class LinkedUserInfoMixin:
    """Provides ``get_linked_user_info`` for a ``linked_user_info =
    SerializerMethodField()`` — a snapshot of the related JasminUser for the
    user-status modal (member + reseller contexts). ``LINKED_USER_ATTR`` names
    the accessor (``user`` vs ``linked_user``); ``serialize_user_row`` is the
    single shape feeding both modals."""

    LINKED_USER_ATTR = "user"

    def get_linked_user_info(self, obj) -> dict | None:
        user = getattr(obj, self.LINKED_USER_ATTR, None)
        if user is None:
            return None
        from apps.accounts.services.user_admin_service import serialize_user_row

        return serialize_user_row(user)


class LinePricingFieldsMixin:
    """Adds ``line_netto`` and ``line_brutto`` (string decimals) to a line-item
    serializer. Values come straight from the model's ``LinePricingMixin``
    properties so the formula lives in one place (``models.mixin``).

    The fields are injected via ``get_fields()`` (same pattern as
    ``DeletableMixin``): this mixin is a plain ``object``, and DRF's
    metaclass only collects declared Field class attributes from
    serializer bases — declared on a non-Serializer mixin they are
    silently dropped, leaving the fields neither at runtime nor in the
    schema.
    """

    def get_fields(self):
        fields = super().get_fields()
        fields["line_netto"] = serializers.DecimalField(
            max_digits=12, decimal_places=2, read_only=True
        )
        fields["line_brutto"] = serializers.DecimalField(
            max_digits=12, decimal_places=2, read_only=True
        )
        return fields


class TaxBreakdownFieldMixin:
    """Adds ``tax_breakdown`` to a parent document serializer (Order /
    DeliveryNote / Invoice). Decimals are converted to strings so the JSON
    is stable and frontend-safe.

    Injected via ``get_fields()`` for the same metaclass reason as
    ``LinePricingFieldsMixin`` above.
    """

    def get_fields(self):
        fields = super().get_fields()
        field = serializers.SerializerMethodField()
        # Wire up the method manually since the field is added dynamically
        # (same pattern as DeletableMixin).
        field.bind("tax_breakdown", self)
        field.parent = self
        fields["tax_breakdown"] = field
        return fields

    def get_tax_breakdown(self, obj) -> list[dict]:
        return [
            {
                "rate": str(group["rate"]),
                "netto": str(group["netto"]),
                "tax": str(group["tax"]),
                "brutto": str(group["brutto"]),
            }
            for group in obj.tax_breakdown
        ]


class CreatedByNameMixin:
    """Adds ``created_by_name`` — a human-readable name for the document's
    ``created_by`` user — to a parent document serializer (Invoice /
    DeliveryNote). Injected via ``get_fields()`` for the same metaclass reason
    as ``LinePricingFieldsMixin``.
    """

    def get_fields(self):
        fields = super().get_fields()
        field = serializers.SerializerMethodField()
        field.bind("created_by_name", self)
        field.parent = self
        fields["created_by_name"] = field
        return fields

    def get_created_by_name(self, obj) -> str | None:
        """Return a human-readable name for ``created_by``."""
        user = obj.created_by
        if not user:
            return None
        full_name = (getattr(user, "get_full_name", lambda: "")() or "").strip()
        return full_name or getattr(user, "username", None) or str(user)


class ShareArticleResolutionMixin:
    """Adds ``share_article_name`` + ``organic_status`` to a line-item content
    serializer (Invoice / DeliveryNote), resolving through the line's ``offer``
    when ``share_article`` isn't set directly.

    ``organic_status`` is the EU 2018/848 disclosure: the PDF appends "*" (organic)
    or "**" (in transition) to the article name and prints a footer block
    referencing ``Tenant.organic_control_number`` iff any line carries one of
    those marks. Injected via ``get_fields()`` for the same metaclass reason as
    ``LinePricingFieldsMixin``.
    """

    def get_fields(self):
        fields = super().get_fields()
        for name in ("share_article_name", "organic_status"):
            field = serializers.SerializerMethodField()
            field.bind(name, self)
            field.parent = self
            fields[name] = field
        return fields

    def get_share_article_name(self, obj) -> str | None:
        """Get share article name from direct relation or through offer."""
        if obj.share_article:
            return obj.share_article.name
        if obj.offer and obj.offer.share_article:
            return obj.offer.share_article.name
        return None

    def get_organic_status(self, obj) -> str | None:
        if obj.share_article:
            return obj.share_article.organic_status
        if obj.offer and obj.offer.share_article:
            return obj.offer.share_article.organic_status
        return None


class StorageFieldsMixin:
    """
    Mixin to add dynamic storage fields functionality to serializers.
    example: storage_xkdiealkyi
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_storage_fields()

    def _active_storages(self) -> list:
        """Active Storage rows, fetched once per serializer instance.

        DRF's list serializer reuses ONE child instance for every row, so
        memoizing here evaluates ``Storage.objects.filter(is_active=True)``
        once per response instead of once per row (the previous N+1).
        Tenant-safe: a serializer instance only ever serves one request /
        schema.

        Defensive against being instantiated outside a tenant context (e.g.
        drf-spectacular schema generation on the public schema, where the
        Storage table is unreachable) — returns ``[]`` so the dynamic fields
        are simply skipped.
        """
        cached = getattr(self, "_active_storages_cache", None)
        if cached is None:
            from django.db import DatabaseError

            from ..models.basics import Storage

            try:
                cached = list(Storage.objects.filter(is_active=True))
            except DatabaseError:
                cached = []
            self._active_storages_cache = cached
        return cached

    def _add_storage_fields(self):
        """Add a boolean field per active storage (e.g. ``storage_<id>``)."""
        for storage in self._active_storages():
            field_name = f"storage_{storage.id}"
            self.fields[field_name] = serializers.BooleanField(
                required=False, default=False
            )

    def to_representation(self, instance):
        """
        Convert model instance to dictionary representation.
        Handles both dict data and model instances.
        """
        if isinstance(instance, dict):
            # Data is already a dictionary (from summary method)
            return instance
        else:
            # Data is a model instance, use default serialization
            data = super().to_representation(instance)

            # Add storage fields (active storages cached for the whole list).
            storage_fields = build_storage_fields(
                instance, active_storages=self._active_storages()
            )
            data.update(storage_fields)

            return data

    def to_internal_value(self, data):
        """
        Handle incoming data with storage fields.
        """
        # Let the parent handle the basic validation
        validated_data = super().to_internal_value(data)

        # Add storage fields using utility function
        storage_fields = extract_storage_fields_from_data(
            data, active_storages=self._active_storages()
        )
        validated_data.update(storage_fields)

        return validated_data


# Shared DIFF_FIELDS sets for DifferenceTrackingMixin subclasses (the reseller
# invoice + delivery-note content serializers). One home so a field added to a
# document type's diff can't be silently skipped on its twin.
ARTICLE_DIFF_FIELDS = ["amount", "price_per_unit", "rabatt", "unit", "size"]
CRATE_DIFF_FIELDS = ["amount", "price_per_unit", "rabatt"]


class DifferenceTrackingMixin:
    """Expose ``<api>_differs`` and ``original_<model_field>`` SerializerMethodFields.

    Reads the snapshot of the upstream value from the model's local
    ``source_<model_field>`` column. Pure local field comparison — no FK
    traversal, no N+1 queries.

    Subclasses declare which fields participate via ``DIFF_FIELDS``. Each
    entry is either a plain string (api name == model field name) or a
    ``(api_name, model_field)`` tuple to alias::

        class FooSerializer(DifferenceTrackingMixin, ...):
            # ``price_differs`` / ``original_price_per_unit``
            DIFF_FIELDS = ["amount", ("price", "price_per_unit"), "rabatt"]

    For pseudo-fields that don't have a single ``source_<name>`` column
    (e.g. ``article`` which compares two FKs), override
    :meth:`_get_pseudo_diff` and add the field name to ``DIFF_PSEUDO``.

    Diff is auto-skipped when :meth:`_diff_disabled` returns True. Default
    impl returns ``True`` for stornos and corrections (negated/adjusted
    amounts make the comparison meaningless).
    """

    DIFF_FIELDS: list = ["amount", ("price", "price_per_unit"), "rabatt"]
    DIFF_PSEUDO: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_difference_fields()

    @classmethod
    def _iter_diff(cls):
        """Yield ``(api_name, model_field)`` pairs."""
        for entry in cls.DIFF_FIELDS:
            if isinstance(entry, tuple):
                yield entry
            else:
                yield (entry, entry)

    def _add_difference_fields(self):
        for api_name, model_field in self._iter_diff():
            self.fields[f"{api_name}_differs"] = serializers.SerializerMethodField()
            self.fields[f"original_{model_field}"] = serializers.SerializerMethodField()
        for field in self.DIFF_PSEUDO:
            self.fields[f"{field}_differs"] = serializers.SerializerMethodField()

    # -- override hooks ----------------------------------------------------
    def _diff_disabled(self, obj) -> bool:
        """Return True to skip the entire diff for this row.

        Default rule: invoice rows belonging to a storno or correction
        document — their amounts are negated/adjusted, so comparing them to
        the original delivery-note row is misleading.
        """
        invoice = getattr(obj, "invoice", None)
        if invoice and getattr(invoice, "document_type", "") in (
            "storno",
            "correction",
        ):
            return True
        return False

    def _get_pseudo_diff(self, obj, name: str) -> bool:
        """Override for pseudo-fields declared in ``DIFF_PSEUDO``."""
        raise NotImplementedError

    # -- internals ---------------------------------------------------------
    def _source_attr(self, obj, model_field: str):
        # ``DIFF_FIELDS`` is paired with matching ``source_<field>``
        # snapshot columns on the model (see ``SourceSnapshotMixin``).
        # No safety default: a ``DIFF_FIELDS`` entry without its source
        # column should raise here, not silently report "no diff".
        return getattr(obj, f"source_{model_field}")

    def _differs(self, obj, model_field: str) -> bool:
        if self._diff_disabled(obj):
            return False
        source = self._source_attr(obj, model_field)
        if source is None:
            return False
        # ``model_field`` is the live attribute paired with the
        # snapshot; it MUST exist on the model — raise on typo rather
        # than silently flag every row as "differs".
        return getattr(obj, model_field) != source

    def _original(self, obj, model_field: str):
        if self._diff_disabled(obj):
            return None
        # Return the raw snapshot value; the JSON serializer handles type
        # coercion (Decimal → str, int → number, etc.). The frontend wraps
        # the value in ``String(...)`` for display either way.
        return self._source_attr(obj, model_field)

    def __getattribute__(self, name):
        try:
            cls = object.__getattribute__(self, "__class__")
            api_to_model = {api: m for api, m in cls._iter_diff()}
            model_to_api = {m: api for api, m in api_to_model.items()}
            pseudo = object.__getattribute__(self, "DIFF_PSEUDO")
        except AttributeError:
            return super().__getattribute__(name)

        # Annotate the generated lambdas so drf-spectacular doesn't fall
        # back to "string" for the dynamic *_differs / original_* fields
        # (each cascade becomes a spurious schema warning otherwise).
        if name.startswith("get_") and name.endswith("_differs"):
            api_name = name[4:-8]
            if api_name in api_to_model:
                model_field = api_to_model[api_name]
                return extend_schema_field(OpenApiTypes.BOOL)(
                    lambda obj, _f=model_field: self._differs(obj, _f)
                )
            if api_name in pseudo:
                return extend_schema_field(OpenApiTypes.BOOL)(
                    lambda obj, _f=api_name: (
                        False
                        if self._diff_disabled(obj)
                        else self._get_pseudo_diff(obj, _f)
                    )
                )

        elif name.startswith("get_original_"):
            model_field = name[len("get_original_") :]
            if model_field in model_to_api:
                # Snapshot value is Decimal/int/str/None — DRF coerces all
                # of these to string on the JSON wire, so annotate as STR.
                return extend_schema_field(OpenApiTypes.STR)(
                    lambda obj, _f=model_field: self._original(obj, _f)
                )

        return super().__getattribute__(name)


class DynamicContactFieldsMixin:
    """
    Mixin to automatically add ContactEntity fields to a serializer.

    Supports two modes:
    - Simple mode (required=False for all fields)
    - Strict mode (required based on model definition)

    Usage:
        class MySerializer(DynamicContactFieldsMixin, serializers.ModelSerializer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._add_contact_fields(strict_required=True)
    """

    def _add_contact_fields(
        self,
        prefix: str = "",
        exclude_fields: set = None,
        strict_required: bool = False,
        handle_conflicts: bool = True,
    ):
        """
        Add all ContactEntity fields to the serializer.

        Args:
            prefix: Optional prefix for field names (e.g., "contact_")
            exclude_fields: Set of field names to exclude
            strict_required: If True, detect required fields from model definition
            handle_conflicts: If True, auto-prefix conflicting fields (name, note)

        Example:
            >>> # Simple mode (DeliveryStation)
            >>> self._add_contact_fields(handle_conflicts=True)

            >>> # Strict mode (Reseller)
            >>> self._add_contact_fields(strict_required=True)
        """
        from ..models import ContactEntity

        # Default exclusions
        if exclude_fields is None:
            exclude_fields = {"id", "created_at", "updated_at"}

        # Fields that should be prefixed if handle_conflicts=True
        conflict_fields = {"name", "note"}

        for field in ContactEntity._meta.get_fields():
            # Skip relations and excluded fields
            if (
                field.many_to_many
                or field.one_to_many
                or field.one_to_one
                or field.name in exclude_fields
            ):
                continue

            # Determine field name with prefix
            if handle_conflicts and field.name in conflict_fields:
                field_name = f"contact_{field.name}"
            elif prefix:
                field_name = f"{prefix}{field.name}"
            else:
                field_name = field.name

            # Determine if required
            if strict_required:
                is_required = not field.blank and not field.null
            else:
                is_required = False

            # Add the field based on its type
            self.fields[field_name] = self._create_contact_field(field, is_required)

        # The model's ``contact`` FK is never written directly by the client —
        # it's built from the flattened fields above by the create/update
        # service, which assigns ``validated_data["contact"]`` itself. Mark it
        # read-only so a NON-NULL FK (e.g. ``Reseller.contact`` = PROTECT) does
        # not become a required write field that rejects the flattened-field
        # payload with "contact: this field is required".
        if "contact" in self.fields:
            self.fields["contact"] = serializers.PrimaryKeyRelatedField(read_only=True)

    def _create_contact_field(self, field, is_required: bool):
        """Create appropriate serializer field for a Django model field."""
        allow_null = getattr(field, "null", False)
        allow_blank = getattr(field, "blank", False)

        if isinstance(field, models.BooleanField):
            return serializers.BooleanField(required=is_required, allow_null=allow_null)

        elif isinstance(field, models.EmailField):
            return serializers.EmailField(
                max_length=getattr(field, "max_length", 254),
                required=is_required,
                allow_null=allow_null,
                allow_blank=allow_blank,
            )

        elif isinstance(field, models.CharField):
            return serializers.CharField(
                max_length=field.max_length,
                required=is_required,
                allow_null=allow_null,
                allow_blank=allow_blank,
            )

        elif isinstance(field, models.TextField):
            return serializers.CharField(
                required=is_required,
                allow_null=allow_null,
                allow_blank=allow_blank,
            )

        elif isinstance(field, models.DecimalField):
            return serializers.DecimalField(
                max_digits=field.max_digits,
                decimal_places=field.decimal_places,
                required=is_required,
                allow_null=allow_null,
            )

        elif isinstance(field, models.IntegerField):
            return serializers.IntegerField(required=is_required, allow_null=allow_null)

        elif isinstance(field, models.URLField):
            return serializers.URLField(
                required=is_required,
                allow_null=allow_null,
            )

        elif isinstance(field, models.OneToOneField):
            return serializers.PrimaryKeyRelatedField(
                queryset=field.related_model.objects.all(),
                required=is_required,
                allow_null=allow_null,
            )

        # Fallback for other field types
        else:
            return serializers.CharField(
                required=is_required,
                allow_null=allow_null,
                allow_blank=True,
            )

    def _get_contact_field_names(self, exclude_fields: set = None):
        """
        Get list of contact field names.

        Useful for validation logic.
        """
        from ..models import ContactEntity

        if exclude_fields is None:
            exclude_fields = {"id", "created_at", "updated_at"}

        return [
            field.name
            for field in ContactEntity._meta.get_fields()
            if (
                not field.many_to_many
                and not field.one_to_many
                and not field.one_to_one
                and field.name not in exclude_fields
            )
        ]

    def _get_required_contact_fields(self, exclude_fields: set = None):
        """
        Get list of required contact field names.

        Useful for validation logic.
        """
        from ..models import ContactEntity

        if exclude_fields is None:
            exclude_fields = {"id", "created_at", "updated_at"}

        required_fields = []

        for field in ContactEntity._meta.get_fields():
            if (
                not field.many_to_many
                and not field.one_to_many
                and not field.one_to_one
                and field.name not in exclude_fields
                and not field.blank
                and not field.null
            ):
                required_fields.append(field.name)

        return required_fields


class DynamicDeliveryDayFieldsMixin:
    """
    Mixin to automatically add delivery day fields to a serializer.

    Usage:
        class MySerializer(DynamicDeliveryDayFieldsMixin, serializers.ModelSerializer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._add_day_fields()
    """

    def _add_day_fields(self):
        """
        Add dynamic day fields for current and future delivery days.

        Field names are the delivery day IDs, values are booleans.

        Defensive against being instantiated outside of a tenant context
        (e.g. during drf-spectacular schema generation, which runs on the
        public schema where tenant tables don't exist). When the
        SharesDeliveryDay table is unreachable we simply skip the dynamic
        fields — mirrors the pattern in ``StorageFieldsMixin``.
        """
        from django.db import DatabaseError
        from django.utils import timezone

        from ..models import SharesDeliveryDay

        now = timezone.now().date()

        try:
            current_shares_delivery_days = list(
                SharesDeliveryDay.current.active_at_date(now)
            )
            future_shares_delivery_days = list(
                SharesDeliveryDay.objects.filter(valid_until__isnull=True).exclude(
                    id__in=current_shares_delivery_days
                )
            )
        except DatabaseError:
            return

        all_delivery_days = current_shares_delivery_days + future_shares_delivery_days

        # Add a boolean field for each delivery day
        for day in all_delivery_days:
            field_name = str(day.id)
            self.fields[field_name] = serializers.BooleanField(
                read_only=True,
                required=False,
            )
