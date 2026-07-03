import { Button, Flex, Result } from "antd";
import { useNavigate } from "react-router-dom";

interface UnauthorizedPageProps {
  /** Optional custom subtitle (e.g. a feature-disabled reason). */
  message?: string;
}

const UnauthorizedPage = ({ message }: UnauthorizedPageProps) => {
  const navigate = useNavigate();

  return (
    <Result
      title="403"
      subTitle={message ?? "Sorry, you are not authorized to access this page."}
      extra={
        <Flex gap="8px" justify="center">
          <Button type="primary" onClick={() => navigate("/")}>
            Back Home
          </Button>
          <Button onClick={() => navigate(-1)}>Go Back</Button>
        </Flex>
      }
    />
  );
};
export default UnauthorizedPage;
