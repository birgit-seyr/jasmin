import { EditOutlined } from "@ant-design/icons";
import { Button, Card, Space, Table, Tag, Typography } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { EmailTemplateListItem } from "@shared/api/generated/models";
import { useNotificationsEmailTemplatesList } from "@shared/api/generated/notifications/notifications";
import { useTenant } from "@hooks/index";

import EmailTemplateEditorModal from "@features/configuration/modals/EmailTemplateEditorModal";

const { Text, Paragraph } = Typography;

// Display order + localized labels for category groupings. Must match
// CATEGORY_ORDER in apps/notifications/registry.py.
const CATEGORY_ORDER = ["members", "resellers", "users", "office"] as const;
type Category = (typeof CATEGORY_ORDER)[number];

export default function ConfigurationEmailTemplates() {
  const { t, i18n } = useTranslation();
  const { getSetting } = useTenant();
  const [editingSlug, setEditingSlug] = useState<string | null>(null);

  // Member-app templates are only relevant when the member app navigation is
  // enabled for this tenant (configured in ConfigurationApp.tsx).
  const showMembers = getSetting("navigation.show_members", true) as boolean;

  const { data, isLoading } = useNotificationsEmailTemplatesList();

  const formatDate = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(i18n.language, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    return (iso: string | null) => (iso ? fmt.format(new Date(iso)) : "—");
  }, [i18n.language]);

  const grouped = useMemo(() => {
    const rows: EmailTemplateListItem[] = Array.isArray(data) ? data : [];
    const buckets: Record<string, EmailTemplateListItem[]> = {};
    rows.forEach((r) => {
      const cat = (r as { category?: string }).category ?? "users";
      (buckets[cat] ??= []).push(r);
    });
    const known = CATEGORY_ORDER.filter((c) => buckets[c]?.length);
    const extras = Object.keys(buckets).filter(
      (c) => !CATEGORY_ORDER.includes(c as Category),
    );
    return [...known, ...extras]
      .filter((cat) => showMembers || cat !== "members")
      .map((cat) => ({
        category: cat,
        rows: buckets[cat] ?? [],
      }));
  }, [data, showMembers]);

  const categoryLabel = (cat: string) =>
    t(`email_templates.category_${cat}`, {
      defaultValue:
        cat === "members"
          ? t("email_templates.category_members")
          : cat === "resellers"
            ? t("email_templates.category_resellers")
            : cat === "users"
              ? t("email_templates.category_users")
              : cat,
    });

  // Label + description in the registry are hardcoded German. Look up
  // a per-slug translation first, fall back to the backend value if the
  // current locale has no override. Dots in the slug are the i18next
  // nesting separator, so we substitute "_" to keep the key flat.
  const translatedLabel = (row: EmailTemplateListItem) =>
    t(`email_templates.label.${row.slug.replace(/\./g, "_")}`, {
      defaultValue: row.label,
    });
  const translatedDescription = (row: EmailTemplateListItem) =>
    t(`email_templates.description.${row.slug.replace(/\./g, "_")}`, {
      defaultValue: row.description,
    });

  const columns = [
    {
      title: t("email_templates.col_label"),
      dataIndex: "label",
      render: (_: unknown, row: EmailTemplateListItem) => (
        <Space direction="vertical" size={0}>
          <Text strong>{translatedLabel(row)}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {translatedDescription(row)}
          </Text>
        </Space>
      ),
    },
    {
      title: t("email_templates.col_status"),
      dataIndex: "customized_languages",
      width: 160,
      render: (val: string[] | undefined) => {
        const isCustom = (val ?? []).length > 0;
        return isCustom ? (
          <Tag color="blue">
            {t("email_templates.status_custom")}
          </Tag>
        ) : (
          <Tag>{t("email_templates.status_default")}</Tag>
        );
      },
    },
    {
      title: t("email_templates.col_updated"),
      dataIndex: "updated_at",
      width: 200,
      render: (val: string | null) => formatDate(val),
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: unknown, row: EmailTemplateListItem) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => setEditingSlug(row.slug)}
        >
          {t("common.edit")}
        </Button>
      ),
    },
  ];

  return (
    <>
      <h1>{t("email_templates.page_title")}</h1>
      <Paragraph type="secondary">
        {t("email_templates.page_intro")}
      </Paragraph>

      <Space direction="vertical" size="large" className="w-full">
        {grouped.map(({ category, rows }) => (
          <Card
            key={category}
            title={categoryLabel(category)}
            className="settings-card-header"
          >
            <Table<EmailTemplateListItem>
              rowKey="slug"
              loading={isLoading}
              dataSource={rows}
              pagination={false}
              columns={columns}
            />
          </Card>
        ))}
        {!isLoading && grouped.length === 0 && (
          <Card>
            <Text type="secondary">
              {t("email_templates.empty")}
            </Text>
          </Card>
        )}
      </Space>

      <EmailTemplateEditorModal
        slug={editingSlug}
        onClose={() => setEditingSlug(null)}
      />
    </>
  );
}
