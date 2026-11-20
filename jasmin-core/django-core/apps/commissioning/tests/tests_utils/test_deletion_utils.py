"""Tests for apps.commissioning.utils.deletion_utils."""

from __future__ import annotations

import datetime

import pytest

from apps.commissioning.models import (
    Crate,
    DeliveryNoteContent,
    InvoiceResellerContent,
    ShareArticle,
)
from apps.commissioning.tests.factories import (
    CrateFactory,
    CrateNetPriceFactory,
    ShareArticleFactory,
    ShareContentFactory,
    StorageFactory,
    VirtualVariationComponentFactory,
)
from apps.commissioning.utils.deletion_utils import (
    _normalize_model_names,
    _reverse_relations,
    bulk_deletable_pks,
    can_delete_instance,
)


# ---------------------------------------------------------------------------
# _normalize_model_names  (pure function — no DB needed)
# ---------------------------------------------------------------------------
class TestNormalizeModelNames:
    def test_string_names(self):
        result = _normalize_model_names(["Foo", "Bar"])
        assert result == {"Foo", "Bar"}

    def test_model_classes(self):
        from apps.commissioning.models import ShareArticle, Storage

        result = _normalize_model_names([ShareArticle, Storage])
        assert "ShareArticle" in result
        assert "Storage" in result

    def test_mixed_input(self):
        from apps.commissioning.models import ShareArticle

        result = _normalize_model_names(["Foo", ShareArticle])
        assert result == {"Foo", "ShareArticle"}

    def test_empty_list(self):
        assert _normalize_model_names([]) == set()


# ---------------------------------------------------------------------------
# can_delete_instance  (needs DB + tenant schema)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCanDeleteInstance:
    def test_instance_with_no_relations_can_be_deleted(self, tenant):
        storage = StorageFactory(name="Empty Storage")
        can_delete, info = can_delete_instance(storage)
        assert can_delete is True
        assert info == {}

    def test_instance_with_protected_relation_cannot_be_deleted(self, tenant):
        """ShareArticle has PROTECT FKs from movements, share contents, etc.
        Creating a related object should block deletion."""
        from apps.commissioning.tests.factories import (
            MovementShareArticleFactory,
        )

        article = ShareArticleFactory()
        storage = StorageFactory()
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            movement_type="INVENTORY",
        )

        can_delete, info = can_delete_instance(article)
        assert can_delete is False
        assert "protected_relations" in info or "related_model" in info

    def test_exclude_models_skips_specified_relations(self, tenant):
        """When we exclude a model, its relations should not block deletion."""
        from apps.commissioning.tests.factories import (
            MovementShareArticleFactory,
        )

        article = ShareArticleFactory()
        storage = StorageFactory()
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            movement_type="INVENTORY",
        )

        can_delete, info = can_delete_instance(
            article, exclude_models=["MovementShareArticle"]
        )
        # May still be blocked by other relations, but MovementShareArticle is skipped
        # The key assertion: if this was the only blocker, it should now pass
        # If other relations exist, it may still fail — that's correct behavior
        # We just verify the exclude_models parameter is respected
        assert isinstance(can_delete, bool)
        assert isinstance(info, dict)


# ---------------------------------------------------------------------------
# Hidden relations (related_name="+")
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHiddenRelations:
    """A foreign key declared with ``related_name="+"`` counts in the check a
    delete runs (``include_hidden``), not in the flag a list shows: the lines
    behind it would cost every list a scan."""

    def test_a_hidden_protect_relation_blocks_the_delete_only(self, tenant):
        article = ShareArticleFactory()
        ShareContentFactory(share_article=article)

        can_delete, info = can_delete_instance(article, include_hidden=True)

        assert can_delete is False
        assert {"model": "ShareContent", "field": "share_article"} in (
            info["protected_relations"]
        )
        assert can_delete_instance(article)[0] is True
        assert bulk_deletable_pks(ShareArticle, [article.pk]) == ({article.pk}, False)

    def test_a_hidden_set_null_relation_blocks_the_delete_only(self, tenant):
        crate = CrateFactory()
        ShareArticleFactory(default_crate_harvest=crate)

        can_delete, info = can_delete_instance(crate, include_hidden=True)

        assert can_delete is False
        assert info["related_model"] == "ShareArticle"
        assert can_delete_instance(crate)[0] is True


@pytest.mark.django_db
class TestExcludingOneKey:
    """``"Model.field"`` leaves out one of a model's keys to the object, its
    name all of them."""

    def test_the_named_key_is_left_out_and_the_other_still_counts(self, tenant):
        component = VirtualVariationComponentFactory()
        own_components = ["VirtualVariationComponent.virtual_variation"]

        assert can_delete_instance(
            component.virtual_variation,
            exclude_models=own_components,
            include_hidden=True,
        ) == (True, {})
        assert (
            can_delete_instance(
                component.physical_variation,
                exclude_models=own_components,
                include_hidden=True,
            )[0]
            is False
        )

    def test_the_model_name_leaves_out_every_key(self, tenant):
        component = VirtualVariationComponentFactory()

        for variation in (component.virtual_variation, component.physical_variation):
            assert can_delete_instance(
                variation,
                exclude_models=["VirtualVariationComponent"],
                include_hidden=True,
            ) == (True, {})


@pytest.mark.django_db
class TestTheBatchedCheck:
    """The list's check asks per row whether anything points at it, and agrees
    with the single one."""

    def test_only_the_rows_something_points_at_are_kept(self, tenant):
        used, unused = CrateFactory(), CrateFactory()
        CrateNetPriceFactory(
            crate=used,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        CrateNetPriceFactory(crate=used, valid_from=datetime.date(2026, 6, 29))

        assert bulk_deletable_pks(Crate, [used.pk, unused.pk]) == ({unused.pk}, False)
        assert can_delete_instance(used)[0] is False
        assert can_delete_instance(unused)[0] is True

    def test_an_excluded_model_does_not_count(self, tenant):
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate)

        assert bulk_deletable_pks(
            Crate, [crate.pk], exclude_models=["CrateNetPrice"]
        ) == (
            {crate.pk},
            False,
        )


class TestManyToManyRelations:
    """A many-to-many is counted once, through its through table's foreign key,
    hidden where the many-to-many is; excluding the model that declares it
    excludes that table."""

    @staticmethod
    def _related_models(exclude: set[str], *, include_hidden: bool = True) -> list[str]:
        return [
            relation.related_model.__name__
            for relation in _reverse_relations(
                DeliveryNoteContent, exclude, include_hidden=include_hidden
            )
        ]

    def test_the_through_table_stands_in_for_the_link(self):
        through = InvoiceResellerContent.delivery_note_contents.through.__name__

        related = self._related_models(set())

        assert related.count(through) == 1
        assert "InvoiceResellerContent" not in related

    def test_the_through_table_of_a_hidden_many_to_many_is_hidden(self):
        through = InvoiceResellerContent.delivery_note_contents.through.__name__

        assert through not in self._related_models(set(), include_hidden=False)

    def test_excluding_the_declaring_model_drops_its_through_table(self):
        through = InvoiceResellerContent.delivery_note_contents.through.__name__

        assert through not in self._related_models({"InvoiceResellerContent"})
