import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import MessageEntry, { type RendererHandlers } from './MessageEntry';
import { initialTurnState, turnReducer, type TurnMachineState } from '../../api/sse';
import {
  answerBar,
  answerEmpty,
  clarifySingleChoice,
  errorLlmUnavailable,
  rejectionNotDataQuestion,
  rejectionQueryTimeout,
} from '../../test/fixtures';

function handlers(): RendererHandlers & Record<string, ReturnType<typeof vi.fn>> {
  return {
    onClarifyConfirm: vi.fn(),
    onClarifyCancel: vi.fn(),
    onAskSuggestion: vi.fn(),
    onRetryQuestion: vi.fn(),
    onRecalibrate: vi.fn(),
    onOpenSave: vi.fn(),
    onCancelTurn: vi.fn(),
  } as never;
}

function turnEntryWith(machine: TurnMachineState) {
  return { kind: 'turn' as const, id: 'e1', turnId: 'turn-0001', machine, connectionLost: false };
}

function stagedTurn(frames: Array<{ event: Parameters<typeof turnReducer>[1]['event']; data: unknown }>) {
  let machine = initialTurnState();
  for (const f of frames) machine = turnReducer(machine, f as never);
  return machine;
}

describe('MessageEntry 六终态渲染（AC-6~13/F14）', () => {
  it('answer 非空 → ResultCard：insight/图区/表区/口径/操作区齐备', () => {
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'answer', payload: answerBar }} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByTestId('insight')).toHaveTextContent('渠道 A 的 GMV 最高');
    expect(screen.getByTestId('data-table')).toBeInTheDocument();
    expect(screen.getByTestId('result-card')).toBeInTheDocument();
  });

  it('answer 空结果 → EmptyResult：无图无表无保存', () => {
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'answer', payload: answerEmpty }} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByTestId('empty-result')).toBeInTheDocument();
    expect(screen.queryByTestId('data-table')).toBeNull();
    expect(screen.queryByText('存为报表')).toBeNull();
  });

  it('clarification pending → 可交互澄清卡', () => {
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'clarification', payload: clarifySingleChoice }} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByTestId('clarify-card')).toBeInTheDocument();
  });

  it('rejection 业务码 → 文案 + 建议点选发问；建议点击调 onAskSuggestion', async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'rejection', payload: rejectionNotDataQuestion }} lastQuestion="为什么渠道 A 卖得好" handlers={h} />);
    expect(screen.getByTestId('reject-NOT_DATA_QUESTION')).toBeInTheDocument();
    await user.click(screen.getByText('618 各渠道 GMV 排行'));
    expect(h.onAskSuggestion).toHaveBeenCalledWith('618 大促期间各渠道 GMV 是多少，按从高到低排');
  });

  it('rejection 故障码 → 重试按钮（原问题重发）', async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'rejection', payload: rejectionQueryTimeout }} lastQuestion="618 各渠道 GMV" handlers={h} />);
    await user.click(screen.getByTestId('reject-retry'));
    expect(h.onRetryQuestion).toHaveBeenCalledWith('618 各渠道 GMV');
  });

  it('error → 业务文案 + 重试；不出现错误码', () => {
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'error', payload: errorLlmUnavailable }} lastQuestion="618 各渠道 GMV" handlers={handlers()} />);
    expect(screen.getByTestId('error-message')).toHaveTextContent('大模型服务暂不可用');
    expect(screen.queryByText('E_LLM_UNAVAILABLE')).toBeNull();
  });

  it('cancelled → 静态"已取消"，无半成品卡（F10）', () => {
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'cancelled', payload: { turn_id: 't' } }} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByTestId('cancelled-text')).toHaveTextContent('已取消');
    expect(screen.queryByTestId('result-card')).toBeNull();
  });

  it('note → 静态文本（可带链接）', () => {
    render(<MessageEntry entry={{ kind: 'note', id: 'e', text: '已存为报表：《618 各渠道 GMV 排行》', href: '/reports' }} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByTestId('note-text')).toHaveTextContent('已存为报表');
  });
});

describe('turn 条目渲染（FR-7/AC-6）', () => {
  it('无终态 → ProcessStatus 三行 + 取消按钮', () => {
    const machine = stagedTurn([{ event: 'stage', data: { stage: 'understanding', label: '正在理解问题' } }]);
    const h = handlers();
    render(<MessageEntry entry={turnEntryWith(machine)} lastQuestion="" handlers={h} />);
    expect(screen.getByTestId('stage-understanding')).toBeInTheDocument();
    expect(screen.getByTestId('cancel-btn')).toBeInTheDocument();
  });

  it('连接中断 → "连接中断，重试"且无取消', () => {
    const machine = stagedTurn([{ event: 'stage', data: { stage: 'understanding', label: 'x' } }]);
    render(
      <MessageEntry
        entry={{ kind: 'turn', id: 'e1', turnId: 't1', machine, connectionLost: true }}
        lastQuestion=""
        handlers={handlers()}
      />,
    );
    expect(screen.getByTestId('connection-lost')).toHaveTextContent('连接中断，重试');
    expect(screen.queryByTestId('cancel-btn')).toBeNull();
  });

  it('流中终态 answer → 结果卡；取消按钮消失', () => {
    const machine = stagedTurn([
      { event: 'stage', data: { stage: 'understanding', label: 'x' } },
      { event: 'answer', data: answerBar },
    ]);
    render(<MessageEntry entry={turnEntryWith(machine)} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByTestId('result-card')).toBeInTheDocument();
    expect(screen.queryByTestId('cancel-btn')).toBeNull();
  });

  it('流中终态 cancelled → "已取消"', () => {
    const machine = stagedTurn([
      { event: 'stage', data: { stage: 'querying', label: 'x' } },
      { event: 'cancelled', data: { turn_id: 't1' } },
    ]);
    render(<MessageEntry entry={turnEntryWith(machine)} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByTestId('cancelled-text')).toBeInTheDocument();
  });

  it('rate_delta=null 单元格显示"不可比"（AC-13）', () => {
    render(<MessageEntry entry={{ kind: 'terminal', id: 'e', event: 'answer', payload: { ...answerBar, table: { columns: [{ field: 'channel', label: '渠道', format: 'text' }, { field: 'rate', label: '变化率', format: 'percent' }], rows: [{ channel: '渠道 C', rate: null }], truncated: false, display_limit: 500 } } }} lastQuestion="" handlers={handlers()} />);
    expect(screen.getByText('不可比')).toBeInTheDocument();
  });
});
