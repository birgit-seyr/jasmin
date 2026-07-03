import { Button, Card, Form, Input } from "antd";
import type { ChangeEvent } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useTenantsTenantsPartialUpdate } from "@shared/api/generated/tenants/tenants";
import type { Tenant } from "@shared/api/generated/models";
import { useTenant } from "@hooks/index";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

type ControllerFields = {
  legal_form: string;
  data_protection_contact: string;
  dpo: string;
  supervisory_authority: string;
};

/**
 * Art. 30 GDPR record-of-processing (VVT) controller-identity fields. They ride
 * on the ``Tenant`` row and feed the structured ``gdpr_processing_activities``
 * export (VVTExportCard) — an auditor expects them populated. Empty until the
 * office fills them in.
 */
export default function VVTControllerFieldsCard() {
  const { t } = useTranslation();
  const { tenant, refreshTenant } = useTenant();
  const tenantId = tenant?.id as string | undefined;

  const [values, setValues] = useState<ControllerFields>({
    legal_form: "",
    data_protection_contact: "",
    dpo: "",
    supervisory_authority: "",
  });

  useEffect(() => {
    if (!tenant) return;
    setValues({
      legal_form: (tenant.legal_form as string) ?? "",
      data_protection_contact: (tenant.data_protection_contact as string) ?? "",
      dpo: (tenant.dpo as string) ?? "",
      supervisory_authority: (tenant.supervisory_authority as string) ?? "",
    });
  }, [tenant]);

  const { mutate, isPending } = useTenantsTenantsPartialUpdate({
    mutation: {
      onSuccess: async () => {
        notify.success(t("gdpr.vvt_controller_saved"));
        await refreshTenant();
      },
      onError: (error) =>
        notify.error(
          getErrorMessage(error, t("gdpr.vvt_controller_save_failed")),
        ),
    },
  });

  const setField =
    (key: keyof ControllerFields) => (e: ChangeEvent<HTMLInputElement>) =>
      setValues((v) => ({ ...v, [key]: e.target.value }));

  const handleSave = () => {
    if (!tenantId) return;
    mutate({ id: tenantId, data: values as unknown as Tenant });
  };

  const fields: Array<{ key: keyof ControllerFields; label: string }> = [
    { key: "legal_form", label: t("gdpr.vvt_legal_form") },
    {
      key: "data_protection_contact",
      label: t("gdpr.vvt_data_protection_contact"),
    },
    { key: "dpo", label: t("gdpr.vvt_dpo") },
    { key: "supervisory_authority", label: t("gdpr.vvt_supervisory_authority") },
  ];

  return (
    <Card
      className="settings-card-header"
      title={t("gdpr.vvt_controller_card_title")}
    >
      <Form layout="vertical">
        {fields.map((f) => (
          <Form.Item key={f.key} label={f.label}>
            <Input
              value={values[f.key]}
              onChange={setField(f.key)}
              disabled={!tenantId || isPending}
            />
          </Form.Item>
        ))}
        <Button
          type="primary"
          onClick={handleSave}
          disabled={!tenantId || isPending}
          loading={isPending}
        >
          {t("gdpr.vvt_controller_save")}
        </Button>
      </Form>
    </Card>
  );
}
