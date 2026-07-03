/**
 * Registers the step-up password modal with the axios interceptor.
 *
 * Mount once near the top of the app tree (JasminApp / SuperAdminApp).
 * When the interceptor receives a ``403 auth.step_up_required`` on
 * a destructive request, it calls into this provider's prompt; the
 * modal asks for the password, returns it to the interceptor, which
 * POSTs ``/api/auth/step-up/``, swaps the rotated access token in,
 * and retries the original request.
 *
 * Why a provider (not a hook): the prompt has to live OUTSIDE any
 * specific React tree path so it can fire from background queries,
 * mutations, and code triggered by route changes. A component
 * mounted once high in the tree is the simplest answer.
 */

import { Alert, Form, Input, Modal, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  registerStepUpPrompt,
  type StepUpCredentials,
  type StepUpPromptArgs,
} from "@shared/services/stepUp";
import { getErrorMessage } from "@shared/utils/apiError";

const { Text } = Typography;

interface PromptResolver {
  /** Resolve the prompt promise — only after ``verify`` succeeded. */
  resolve: () => void;
  reject: (reason: unknown) => void;
}

export function StepUpProvider({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  // ``open`` and ``ttlSeconds`` live in ONE state object so the modal
  // can never render open with a TTL from a previous prompt — the two
  // values update in the same commit by construction, instead of
  // relying on React's batching of two separate setState calls.
  const [promptState, setPromptState] = useState<{
    open: boolean;
    ttlSeconds: number;
  }>({
    open: false,
    ttlSeconds: 300,
  });
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const resolverRef = useRef<PromptResolver | null>(null);
  const verifyRef = useRef<
    ((creds: StepUpCredentials) => Promise<void>) | null
  >(null);
  const [form] = Form.useForm<{ password: string }>();

  // Register the prompt at mount and tear it down on unmount. The
  // registry is module-level so there must be exactly one provider
  // alive at a time.
  useEffect(() => {
    registerStepUpPrompt((args: StepUpPromptArgs) => {
      setErrorMessage(null);
      form.resetFields();
      verifyRef.current = args.verify;
      setPromptState({ open: true, ttlSeconds: args.ttlSeconds });
      return new Promise<void>((resolve, reject) => {
        resolverRef.current = { resolve, reject };
      });
    });
    return () => {
      // Settle a pending prompt before unregistering: if the provider
      // unmounts mid-prompt (e.g. an ErrorBoundary swapping to its
      // fallback), an unsettled promise would keep ``runStepUpFlow``'s
      // ``finally`` from running, wedging its ``inFlight`` dedup for
      // every future destructive request until a full page reload.
      resolverRef.current?.reject(new Error("StepUpProvider unmounted"));
      resolverRef.current = null;
      verifyRef.current = null;
      registerStepUpPrompt(null);
    };
  }, [form]);

  const handleSubmit = useCallback(
    async (values: { password: string }) => {
      const resolver = resolverRef.current;
      const verify = verifyRef.current;
      if (!resolver || !verify) return;
      setSubmitting(true);
      setErrorMessage(null);
      try {
        // Verify BEFORE resolving: a wrong password keeps the modal
        // open with the error instead of failing the original action.
        await verify({ password: values.password });
        resolver.resolve();
        resolverRef.current = null;
        verifyRef.current = null;
        setPromptState((prev) => ({ ...prev, open: false }));
      } catch (err) {
        setErrorMessage(
          getErrorMessage(
            err,
            t("auth.step_up.failed"),
          ),
        );
        form.resetFields();
      } finally {
        setSubmitting(false);
      }
    },
    [form, t],
  );

  const handleCancel = useCallback(() => {
    const resolver = resolverRef.current;
    if (resolver) {
      resolver.reject(new Error("step-up cancelled by user"));
      resolverRef.current = null;
      verifyRef.current = null;
    }
    setPromptState((prev) => ({ ...prev, open: false }));
  }, []);

  const ttlMinutes = Math.round(promptState.ttlSeconds / 60);

  return (
    <>
      {children}
      <Modal
        title={
          <span className="icon-title-row">
            {t("auth.step_up.title")}
          </span>
        }
        open={promptState.open}
        onCancel={handleCancel}
        okText={t("auth.step_up.submit")}
        cancelText={t("common.cancel")}
        onOk={() => form.submit()}
        confirmLoading={submitting}
        wrapClassName="step-up-modal"
        destroyOnHidden
      >
        <Text type="secondary">
          {t("auth.step_up.description")}
        </Text>

        {errorMessage && (
          <Alert
            type="error"
            showIcon
            message={errorMessage}
            style={{ marginTop: 12 }}
          />
        )}

        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            name="password"
            label={t("auth.step_up.password")}
            rules={[
              {
                required: true,
                message: t("auth.step_up.password_required"),
              },
            ]}
          >
            <Input.Password autoFocus autoComplete="current-password" />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t(
              "auth.step_up.ttl_hint",
              { minutes: ttlMinutes },
            )}
          </Text>
        </Form>
      </Modal>
    </>
  );
}

export default StepUpProvider;
