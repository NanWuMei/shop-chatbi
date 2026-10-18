/**
 * 拒答卡（F3/FR-13）：统一容器 + 六 reason_code 分支。
 * 四业务码＝业务拒答态（reason_text 全用后端文案 + suggestions 点选发问，无重试图标）；
 * QUERY_TIMEOUT/QUERY_ERROR＝故障态视觉 + 重试（原问题重发）。不外露码值/SQL/lint/堆栈。
 */
import { Alert, Button, Space } from 'antd';
import { WarningOutlined } from '@ant-design/icons';
import { BUSINESS_REJECTION_CODES, type RejectionPayload } from '../../api/types';

export default function RejectMessage({
  payload,
  onSuggest,
  onRetry,
}: {
  payload: RejectionPayload;
  /** suggestions 点选即发问 */
  onSuggest: (question: string) => void;
  /** 重试＝原问题重发（仅故障码） */
  onRetry: () => void;
}) {
  const isFault = !BUSINESS_REJECTION_CODES.includes(payload.reason_code);

  return (
    <Alert
      className={isFault ? 'reject-message reject-message--fault' : 'reject-message'}
      type={isFault ? 'error' : 'warning'}
      icon={isFault ? <WarningOutlined /> : undefined}
      showIcon
      data-testid={`reject-${payload.reason_code}`}
      message={
        <Space direction="vertical" style={{ width: '100%' }}>
          <span data-testid="reject-text">{payload.reason_text}</span>
          {payload.suggestions.length > 0 && (
            <Space wrap data-testid="reject-suggestions">
              {payload.suggestions.map((s) => (
                <Button key={s.question} size="small" onClick={() => onSuggest(s.question)}>
                  {s.label}
                </Button>
              ))}
            </Space>
          )}
          {isFault && (
            <Button size="small" danger onClick={onRetry} data-testid="reject-retry">
              重试
            </Button>
          )}
        </Space>
      }
    />
  );
}
