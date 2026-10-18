/** 409 E_NAME_CONFLICT 步骤：覆盖 / 换个名字 / 取消（SDD §3.5 弹窗第二步）。 */
import { Alert, Button, Space } from 'antd';

export default function NameConflictStep({
  existing,
  onOverwrite,
  onRename,
  onCancel,
}: {
  existing: { id: string; title: string };
  onOverwrite: () => void;
  onRename: () => void;
  onCancel: () => void;
}) {
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="name-conflict-step">
      <Alert type="warning" showIcon message={`已有同名报表《${existing.title}》，是否覆盖？`} />
      <Space>
        <Button type="primary" danger onClick={onOverwrite} data-testid="conflict-overwrite">
          覆盖
        </Button>
        <Button onClick={onRename} data-testid="conflict-rename">
          换个名字
        </Button>
        <Button onClick={onCancel}>取消</Button>
      </Space>
    </Space>
  );
}
