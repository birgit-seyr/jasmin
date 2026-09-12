import { ArrowLeftOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Drawer, List, Spin, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useSupportTicketsList,
  useSupportTicketsRetrieve,
} from "@shared/api/generated/support/support";
import type { SupportTicketList } from "@shared/api/generated/models";
import { useDateFormat } from "@hooks/index";
import ReplyComposer from "./ReplyComposer";
import SupportTicketModal from "./SupportTicketModal";
import TicketThread from "./TicketThread";
import { statusTagColor } from "./statusColors";

const { Title, Text } = Typography;

/** Master-detail help drawer opened from the top-bar HelpButton. Lists the
 *  user's own tickets (office/admin see the whole tenant, enforced server-side),
 *  opens a thread with a reply composer, and launches the create modal. */
export default function SupportDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // staleTime is 0 globally → this refreshes on open; only fetch while open.
  const listQuery = useSupportTicketsList({ query: { enabled: open } });
  const tickets = (listQuery.data ?? []) as SupportTicketList[];

  const close = () => {
    setSelectedId(null);
    onClose();
  };

  return (
    <Drawer
      open={open}
      onClose={close}
      title={t("support.drawer.title")}
      width={480}
    >
      {selectedId ? (
        <TicketDetail id={selectedId} onBack={() => setSelectedId(null)} />
      ) : (
        <MyTickets
          tickets={tickets}
          loading={listQuery.isLoading}
          onSelect={setSelectedId}
          onNew={() => setModalOpen(true)}
        />
      )}

      <SupportTicketModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(id) => id && setSelectedId(id)}
      />
    </Drawer>
  );
}

function MyTickets({
  tickets,
  loading,
  onSelect,
  onNew,
}: {
  tickets: SupportTicketList[];
  loading: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();

  return (
    <>
      <Button
        type="primary"
        icon={<PlusOutlined />}
        onClick={onNew}
        style={{ marginBottom: 16 }}
      >
        {t("support.drawer.new_ticket")}
      </Button>

      {loading ? (
        <Spin />
      ) : tickets.length === 0 ? (
        <div className="text-muted">{t("support.thread.empty")}</div>
      ) : (
        <List
          dataSource={tickets}
          renderItem={(ticket) => (
            <List.Item key={ticket.id} style={{ padding: 0 }}>
              {/* A real button → keyboard-operable row (not a bare onClick div). */}
              <Button
                type="text"
                block
                onClick={() => ticket.id && onSelect(ticket.id)}
                style={{ height: "auto", padding: "8px 12px", textAlign: "left" }}
              >
                {/* All-span content: a <button> may only contain phrasing
                    content, so no block <div>s inside. */}
                <span className="flex-between" style={{ width: "100%", gap: 8 }}>
                  <span style={{ display: "block", overflow: "hidden" }}>
                    <span className="text-ellipsis" style={{ display: "block" }}>
                      {ticket.subject}
                    </span>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {ticket.created_at ? formatDate(ticket.created_at) : ""}
                    </Text>
                  </span>
                  <Tag color={statusTagColor(ticket.status)}>
                    {t(`support.status.${ticket.status}`)}
                  </Tag>
                </span>
              </Button>
            </List.Item>
          )}
        />
      )}
    </>
  );
}

function TicketDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const { t } = useTranslation();
  const detailQuery = useSupportTicketsRetrieve(id);
  const ticket = detailQuery.data;
  const backRef = useRef<HTMLButtonElement>(null);

  // Move focus into the newly-mounted detail so keyboard/AT users aren't
  // stranded on the now-unmounted list row after selecting a ticket.
  useEffect(() => {
    backRef.current?.focus();
  }, []);

  return (
    <>
      <Button
        ref={backRef}
        type="link"
        icon={<ArrowLeftOutlined />}
        onClick={onBack}
        style={{ paddingLeft: 0, marginBottom: 8 }}
      >
        {t("support.drawer.back")}
      </Button>

      {detailQuery.isLoading || !ticket ? (
        <Spin />
      ) : (
        <>
          <div className="flex-between" style={{ gap: 8 }}>
            <Title level={5} style={{ margin: 0 }}>
              {ticket.subject}
            </Title>
            <Tag color={statusTagColor(ticket.status)}>
              {t(`support.status.${ticket.status}`)}
            </Tag>
          </div>
          <div style={{ marginTop: 12 }}>
            <TicketThread messages={ticket.messages ?? []} />
          </div>
          <ReplyComposer ticketId={id} />
        </>
      )}
    </>
  );
}
