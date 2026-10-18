import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockEventSource } from '../test/MockEventSource';
import { answerBar, sessionMessages } from '../test/fixtures';
import { useChatStore } from './chatStore';

/** 拦截 client 模块：fetch 层不真实发生 */
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    startTurn: vi.fn(),
    cancelTurn: vi.fn().mockResolvedValue({ turn_id: 't1', status: 'cancelling' }),
    getMessages: vi.fn(),
    getHealth: vi.fn().mockResolvedValue({ status: 'ok', checks: { db: 'ok', llm: 'ok', embedding: 'unconfigured' } }),
  };
});

import { cancelTurn, getMessages, startTurn } from '../api/client';

const startTurnMock = vi.mocked(startTurn);
const cancelTurnMock = vi.mocked(cancelTurn);
const getMessagesMock = vi.mocked(getMessages);

beforeEach(() => {
  MockEventSource.install();
  useChatStore.setState({ sessionId: null, entries: [], draft: '', active: false, closeStream: null });
  startTurnMock.mockReset();
  cancelTurnMock.mockClear();
  getMessagesMock.mockReset();
});

afterEach(() => {
  useChatStore.getState().closeStreamNow();
  MockEventSource.uninstall();
});

function settleTurn(turnId: string, sessionId: string) {
  startTurnMock.mockResolvedValueOnce({ turn_id: turnId, session_id: sessionId, status: 'running' });
}

describe('chatStore 问数流（FR-4~10）', () => {
  it('ask：乐观渲染用户气泡 → POST 202 → 建 turn 条目 → stage/answer 帧驱动', async () => {
    settleTurn('turn-0001', 'session-0001');
    useChatStore.getState().ask('618 各渠道 GMV');
    await vi.waitFor(() => expect(useChatStore.getState().entries[1]?.kind).toBe('turn'));
    const es = MockEventSource.last!;
    es.dispatch('stage', { stage: 'understanding', label: '正在理解问题' }, '1');
    es.dispatch('answer', answerBar, '2');
    const entries = useChatStore.getState().entries;
    expect(entries[0]).toMatchObject({ kind: 'user', question: '618 各渠道 GMV' });
    expect(entries[1].kind).toBe('turn');
    const machine = (entries[1] as { machine: { terminal: unknown } }).machine;
    expect(machine.terminal).not.toBeNull();
  });

  it('ask：POST 失败 → 解锁互斥 + onError', async () => {
    startTurnMock.mockRejectedValueOnce(new Error('大模型服务暂不可用，请稍后重试'));
    const onError = vi.fn();
    useChatStore.getState().ask('问题', { onError });
    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('大模型服务暂不可用，请稍后重试'));
    expect(useChatStore.getState().active).toBe(false);
  });

  it('done 帧后解锁互斥（可追问）', async () => {
    settleTurn('turn-0001', 'session-0001');
    useChatStore.getState().ask('问题1');
    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy());
    const es = MockEventSource.last!;
    es.dispatch('stage', { stage: 'querying', label: 'x' }, '1');
    es.dispatch('answer', answerBar, '2');
    es.dispatch('done', { turn_id: 'turn-0001' }, '3');
    await vi.waitFor(() => expect(useChatStore.getState().active).toBe(false));
    settleTurn('turn-0002', 'session-0001');
    useChatStore.getState().ask('问题2');
    await vi.waitFor(() => expect(startTurnMock).toHaveBeenCalledTimes(2));
  });

  it('active 互斥：进行中再 ask 不发第二个 POST', () => {
    settleTurn('turn-0001', 'session-0001');
    useChatStore.getState().ask('问题1');
    useChatStore.getState().ask('问题2');
    expect(startTurnMock).toHaveBeenCalledTimes(1);
  });

  it('cancelActiveTurn：调 cancel 接口（FR-7）', async () => {
    settleTurn('turn-0001', 'session-0001');
    useChatStore.getState().ask('问题');
    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy());
    useChatStore.getState().cancelActiveTurn();
    await vi.waitFor(() => expect(cancelTurnMock).toHaveBeenCalledWith('turn-0001'));
  });

  it('onLost → connectionLost 条目标记（AC-6 降级态）', async () => {
    settleTurn('turn-0001', 'session-0001');
    useChatStore.getState().ask('问题');
    await vi.waitFor(() => expect(MockEventSource.last).toBeTruthy());
    const es = MockEventSource.last!;
    es.dispatch('error', undefined, '1');
    es.dispatch('error', undefined, '1');
    await vi.waitFor(() => {
      const entry = useChatStore.getState().entries.find((e) => e.kind === 'turn');
      expect(entry && entry.kind === 'turn' && entry.connectionLost).toBe(true);
    });
  });

  it('confirmClarify：POST 202 成功后澄清卡就地收起（confirmed）', async () => {
    settleTurn('turn-0002', 'session-0001');
    const payload = { clarify_id: 'clarify-0001', round: 1, title: 't', reason_code: 'METRIC_DIM_AMBIGUOUS' as const, input_type: 'single_choice' as const, options: [], suggestions: [], allow_custom_text: true, status: 'pending' as const };
    useChatStore.setState({
      entries: [{ kind: 'terminal', id: 'e-clar', event: 'clarification', payload }],
    });
    useChatStore.getState().confirmClarify(payload, { type: 'option', value: 'beauty_personal_care' });
    await vi.waitFor(() => expect(startTurnMock).toHaveBeenCalledTimes(1));
    const body = startTurnMock.mock.calls[0][0];
    expect(body.clarify).toEqual({ clarify_id: 'clarify-0001', selection: { type: 'option', value: 'beauty_personal_care' } });
    const entry = useChatStore.getState().entries[0];
    expect((entry as { payload: { status: string } }).payload.status).toBe('confirmed');
  });

  it('cancelClarify：就地收起不发请求（FR-11）', () => {
    useChatStore.setState({
      entries: [
        { kind: 'terminal', id: 'e-clar', event: 'clarification', payload: { clarify_id: 'c1', round: 1, title: 't', reason_code: 'VAGUE', input_type: 'question_suggestions', options: [], suggestions: [], allow_custom_text: true, status: 'pending' } },
      ],
    });
    useChatStore.getState().cancelClarify('c1');
    expect(startTurnMock).not.toHaveBeenCalled();
    const entry = useChatStore.getState().entries[0];
    expect((entry as { payload: { status: string } }).payload.status).toBe('cancelled');
  });

  it('loadSession：五类消息 → 同一渲染器形状（AC-18）', async () => {
    getMessagesMock.mockResolvedValueOnce(sessionMessages);
    await useChatStore.getState().loadSession('session-0001');
    const entries = useChatStore.getState().entries;
    expect(entries.map((e) => e.kind)).toEqual([
      'user', 'terminal', 'terminal', 'user', 'terminal', 'user', 'terminal', 'note',
    ]);
    expect(useChatStore.getState().sessionId).toBe('session-0001');
  });
});
