/**
 * 过程状态（FR-7）：三阶段固定文案与图标态（✓/转圈/灰），随 stage 点亮、同段去重；
 * 「取消」调 cancel 接口；cancelled 帧后由消息渲染器替换静态"已取消"（本组件不渲染半成品卡）。
 */
import { Button, Spin } from 'antd';
import { CheckCircleFilled, LoadingOutlined, MinusCircleOutlined } from '@ant-design/icons';
import { STAGES, type Stage } from '../../api/types';
import type { TurnMachineState } from '../../api/sse';

const LABELS: Record<Stage, string> = {
  understanding: '正在理解问题',
  checking_caliber: '正在核对口径',
  querying: '正在取数',
};

export default function ProcessStatus({
  machine,
  connectionLost,
  onCancel,
}: {
  machine: TurnMachineState;
  connectionLost: boolean;
  onCancel: () => void;
}) {
  if (connectionLost) {
    return (
      <div className="process-status process-status--lost" data-testid="connection-lost">
        连接中断，重试
      </div>
    );
  }

  const running = machine.phase === 'streaming' || machine.phase === 'idle';

  return (
    <div className="process-status" data-testid="process-status">
      {STAGES.map((stage) => {
        const status = machine.stageStatuses[stage];
        return (
          <div key={stage} className={`process-status__row process-status__row--${status}`} data-testid={`stage-${stage}`}>
            {status === 'done' && <CheckCircleFilled className="process-status__icon-done" />}
            {status === 'running' && <LoadingOutlined spin />}
            {status === 'pending' && <MinusCircleOutlined className="process-status__icon-pending" />}
            <span>{LABELS[stage]}</span>
            {status === 'running' && <Spin size="small" />}
          </div>
        );
      })}
      {running && (
        <Button size="small" onClick={onCancel} data-testid="cancel-btn">
          取消
        </Button>
      )}
    </div>
  );
}
