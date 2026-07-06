import { ConfigProvider, Layout, theme } from "antd";
import { lazy, Suspense, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes } from "react-router-dom";
import DynamicSidebar from "@shared/layout/DynamicSidebar";
import Footer from "@shared/layout/Footer";
import MainContent from "@shared/layout/MainContent";
import SkipToMainLink from "@shared/layout/SkipToMainLink";
import TopNavigation from "@shared/layout/TopNavigation";
import UserMenu from "@shared/layout/UserMenu";
import { useAuth } from "@shared/contexts/AuthContext";
import { useLocale } from "@shared/contexts/LocalContext";
import { ModalProvider } from "@shared/contexts/ModalContext";
import { NavigationProvider } from "@shared/contexts/NavigationContext";
import { PermissionProvider } from "@shared/contexts/PermissionContext";
import { useTenant, useTheme } from "@hooks/index";
import LoginPage from "@features/auth/pages/LoginPage";
import RegistrationPage from "@features/auth/pages/registration/RegistrationPage";
import SetPasswordPage from "@features/auth/pages/SetPasswordPage";
import ForgotPasswordPage from "@features/auth/pages/ForgotPasswordPage";
import ResetPasswordPage from "@features/auth/pages/ResetPasswordPage";
import PrivacyPolicyPage from "@features/public/pages/PrivacyPolicyPage";
import ImpressumPage from "@features/public/pages/ImpressumPage";
import WaitingListOfferPage from "@features/public/pages/WaitingListOfferPage";

const MemberDetail = lazy(() => import("@features/members/pages/MemberDetail"));
const CustomerOrderPage = lazy(
  () => import("@features/customer/pages/CustomerOrderPage"),
);

import deDE from "antd/locale/de_DE";
import enUS from "antd/locale/en_US";
import itIT from "antd/locale/it_IT";
import frFR from "antd/locale/fr_FR";

const ANTD_LOCALES = { en: enUS, de: deDE, it: itIT, fr: frFR };

export default function JasminApp() {
  const themeTokens = useTheme();
  const { language, theme: userTheme } = useLocale();
  const { tenant } = useTenant();
  const { user, isAuthenticated, bootstrapping } = useAuth();
  const { i18n } = useTranslation();

  const { defaultAlgorithm, darkAlgorithm } = theme;

  const antdLocale = useMemo(
    () => ANTD_LOCALES[language as keyof typeof ANTD_LOCALES] || enUS,
    [language],
  );

  const antdTheme = {
    algorithm: userTheme === "dark" ? darkAlgorithm : defaultAlgorithm,
    token: {
      ...themeTokens,
      colorPrimary: "rgb(29, 96, 62)",
      colorLink: "rgb(29, 96, 62)",
      colorLinkHover: "rgb(169, 227, 159)",
      colorLinkActive: "rgb(136, 0, 111)",
      fontFamily:
        "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif",
    },
  };

  useEffect(() => {
    if (language && i18n.language !== language) {
      i18n.changeLanguage(language);
    }
  }, [language, i18n]);

  // Show the full-screen loader ONLY during the initial auth boot. Gating on
  // the per-action ``loading`` would unmount the login page on every submit and
  // drop the 2FA step (the credentials form would reappear instead of the code
  // field).
  if (bootstrapping) {
    return (
      <ConfigProvider theme={antdTheme} locale={antdLocale}>
        <div
          role="status"
          aria-live="polite"
          className="flex-center"
          style={{
            height: "100vh",
          }}
        >
          Loading...
        </div>
      </ConfigProvider>
    );
  }

  // If not authenticated, show login page WITHOUT layout
  if (!isAuthenticated) {
    return (
      <ConfigProvider theme={antdTheme} locale={antdLocale}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegistrationPage />} />
          <Route path="/set-password/:token" element={<SetPasswordPage />} />
          <Route
            path="/waiting-list-offer/:token"
            element={<WaitingListOfferPage />}
          />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route
            path="/reset-password/:uid/:token"
            element={<ResetPasswordPage />}
          />
          <Route path="/privacy-policy" element={<PrivacyPolicyPage />} />
          <Route path="/impressum" element={<ImpressumPage />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </ConfigProvider>
    );
  }

  // Check user roles
  const hasRole = (role: string) => user?.roles?.includes(role);
  const hasOnlyRole = (role: string) =>
    user?.roles?.length === 1 && user?.roles[0] === role;

  // Allow any user with at least one valid role
  const hasAnyValidRole =
    hasRole("office") ||
    hasRole("management") ||
    hasRole("gardener") ||
    hasRole("pack_team") ||
    hasRole("harvest_team") ||
    hasRole("admin") ||
    hasRole("superuser") ||
    hasRole("staff") ||
    hasRole("member") ||
    hasRole("customer");

  if (!hasAnyValidRole) {
    return (
      <ConfigProvider theme={antdTheme} locale={antdLocale}>
        <Navigate to="/login" replace />
      </ConfigProvider>
    );
  }

  // Member-only users get a minimal layout with just their member
  // page — plus a slim header carrying the unified ``<UserMenu />`` in
  // the top-right so the same login/data/GDPR/language bundle is
  // available across every role's layout.
  if (hasOnlyRole("member")) {
    const memberId = user?.member_id;
    const memberPath = memberId ? `/members/members/${memberId}` : "/login";
    return (
      <ConfigProvider theme={antdTheme} locale={antdLocale}>
        <PermissionProvider user={user} tenant={tenant}>
          <Layout style={{ minHeight: "100vh" }}>
            <Layout.Header
              className="flex-end"
              style={{
                alignItems: "center",
                padding: "0 16px",
                background: "var(--color-bg-container)",
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              <UserMenu />
            </Layout.Header>
            <Layout.Content
              style={{
                padding: "24px",
                background: "var(--color-bg-base)",
                minHeight: "100vh",
              }}
            >
              <Suspense
                fallback={
                  <div role="status" aria-live="polite">
                    Loading...
                  </div>
                }
              >
                <Routes>
                  <Route
                    path="/members/members/:id"
                    element={<MemberDetail />}
                  />
                  <Route
                    path="*"
                    element={<Navigate to={memberPath} replace />}
                  />
                </Routes>
              </Suspense>
            </Layout.Content>
          </Layout>
        </PermissionProvider>
      </ConfigProvider>
    );
  }

  // Customer-only users get a minimal layout with their order page —
  // same header treatment as the member layout above so the
  // ``<UserMenu />`` bundle is in the same place.
  if (hasOnlyRole("customer")) {
    return (
      <ConfigProvider theme={antdTheme} locale={antdLocale}>
        <PermissionProvider user={user} tenant={tenant}>
          <Layout style={{ minHeight: "100vh" }}>
            <Layout.Header
              className="flex-end"
              style={{
                alignItems: "center",
                padding: "0 16px",
                background: "var(--color-bg-container)",
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              <UserMenu />
            </Layout.Header>
            <Layout.Content
              style={{
                padding: "24px",
                background: "var(--color-bg-base)",
                minHeight: "100vh",
              }}
            >
              <Suspense
                fallback={
                  <div role="status" aria-live="polite">
                    Loading...
                  </div>
                }
              >
                <Routes>
                  <Route path="/customer" element={<CustomerOrderPage />} />
                  <Route
                    path="*"
                    element={<Navigate to="/customer" replace />}
                  />
                </Routes>
              </Suspense>
            </Layout.Content>
          </Layout>
        </PermissionProvider>
      </ConfigProvider>
    );
  }

  // Render full app with layout for authenticated staff users
  return (
    <ConfigProvider theme={antdTheme} locale={antdLocale}>
      <PermissionProvider user={user} tenant={tenant}>
        <NavigationProvider>
          <ModalProvider>
            <Layout style={{ minHeight: "100vh" }}>
              <SkipToMainLink />
              <TopNavigation />
              <Layout>
                <DynamicSidebar />
                <MainContent />
              </Layout>
              <Footer />
            </Layout>
          </ModalProvider>
        </NavigationProvider>
      </PermissionProvider>
    </ConfigProvider>
  );
}
