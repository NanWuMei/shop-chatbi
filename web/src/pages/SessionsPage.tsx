/**
 * 对话记录页（FR-23~25）：列表（标题/消息数/最后提问时间/创建时间）、打开、删除；
 * 打开=还原历史消息（loadSession → 同一渲染器）。
 */
import { App as AntApp, Button, List, Popconfirm } from 'antd';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSessionStore } from '../store/sessionStore';
import { formatDateTime } from '../utils/format';

export default function SessionsPage() {
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const items = useSessionStore((s) => s.items);
  const loading = useSessionStore((s) => s.loading);
  const load = useSessionStore((s) => s.load);
  const remove = useSessionStore((s) => s.remove);

  useEffect(() => {
    load({ onError: (msg) => message.error(msg) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="sessions-page" data-testid="sessions-page">
      <List
        loading={loading}
        dataSource={items}
        locale={{ emptyText: '暂无会话，去「问数」开启第一次提问' }}
        renderItem={(item) => (
          <List.Item
            className="sessions-page__item"
            actions={[
              <Button key="open" type="link" size="small" onClick={() => navigate(`/chat/${item.id}`)}>
                打开
              </Button>,
              <Popconfirm
                key="del"
                title="删除后不可恢复，确认删除？"
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={async () => {
                  const ok = await remove(item.id, { onError: (msg) => message.error(msg) });
                  if (ok) load({ onError: (msg) => message.error(msg) });
                }}
              >
                <Button type="link" size="small" danger>
                  删除
                </Button>
              </Popconfirm>,
            ]}
            onClick={() => navigate(`/chat/${item.id}`)}
          >
            <List.Item.Meta
              title={<span data-testid="session-title">{item.title}</span>}
              description={
                <span>
                  {item.message_count} 条消息 · 最后提问 {formatDateTime(item.last_question_at)} · 创建于{' '}
                  {formatDateTime(item.created_at)}
                </span>
              }
            />
          </List.Item>
        )}
      />
    </div>
  );
}
