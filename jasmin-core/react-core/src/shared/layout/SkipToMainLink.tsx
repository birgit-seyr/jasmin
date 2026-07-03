import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";

/**
 * A11Y-27: "skip to main content" link. Visually hidden until it receives
 * keyboard focus (first Tab stop), then visible — lets keyboard users jump
 * past the nav straight to the main content. Moves focus to #main-content
 * (which carries tabIndex={-1} so it can receive programmatic focus).
 */
export default function SkipToMainLink() {
  const { t } = useTranslation();

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    const target = document.getElementById("main-content");
    if (target) {
      event.preventDefault();
      target.focus();
      target.scrollIntoView({ block: "start" });
    }
  };

  return (
    <a href="#main-content" onClick={handleClick} className="skip-to-main-link">
      {t("nav.skip_to_main")}
    </a>
  );
}
