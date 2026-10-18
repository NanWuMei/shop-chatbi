import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SaveReportDialog from './index';
import { answerBar, httpErrorNameConflict, saveReportOk } from '../../../test/fixtures';
import { ApiError } from '../../../api/client';

vi.mock('../../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../../api/client')>('../../../api/client');
  return { ...actual, saveReport: vi.fn() };
});

import { saveReport } from '../../../api/client';
const saveReportMock = vi.mocked(saveReport);

function conflictError() {
  return new ApiError(
    409,
    httpErrorNameConflict.error.code,
    httpErrorNameConflict.error.message,
    false,
    httpErrorNameConflict.error.existing,
  );
}

describe('SaveReportDialog（FR-16/AC-19）', () => {
  it('标题预填问题、口径只读行、保存成功回调', async () => {
    const user = userEvent.setup();
    saveReportMock.mockResolvedValueOnce(saveReportOk);
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<SaveReportDialog open answer={answerBar} turnId="turn-0001" onClose={onClose} onSaved={onSaved} />);
    expect(screen.getByTestId('save-title-input')).toHaveValue('618 大促期间各渠道 GMV，按从高到低排');
    expect(screen.getByText(`口径：${answerBar.caliber.summary}`)).toBeInTheDocument();
    await user.click(screen.getByTestId('save-submit'));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith('618 大促期间各渠道 GMV，按从高到低排'));
    expect(saveReportMock).toHaveBeenCalledWith({ turn_id: 'turn-0001', title: '618 大促期间各渠道 GMV，按从高到低排', overwrite: undefined });
  });

  it('409 E_NAME_CONFLICT → 第二步：覆盖=overwrite=true 重发', async () => {
    const user = userEvent.setup();
    saveReportMock.mockRejectedValueOnce(conflictError());
    saveReportMock.mockResolvedValueOnce(saveReportOk);
    const onSaved = vi.fn();
    render(<SaveReportDialog open answer={answerBar} turnId="turn-0001" onClose={vi.fn()} onSaved={onSaved} />);
    await user.click(screen.getByTestId('save-submit'));
    await waitFor(() => expect(screen.getByTestId('name-conflict-step')).toBeInTheDocument());
    expect(screen.getByText(/已有同名报表《618 各渠道 GMV 排行》/)).toBeInTheDocument();
    await user.click(screen.getByTestId('conflict-overwrite'));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(saveReportMock).toHaveBeenLastCalledWith({ turn_id: 'turn-0001', title: '618 大促期间各渠道 GMV，按从高到低排', overwrite: true });
  });

  it('409 → 换个名字回到编辑', async () => {
    const user = userEvent.setup();
    saveReportMock.mockRejectedValueOnce(conflictError());
    render(<SaveReportDialog open answer={answerBar} turnId="turn-0001" onClose={vi.fn()} onSaved={vi.fn()} />);
    await user.click(screen.getByTestId('save-submit'));
    await waitFor(() => expect(screen.getByTestId('name-conflict-step')).toBeInTheDocument());
    await user.click(screen.getByTestId('conflict-rename'));
    expect(screen.getByTestId('save-title-input')).toBeInTheDocument();
  });

  it('409 → 取消关弹窗', async () => {
    const user = userEvent.setup();
    saveReportMock.mockRejectedValueOnce(conflictError());
    const onClose = vi.fn();
    render(<SaveReportDialog open answer={answerBar} turnId="turn-0001" onClose={onClose} onSaved={vi.fn()} />);
    await user.click(screen.getByTestId('save-submit'));
    await waitFor(() => expect(screen.getByTestId('name-conflict-step')).toBeInTheDocument());
    // AntD 对两字按钮自动插空格（"取 消"），用正则匹配
    await user.click(screen.getByRole('button', { name: /取\s?消/ }));
    expect(onClose).toHaveBeenCalled();
  });

  it('空标题不可保存', () => {
    render(<SaveReportDialog open answer={{ ...answerBar, question: '' }} turnId="t" onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByTestId('save-submit')).toBeDisabled();
  });
});
