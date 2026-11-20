import { Alert, Button, Card, Spin, Tag } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningLabelTemplatesListQueryKey,
  useCommissioningLabelTemplatesCreate,
  useCommissioningLabelTemplatesList,
  useCommissioningLabelTemplatesUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import { useLabelFarm } from "@features/commissioning/hooks";
import { LabelsPDFGenerator } from "@features/commissioning/pdfs";
import {
  DEFAULT_LAYOUT,
  MAX_LABEL_ELEMENTS,
  layoutOf,
  newElement,
  templateRequest,
  type LabelData,
  type LabelField,
  type LabelLayout,
  type PlacedElement,
} from "@features/commissioning/utils/labelLayout";
import { useDateFormat } from "@hooks/index";
import { ExplainerText } from "@shared/ui";
import { notify } from "@shared/utils";
import { todayApiDate } from "@shared/utils/apiDate";
import { getErrorMessage } from "@shared/utils/apiError";
import LabelCanvas from "../components/labels/LabelCanvas";
import LabelElementPanel from "../components/labels/LabelElementPanel";
import LabelFieldPalette from "../components/labels/LabelFieldPalette";
import LabelPrintSettings from "../components/labels/LabelPrintSettings";

/**
 * The editor of the farm's label: its size, how it is printed, and where each
 * piece of information goes on it. Changes stay a draft until saved; a test
 * print shows the draft with sample data on the printer it is set up for.
 */
export default function ConfigurationLabels() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { formatDate } = useDateFormat();
  const { farm, logoUrl, bioLogoUrl } = useLabelFarm();

  const {
    data: templates,
    isLoading,
    isError,
    refetch,
  } = useCommissioningLabelTemplatesList();
  const stored = templates?.[0];
  const storedLayout = useMemo(
    () => (stored ? layoutOf(stored) : DEFAULT_LAYOUT),
    [stored],
  );
  const [draft, setDraft] = useState<LabelLayout | null>(null);
  const layout = draft ?? storedLayout;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = layout.elements.find((element) => element.id === selectedId);

  const edit = (change: Partial<LabelLayout>) => setDraft({ ...layout, ...change });
  const editElement = (id: string, change: Partial<PlacedElement>) =>
    edit({
      elements: layout.elements.map((element) =>
        element.id === id ? { ...element, ...change } : element,
      ),
    });
  const removeElement = (id: string) => {
    edit({ elements: layout.elements.filter((element) => element.id !== id) });
    setSelectedId(null);
  };
  const addElement = (field: LabelField, at?: { x: number; y: number }) => {
    const element = newElement(field, layout, at);
    edit({ elements: [...layout.elements, element] });
    setSelectedId(element.id);
  };

  const create = useCommissioningLabelTemplatesCreate();
  const update = useCommissioningLabelTemplatesUpdate();
  const saving = create.isPending || update.isPending;
  const save = async () => {
    const savedDraft = draft;
    const data = templateRequest(
      layout,
      stored?.name ?? t("commissioning.labels.template_name"),
    );
    try {
      const saved = stored
        ? await update.mutateAsync({ id: stored.id, data })
        : await create.mutateAsync({ data });
      // Kept as the farm's template at once, so a refetch that fails doesn't
      // make the next save create a second one.
      queryClient.setQueryData(getCommissioningLabelTemplatesListQueryKey(), [
        saved,
        ...(templates ?? []).filter((template) => template.id !== saved.id),
      ]);
      // An edit made while the save was on its way stays a draft.
      setDraft((current) => (current === savedDraft ? null : current));
      notify.success(t("commissioning.labels.saved"));
    } catch (error) {
      notify.error(getErrorMessage(error, t("common.action_failed")));
    }
  };

  const sample = useMemo<LabelData>(
    () => ({
      resellerName: t("commissioning.labels.sample.reseller"),
      resellerAddress: t("commissioning.labels.sample.address"),
      resellerCity: t("commissioning.labels.sample.city"),
      article: t("commissioning.labels.sample.article"),
      isOrganic: true,
      isCertified: true,
      sort: t("commissioning.labels.sample.sort"),
      size: "",
      amountPerPu: t("commissioning.labels.sample.amount"),
      deliveryDate: formatDate(todayApiDate()) ?? "",
      orderNumber: t("commissioning.labels.sample.order_number"),
    }),
    [t, formatDate],
  );
  // A sheet is tried out whole, so its alignment on the paper shows.
  const testLabels = useMemo(
    () =>
      Array.from(
        {
          length:
            layout.printMode === "sheet"
              ? layout.sheet.columns * layout.sheet.rows
              : 1,
        },
        () => sample,
      ),
    [layout.printMode, layout.sheet.columns, layout.sheet.rows, sample],
  );

  if (isLoading) {
    return (
      <div className="flex-center">
        <Spin />
      </div>
    );
  }
  // A failed load is shown as such, never as a farm without a template: a
  // save from the default would create a second one.
  if (isError && !templates) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("table.load_failed_title")}
        description={t("table.load_failed_hint")}
        action={
          <Button size="small" onClick={() => refetch()}>
            {t("table.retry")}
          </Button>
        }
      />
    );
  }

  return (
    <div>
      <h1>{t("commissioning.labels.template_title")}</h1>
      <div className="labels-editor__actions">
        <Button type="primary" onClick={save} loading={saving} disabled={!draft && !!stored}>
          {t("commissioning.labels.save")}
        </Button>
        <LabelsPDFGenerator
          layout={layout}
          labels={testLabels}
          farm={farm}
          logoUrl={logoUrl}
          bioLogoUrl={bioLogoUrl}
          filename={t("commissioning.labels.test_print_file")}
          buttonText={t("commissioning.labels.test_print")}
        />
        {(draft || !stored) && <Tag color="orange">{t("commissioning.labels.unsaved")}</Tag>}
      </div>

      {/* Top to bottom: how it prints, the label at its real size, the
          fields to put on it, then the selected field's details. */}
      <div className="labels-editor">
        <Card size="small" title={t("commissioning.labels.print_settings")}>
          <LabelPrintSettings layout={layout} onChange={edit} />
        </Card>
        <LabelCanvas
          layout={layout}
          sample={sample}
          farm={farm}
          logoUrl={logoUrl}
          bioLogoUrl={bioLogoUrl}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onChange={editElement}
          onRemove={removeElement}
          onAdd={addElement}
        />
        <LabelFieldPalette
          onAdd={addElement}
          hiddenFields={farm.organicEnabled ? [] : ["organic_logo", "control_number"]}
          full={layout.elements.length >= MAX_LABEL_ELEMENTS}
        />
        {selected ? (
          <LabelElementPanel
            element={selected}
            onChange={(change) => editElement(selected.id, change)}
            onRemove={() => removeElement(selected.id)}
          />
        ) : (
          <p className="labels-editor__hint">{t("commissioning.labels.select_hint")}</p>
        )}
      </div>

      <ExplainerText title={t("common.info")}>
        {t("explainers.labels_editor")}
      </ExplainerText>
    </div>
  );
}
