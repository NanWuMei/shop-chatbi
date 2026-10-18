/**
 * error 终态：业务化错误文案 + 「重试」（重试＝原问题重发一轮，原气泡保留）。
 * 不展示错误码/SQL/堆栈（NFR-5）。
 */
import { Button } from 'antd';
import type { ErrorPayload } from '../../api/types';

export default function ErrorMessage({ payload, onRetry }: { payload: ErrorPayload; onRetry: () => void }) {
  return (
    <div className="error-message" data-testid="error-message" role="alert">
      <span className="error-message__text">{payload.message}</span>
      {payload.retryable && (
        <Button size="small" onClick={onRetry} data-testid="error-retry">
          重试
        </Button>
      )}
    </div>
  );
}
