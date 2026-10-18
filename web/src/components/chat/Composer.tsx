/**
 * 输入区（FR-4）：空内容置灰；回车发送/Shift+回车换行；客户端长度预校验 500
 * （超长置灰 + 固定提示，不发请求）；发送后乐观渲染用户气泡（由 chatStore.ask 完成）。
 */
import { Input } from 'antd';
import { useMemo } from 'react';
import { QUESTION_MAX_LENGTH, questionSendable } from '../../utils/format';
import { useChatStore } from '../../store/chatStore';

export default function Composer({ onSend }: { onSend: (question: string) => void }) {
  const draft = useChatStore((s) => s.draft);
  const setDraft = useChatStore((s) => s.setDraft);
  const active = useChatStore((s) => s.active);
  const { sendable, reason } = useMemo(() => questionSendable(draft), [draft]);

  const send = () => {
    if (!sendable || active) return;
    onSend(draft.trim());
    setDraft('');
  };

  return (
    <div className="composer" data-testid="composer">
      <Input.TextArea
        value={draft}
        placeholder="输入你的问题，例如：618 大促期间各渠道 GMV，按从高到低排"
        autoSize={{ minRows: 1, maxRows: 4 }}
        onChange={(e) => setDraft(e.target.value)}
        // 回车发送、Shift+回车换行（FR-4）
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        maxLength={QUESTION_MAX_LENGTH + 50} // 硬截断兜底；500 预校验仍生效
        data-testid="composer-input"
        status={reason ? 'error' : undefined}
      />
      <div className="composer__footer">
        <span className="composer__tip" data-testid="composer-tip">
          {reason}
        </span>
        <span className="composer__count">{[...draft.trim()].length}/{QUESTION_MAX_LENGTH}</span>
        <button
          type="button"
          className="composer__send"
          disabled={!sendable}
          onClick={send}
          title={active ? '请等待当前查询完成或取消' : undefined}
          data-testid="composer-send"
        >
          发送
        </button>
      </div>
    </div>
  );
}
