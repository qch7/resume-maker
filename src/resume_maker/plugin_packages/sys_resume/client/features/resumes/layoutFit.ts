import type { PageLayout } from "@resume-maker/plugin-sdk/shared/resume/pageLayout";

export interface LayoutFitResult {
  status: "fit" | "unchanged" | "unfit" | "unavailable";
  options: PageLayout;
  pages: number | null;
  attempts: number;
  preview: unknown;
  message: string;
}
export interface LayoutFitTicket {
  identity: string;
  controller: AbortController;
}

/** 只接受当前请求对当前完整输入的实测结果，取消后即使服务返回也不发布 */
export function currentFitResult(
  ticket: LayoutFitTicket,
  current: LayoutFitTicket | null,
  identity: string,
): boolean {
  return (
    ticket === current &&
    ticket.identity === identity &&
    !ticket.controller.signal.aborted
  );
}

/** 后端明确报告达标且实测页数符合当前预算时才允许回填 */
export function fitResultSucceeded(
  result: LayoutFitResult,
  target: number,
): boolean {
  return (
    (result.status === "fit" || result.status === "unchanged") &&
    result.pages !== null &&
    result.pages > 0 &&
    result.pages <= target
  );
}
