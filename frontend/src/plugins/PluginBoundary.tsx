import { Component, type ReactNode } from "react";

/** 单个扩展视图失败时保留工作台和现有草稿 */
export default class PluginBoundary extends Component<
  { owner: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  /** React 捕获组件异常后只替换当前贡献 */
  static getDerivedStateFromError() {
    return { failed: true };
  }
  /** 错误提示不打印插件可能包含的资料正文 */
  render() {
    return this.state.failed ? (
      <p role="alert">
        {this.props.owner} 的界面暂不可用，已保存的资料和草稿仍保留。
      </p>
    ) : (
      this.props.children
    );
  }
}
