/**
 * 问数页（FR-1~21 / SDD §3.1）：
 * 输入区常驻 → 消息流（同一渲染器）→ 单输入框多轮追问 → 保存/重澄清动作 → 六终态展示。
 * 跨路由保活由 chatStore 提供；URL /chat 就地替换 /chat/:sessionId（FR-2）。
 */
import { App as AntApp, Button, Popconfirm } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { deleteSession } from '../api/client';
import type { AnswerEvent, ClarifyPayload } from '../api/types';
import type { ClarifySelection } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';
import Composer from '../components/chat/Composer';
import MessageStream from '../components/chat/MessageStream';
import type { RendererHandlers } from '../components/chat/MessageEntry';
import SaveReportDialog from '../components/chat/SaveReportDialog';

export default function AskPage() {
  const navigate = useNavigate();
  const { sessionId: routeSessionId } = useParams();
  const { message } = AntApp.useApp();
  const [saveTarget, setSaveTarget] = useState<{ answer: AnswerEvent; turnId: string } | null>(null);

  const sessionId = useChatStore((s) => s.sessionId);
  const entries = useChatStore((s) => s.entries);
  const active = useChatStore((s) => s.active);
  const ask = useChatStore((s) => s.ask);
  const confirmClarify = useChatStore((s) => s.confirmClarify);
  const cancelClarify = useChatStore((s) => s.cancelClarify);
  const recalibrate = useChatStore((s) => s.recalibrate);
  const cancelActiveTurn = useChatStore((s) => s.cancelActiveTurn);
  const addNote = useChatStore((s) => s.addNote);
  const loadSession = useChatStore((s) => s.loadSession);
  const reset = useChatStore((s) => s.reset);

  // 新建会话：清空本地状态回 /chat（不动服务器历史）
  const startNewChat = () => {
    if (active) {
      message.warning('请等待当前查询完成或取消');
      return;
    }
    reset();
    navigate('/chat', { replace: true });
  };

  // 清除聊天记录：删除当前会话（服务器+本地），回到空白问数页
  const clearCurrentChat = async () => {
    if (active) {
      message.warning('请等待当前查询完成或取消');
      return;
    }
    const sid = sessionId ?? routeSessionId;
    if (sid) {
      try {
        await deleteSession(sid);
      } catch (err) {
        message.error(err instanceof Error ? err.message : '删除会话失败，请重试');
        return;
      }
    }
    reset();
    navigate('/chat', { replace: true });
    message.success('聊天记录已清除');
  };

  // 路由会话与 store 不一致时还原历史（AC-2/AC-18）
  useEffect(() => {
    if (routeSessionId && routeSessionId !== sessionId) {
      loadSession(routeSessionId, { onError: (msg) => message.error(msg) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeSessionId]);

  const runTurnOpts = {
    onSessionReady: (sid: string) => navigate(`/chat/${sid}`, { replace: true }),
    onError: (msg: string) => message.error(msg),
  };

  const sendQuestion = (question: string) => {
    if (active) {
      message.warning('请等待当前查询完成或取消');
      return;
    }
    ask(question, runTurnOpts);
  };

  const handlers: RendererHandlers = {
    onClarifyConfirm: (payload: ClarifyPayload, selection: ClarifySelection) => {
      confirmClarify(payload, selection, runTurnOpts);
    },
    onClarifyCancel: cancelClarify,
    onAskSuggestion: sendQuestion,
    onRetryQuestion: sendQuestion,
    onRecalibrate: (turnId) => recalibrate(turnId, runTurnOpts),
    onOpenSave: (answer, turnId) => setSaveTarget({ answer, turnId }),
    onCancelTurn: cancelActiveTurn,
  };

  return (
    <div className="ask-page">
      <div className="ask-page__toolbar" data-testid="ask-toolbar">
        <Button size="small" onClick={startNewChat} data-testid="new-chat-btn">
          新建会话
        </Button>
        <Popconfirm
          title="清除当前聊天记录？"
          description="该会话将被删除，不可恢复"
          okText="清除"
          okButtonProps={{ danger: true }}
          cancelText="取消"
          onConfirm={clearCurrentChat}
        >
          <Button size="small" danger disabled={entries.length === 0 && !sessionId && !routeSessionId} data-testid="clear-chat-btn">
            清除聊天记录
          </Button>
        </Popconfirm>
      </div>
      <div className="ask-page__stream">
        {entries.length === 0 ? (
          <div className="ask-page__empty" data-testid="ask-empty">
            输入一个问题开始，例如：618 大促期间各渠道 GMV，按从高到低排
          </div>
        ) : (
          <MessageStream entries={entries} handlers={handlers} />
        )}
      </div>
      <Composer onSend={sendQuestion} />
      {saveTarget !== null && (
        <SaveReportDialog
          open
          answer={saveTarget.answer}
          turnId={saveTarget.turnId}
          onClose={() => setSaveTarget(null)}
          onSaved={(title) => addNote(`已存为报表：《${title}》`, '/reports')}
          onError={(msg) => message.error(msg)}
        />
      )}
    </div>
  );
}
