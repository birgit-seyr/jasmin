import NotAuthorizedResult from "@shared/ui/NotAuthorizedResult";

interface UnauthorizedPageProps {
  /** Optional custom subtitle (e.g. a feature-disabled reason). */
  message?: string;
}

const UnauthorizedPage = ({ message }: UnauthorizedPageProps) => (
  <NotAuthorizedResult message={message} />
);
export default UnauthorizedPage;
