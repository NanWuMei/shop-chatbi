/**
 * 消息渲染器（唯一分发器，Task 5/9 共用）：
 * 六终态穷尽 switch + never 守卫（F14）；历史还原与实时流走同一套（AC-18）。
 */
import { Spin, Typography } from 'antd';
import type { ChatEntry, ClarifySelection } from '../../store/chatStore';
import { assertNever } from '../../api/guard';
import type { AnswerEvent, ClarifyPayload, ErrorPayload, MessagePayload, RejectionPayload, TerminalEvent } from '../../api/types';
import EmptyResult from './EmptyResult';
import ErrorMessage from './ErrorMessage';
import ProcessStatus from './ProcessStatus';
import RejectMessage from './RejectMessage';
import UserBubble from './UserBubble';
import ClarifyCard from './ClarifyCard';
import ResultCard, { answerToCardData } from './ResultCard';

export interface RendererHandlers {
  onClarifyConfirm: (payload: ClarifyPayload, selection: ClarifySelection) => void;
  onClarifyCancel: (clarifyId: string) => void;
  /** suggestions 点选即发问（澄清问法与拒答建议共用） */
  onAskSuggestion: (question: string) => void;
  /** 重试＝原问题重发一轮（error 与两故障码共用） */
  onRetryQuestion: (question: string) => void;
  onRecalibrate: (sourceTurnId: string) => void;
  onOpenSave: (answer: AnswerEvent, turnId: string) => void;
  onCancelTurn: () => void;
}

function TerminalView({
  event,
  payload,
  lastQuestion,
  turnId,
  handlers,
}: {
  event: TerminalEvent;
  payload: MessagePayload;
  lastQuestion: string;
  turnId?: string;
  handlers: RendererHandlers;
}) {
  switch (event) {
    case 'answer': {
      const answer = payload as AnswerEvent;
      return answer.table.rows.length > 0 ? (
        <ResultCard
          data={answerToCardData(answer)}
          terminal="answer"
          turnId={turnId ?? answer.turn_id}
          showActions
          onSave={() => handlers.onOpenSave(answer, turnId ?? answer.turn_id)}
          onRecalibrate={handlers.onRecalibrate}
        />
      ) : (
        <EmptyResult insight={answer.insight} caliber={answer.caliber} />
      );
    }
    case 'clarification':
      return (
        <ClarifyCard
          payload={payload as ClarifyPayload}
          onConfirm={(selection) => handlers.onClarifyConfirm(payload as ClarifyPayload, selection)}
          onCancel={handlers.onClarifyCancel}
          onAskQuestion={handlers.onAskSuggestion}
        />
      );
    case 'rejection':
      return (
        <RejectMessage
          payload={payload as RejectionPayload}
          onSuggest={handlers.onAskSuggestion}
          onRetry={() => handlers.onRetryQuestion(lastQuestion)}
        />
      );
    case 'error':
      return <ErrorMessage payload={payload as unknown as ErrorPayload} onRetry={() => handlers.onRetryQuestion(lastQuestion)} />;
    case 'cancelled':
      return (
        <div className="cancelled-text" data-testid="cancelled-text">
          已取消
        </div>
      );
    default:
      return assertNever(event, '终态事件未穷尽');
  }
}

export default function MessageEntry({
  entry,
  lastQuestion,
  handlers,
}: {
  entry: ChatEntry;
  lastQuestion: string;
  handlers: RendererHandlers;
}) {
  switch (entry.kind) {
    case 'user':
      return <UserBubble question={entry.question} />;
    case 'note':
      return (
        <Typography.Text type="secondary" data-testid="note-text">
          {entry.text}
        </Typography.Text>
      );
    case 'turn': {
      const { machine } = entry;
      if (machine.terminal) {
        return (
          <TerminalView
            event={machine.terminal.event}
            payload={machine.terminal.payload as MessagePayload}
            lastQuestion={lastQuestion}
            turnId={entry.turnId}
            handlers={handlers}
          />
        );
      }
      return <ProcessStatus machine={machine} connectionLost={entry.connectionLost} onCancel={handlers.onCancelTurn} />;
    }
    case 'terminal':
      return <TerminalView event={entry.event} payload={entry.payload} lastQuestion={lastQuestion} handlers={handlers} />;
    default:
      return assertNever(entry, '消息条目类型未穷尽');
  }
}

/** 进行中占位（状态机尚未有帧时的兜底） */
export function TurnPending() {
  return <Spin size="small" />;
}
