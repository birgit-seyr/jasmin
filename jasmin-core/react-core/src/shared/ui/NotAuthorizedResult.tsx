import { Button, Flex, Result } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

interface NotAuthorizedResultProps {
  /** Already-translated reason shown instead of the default subtitle. */
  message?: string;
}

/**
 * The "no access" view of a page the viewer may not open, with a way home and
 * a way back. Renders inside a router.
 */
export default function NotAuthorizedResult({ message }: NotAuthorizedResultProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <Result
      status="403"
      title={t("auth.not_authorized.title")}
      subTitle={message ?? t("auth.not_authorized.message")}
      extra={
        <Flex gap="8px" justify="center">
          <Button type="primary" onClick={() => navigate("/")}>
            {t("auth.not_authorized.back_home")}
          </Button>
          <Button onClick={() => navigate(-1)}>{t("common.back")}</Button>
        </Flex>
      }
    />
  );
}
