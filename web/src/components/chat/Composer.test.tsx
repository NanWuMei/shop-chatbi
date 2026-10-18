import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Composer from './Composer';
import { useChatStore } from '../../store/chatStore';

function reset() {
  useChatStore.setState({ sessionId: null, entries: [], draft: '', active: false, closeStream: null });
}

describe('Composer（AC-3/FR-4）', () => {
  it('空内容发送置灰', () => {
    reset();
    render(<Composer onSend={vi.fn()} />);
    expect(screen.getByTestId('composer-send')).toBeDisabled();
  });

  it('输入后可发送、发送后清空草稿', async () => {
    reset();
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    await user.type(screen.getByTestId('composer-input'), '618 大促各渠道 GMV');
    expect(screen.getByTestId('composer-send')).toBeEnabled();
    await user.click(screen.getByTestId('composer-send'));
    expect(onSend).toHaveBeenCalledWith('618 大促各渠道 GMV');
    expect(useChatStore.getState().draft).toBe('');
  });

  it('回车发送、Shift+回车换行（不发送）', async () => {
    reset();
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const input = screen.getByTestId('composer-input');
    await user.type(input, '第一行');
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    expect(onSend).not.toHaveBeenCalled();
    await user.keyboard('{Enter}');
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('超 500 字置灰并显示固定提示、不触发发送', async () => {
    reset();
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const input = screen.getByTestId('composer-input');
    await user.type(input, '好'.repeat(501));
    expect(screen.getByTestId('composer-send')).toBeDisabled();
    expect(screen.getByTestId('composer-tip')).toHaveTextContent('问题过长，请缩短或拆分');
    await user.click(screen.getByTestId('composer-send'));
    expect(onSend).not.toHaveBeenCalled();
  });

  it('草稿存于 store（跨路由保活载体）', async () => {
    reset();
    const user = userEvent.setup();
    render(<Composer onSend={vi.fn()} />);
    await user.type(screen.getByTestId('composer-input'), '草稿内容');
    expect(useChatStore.getState().draft).toBe('草稿内容');
  });
});
