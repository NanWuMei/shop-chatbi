/**
 * 存为报表弹窗（F16/F17）：标题预填问题、口径行只读、chart 缩略（null 不渲染缩略）、
 * 409 → NameConflictStep（覆盖=overwrite=true 重发 / 换名字 / 取消）、成功关弹窗
 * ＋消息流 note "已存为报表：《名称》"。表/口径进入只读快照（E_REPORT_NOT_SAVEABLE 仅为兜底）。
 */
import { Input, Modal, Skeleton } from 'antd';
import { useEffect, useState } from 'react';
import { ApiError, saveReport } from '../../../api/client';
import type { AnswerEvent } from '../../../api/types';
import ChartView from '../ResultCard/ChartView';
import NameConflictStep from './NameConflictStep';

export default function SaveReportDialog({
  open,
  answer,
  turnId,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean;
  answer: AnswerEvent;
  turnId: string;
  onClose: () => void;
  onSaved: (title: string) => void;
  onError?: (message: string) => void;
}) {
  const [title, setTitle] = useState('');
  const [conflict, setConflict] = useState<{ id: string; title: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setTitle(answer.question.length > 50 ? answer.question.slice(0, 50) : answer.question);
      setConflict(null);
    }
  }, [open, answer.question]);

  const submit = async (overwrite: boolean) => {
    setSubmitting(true);
    try {
      await saveReport({ turn_id: turnId, title: title.trim(), overwrite: overwrite || undefined });
      setSubmitting(false);
      setConflict(null);
      onSaved(title.trim());
      onClose();
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError && err.code === 'E_NAME_CONFLICT' && err.existing) {
        setConflict(err.existing); // 第二步：覆盖/换名/取消（AC-19）
        return;
      }
      // E_REPORT_NOT_SAVEABLE 等兜底：toast 错误信封 business 文案（AC-19）
      const message = err instanceof Error ? err.message : '保存失败，请重试';
      onError?.(message);
    }
  };

  return (
    <Modal
      open={open}
      title="存为报表"
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      data-testid="save-report-dialog"
    >
      {conflict !== null ? (
        <NameConflictStep
          existing={conflict}
          onOverwrite={() => submit(true)}
          onRename={() => setConflict(null)}
          onCancel={onClose}
        />
      ) : (
        <div className="save-dialog">
          <Input
            value={title}
            placeholder="报表名称"
            onChange={(e) => setTitle(e.target.value)}
            maxLength={60}
            data-testid="save-title-input"
          />
          <div className="save-dialog__caliber">口径：{answer.caliber.summary}</div>
          {answer.chart !== null ? (
            <ChartView chart={answer.chart} rows={answer.table.rows} onChartFailed={() => undefined} />
          ) : (
            <Skeleton.Node active={false} style={{ width: '100%', height: 80 }} data-testid="no-chart-thumb" />
          )}
          <button
            type="button"
            className="save-dialog__submit"
            disabled={title.trim() === '' || submitting}
            onClick={() => submit(false)}
            data-testid="save-submit"
          >
            保存
          </button>
        </div>
      )}
    </Modal>
  );
}
