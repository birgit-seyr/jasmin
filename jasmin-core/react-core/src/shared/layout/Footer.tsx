import { Layout } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AboutModal } from "@shared/modals";
const { Footer } = Layout;

export default function JasminFooter() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { t } = useTranslation();

  return (
    <Footer
      style={{
        display: "flex",
        textAlign: "center",
        alignItems: "center",
        justifyContent: "center",
        height: 48,
        fontSize: "0.8em",
      }}
    >
      <span
        role="button"
        tabIndex={0}
        aria-label={t("about.open")}
        onClick={() => setIsModalOpen(true)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setIsModalOpen(true); } }}
        style={{
          marginLeft: "4px",
          cursor: "pointer",
          color: "var(--color-primary)",
        }}
      >
        2026 created by Chance
      </span>
      <AboutModal open={isModalOpen} onClose={() => setIsModalOpen(false)} />
    </Footer>
  );
}
