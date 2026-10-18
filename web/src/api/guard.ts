/**
 * 穷尽性分发工具：联合类型新增成员时编译期报错（NFR-1 / AC-1 / F3）。
 * 用法：switch 内 default 分支调用 assertNever(x)，漏分支即编译失败。
 */
export function assertNever(value: never, message = '未穷尽联合类型分支'): never {
  throw new Error(`${message}: ${JSON.stringify(value)}`);
}
