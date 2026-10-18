/** ⑤ 操作区：存为报表（置灰规则见 saveable.ts）＋「口径不对，重新澄清」（SDD §3 区5）。 */
import { Button, Tooltip } from 'antd';
import { saveDisabledReason } from './saveable';

export default function Actions({
  terminal,
  saveable,
  chartFailed,
  clarifyStatus,
  turnId,
  onSave,
  onRecalibrate,
}: {
  terminal: Parameters<typeof saveDisabledReason>[0]['terminal'];
  saveable: boolean;
  chartFailed: boolean;
  clarifyStatus?: 'pending' | 'confirmed' | 'cancelled';
  /** 重新澄清的 source_turn_id；缺省（报表查看页）不显示该入口 */
  turnId?: string;
  onSave: () => void;
  onRecalibrate?: (sourceTurnId: string) => void;
}) {
  const guard = saveDisabledReason({ terminal, saveable, chartFailed, clarifyStatus });
  return (
    <div className="result-card__actions" data-testid="result-actions">
      <Tooltip title={guard.tooltip || undefined}>
        <Button type="primary" ghost disabled={guard.disabled} onClick={onSave}>
          存为报表
        </Button>
      </Tooltip>
      {turnId !== undefined && onRecalibrate !== undefined && (
        <Button onClick={() => onRecalibrate(turnId)} data-testid="recalibrate-btn">
          口径不对，重新澄清
        </Button>
      )}
    </div>
  );
}
