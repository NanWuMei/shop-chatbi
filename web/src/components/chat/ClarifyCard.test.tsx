import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ClarifyCard from './ClarifyCard';
import { clarifySingleChoice, clarifyTimeQuick, clarifyQuestionSuggestions } from '../../test/fixtures';

describe('ClarifyCard 三控件（AC-10/FR-11/F20）', () => {
  it('single_choice：选后确认并查询可用，未选置灰', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ClarifyCard payload={clarifySingleChoice} onConfirm={onConfirm} onCancel={vi.fn()} onAskQuestion={vi.fn()} />);
    expect(screen.getByTestId('clarify-confirm')).toBeDisabled();
    await user.click(screen.getByText('美妆个护（一级类目）'));
    await user.click(screen.getByTestId('clarify-confirm'));
    expect(onConfirm).toHaveBeenCalledWith({ type: 'option', value: 'beauty_personal_care' });
  });

  it('single_choice：换问法 → custom 提交', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ClarifyCard payload={clarifySingleChoice} onConfirm={onConfirm} onCancel={vi.fn()} onAskQuestion={vi.fn()} />);
    await user.click(screen.getByText('我换个问法'));
    await user.type(screen.getByTestId('clarify-custom-input'), '618 美妆个护 GMV 排行');
    await user.click(screen.getByText('提交问法'));
    expect(onConfirm).toHaveBeenCalledWith({ type: 'custom', value: '618 美妆个护 GMV 排行' });
  });

  it('time_quick：快捷预设 → time_preset', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ClarifyCard payload={clarifyTimeQuick} onConfirm={onConfirm} onCancel={vi.fn()} onAskQuestion={vi.fn()} />);
    await user.click(screen.getByText('本期大促'));
    await user.click(screen.getByTestId('clarify-confirm'));
    expect(onConfirm).toHaveBeenCalledWith({ type: 'time_preset', value: 'current_promo' });
  });

  it('time_quick：自定义时间范围 → time_preset {start,end}', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ClarifyCard payload={clarifyTimeQuick} onConfirm={onConfirm} onCancel={vi.fn()} onAskQuestion={vi.fn()} />);
    await user.click(screen.getByText('自定义'));
    await user.click(screen.getByTestId('clarify-confirm'));
    expect(onConfirm).toHaveBeenCalledWith({ type: 'time_preset', value: { start: '', end: '' } });
  });

  it('question_suggestions：点选即发问，无确认按钮', async () => {
    const user = userEvent.setup();
    const onAskQuestion = vi.fn();
    render(<ClarifyCard payload={clarifyQuestionSuggestions} onConfirm={vi.fn()} onCancel={vi.fn()} onAskQuestion={onAskQuestion} />);
    expect(screen.queryByTestId('clarify-confirm')).toBeNull();
    await user.click(screen.getByText('618 大促期间各渠道 GMV 是多少，按从高到低排'));
    expect(onAskQuestion).toHaveBeenCalledWith('618 大促期间各渠道 GMV 是多少，按从高到低排');
  });

  it('取消：只调 onCancel，不发任何请求语义（无确认）', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ClarifyCard payload={clarifySingleChoice} onConfirm={vi.fn()} onCancel={onCancel} onAskQuestion={vi.fn()} />);
    await user.click(screen.getByTestId('clarify-cancel'));
    expect(onCancel).toHaveBeenCalledWith('clarify-0001');
  });

  it('round 展示服务端值', () => {
    render(<ClarifyCard payload={clarifyQuestionSuggestions} onConfirm={vi.fn()} onCancel={vi.fn()} onAskQuestion={vi.fn()} />);
    expect(screen.getByTestId('clarify-round')).toHaveTextContent('澄清轮次 2/2');
  });

  it('历史还原 confirmed/cancelled：静态呈现不可交互', () => {
    render(
      <ClarifyCard
        payload={{ ...clarifySingleChoice, status: 'cancelled' }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        onAskQuestion={vi.fn()}
      />,
    );
    expect(screen.getByTestId('clarify-card-static')).toHaveTextContent('已取消澄清');
  });
});
