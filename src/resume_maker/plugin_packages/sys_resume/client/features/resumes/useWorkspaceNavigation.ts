import { useEffect, useRef, useState } from "react";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";
import { flushDrafts } from "@resume-maker/plugin-sdk/shared/lib/draftRegistry";
import { readWorkspaceSession, saveWorkspaceSession } from "./workspaceSession";
import type {
  Revision,
  State,
} from "@resume-maker/plugin-sdk/shared/types/index";
import {
  DEFAULT_LOCATION,
  normalizeWorkspaceLocation,
  readWorkspaceLocation,
  workspaceUrl,
  type WorkspaceArea,
  type WorkspaceLocation,
} from "./workspaceLocation";

interface Options {
  loaded: boolean;
  location: WorkspaceLocation;
  state: State;
  areas: WorkspaceArea[];
  pages: string[];
  chatAvailable: boolean;
  defaultProjectId: string;
  blocked: () => boolean;
  onRestore: (location: WorkspaceLocation) => void;
  notify: (message: { text: string; error?: boolean }) => void;
}

/** 地址记录主要导航，前进后退先保存草稿，失效引用回到有效工作区 */
export function useWorkspaceNavigation(options: Options) {
  const current = useRef(options);
  current.current = options;
  const [ready, setReady] = useState(false);
  const initialized = useRef(false);
  const serial = useRef(0);
  const restoring = useRef(false);
  const index = useRef<number>(
    Number.isInteger(history.state?.resumeWorkspace?.index)
      ? history.state.resumeWorkspace.index
      : 0,
  );
  const last = useRef("");
  const href = useRef(window.location.href);
  const reverting = useRef(false);
  const signature = JSON.stringify(options.location);

  /** 历史修订需核对项目归属，删除或失效时采用该项目最新版本 */
  async function resolve(requested: WorkspaceLocation) {
    const value = current.current;
    const normalized = normalizeWorkspaceLocation(
      requested,
      value.state,
      value.areas,
      value.pages,
      value.chatAvailable,
      value.defaultProjectId,
    );
    const project = value.state.projects.find(
      (item) => item.id === normalized.projectId,
    );
    if (
      project &&
      normalized.revisionId !== project.head_revision &&
      !value.state.branches.some(
        (branch) =>
          branch.project_id === project.id &&
          branch.head_revision === normalized.revisionId,
      )
    ) {
      try {
        const revision = await api<Revision>(
          `/revisions/${encodeURIComponent(normalized.revisionId)}`,
        );
        if (revision.project_id !== project.id)
          normalized.revisionId = project.head_revision;
      } catch {
        normalized.revisionId = project.head_revision;
      }
    }
    return normalized;
  }

  useEffect(() => {
    if (!options.loaded || initialized.current) return;
    initialized.current = true;
    const request = ++serial.current;
    void resolve(
      readWorkspaceLocation(
        window.location.href,
        readWorkspaceSession("navigation", DEFAULT_LOCATION),
      ),
    ).then((location) => {
      if (request !== serial.current) return;
      current.current.onRestore(location);
      last.current = JSON.stringify(location);
      setReady(true);
    });
  }, [options.loaded]);

  useEffect(() => {
    if (!ready || restoring.current) return;
    const initial = !history.state?.resumeWorkspace;
    if (!initial && last.current !== signature) index.current++;
    const url = workspaceUrl(window.location.href, options.location);
    const state = {
      ...history.state,
      resumeWorkspace: { index: index.current },
    };
    if (initial || last.current === signature)
      history.replaceState(state, "", url);
    else history.pushState(state, "", url);
    href.current = window.location.href;
    last.current = signature;
    saveWorkspaceSession("navigation", options.location);
  }, [ready, signature]);

  useEffect(() => {
    if (!ready) return;
    /** 拒绝导航时恢复原历史位置，保留可用的前进、后退记录 */
    function revert(targetIndex: number) {
      const offset = index.current - targetIndex;
      if (offset) {
        reverting.current = true;
        history.go(offset);
      } else history.replaceState(history.state, "", href.current);
    }
    /** 仅采用最后一次前进后退，迟到解析不能覆盖新的导航 */
    async function pop(event: PopStateEvent) {
      if (reverting.current) {
        reverting.current = false;
        return;
      }
      const request = ++serial.current;
      const targetIndex = event.state?.resumeWorkspace?.index ?? index.current;
      const requested = readWorkspaceLocation(
        window.location.href,
        DEFAULT_LOCATION,
      );
      restoring.current = true;
      try {
        if (current.current.blocked())
          throw new Error("经历正在保存，请完成后再切换工作区。");
        const location = await resolve(requested);
        await flushDrafts();
        if (request !== serial.current) return;
        if (current.current.blocked())
          throw new Error("经历正在保存，请完成后再切换工作区。");
        index.current = targetIndex;
        last.current = JSON.stringify(location);
        href.current = new URL(
          workspaceUrl(window.location.href, location),
          window.location.href,
        ).href;
        current.current.onRestore(location);
      } catch (error) {
        if (request !== serial.current) return;
        revert(targetIndex);
        current.current.notify({ text: (error as Error).message, error: true });
      } finally {
        if (request === serial.current) restoring.current = false;
      }
    }
    /** 浏览器事件交给异步草稿屏障处理 */
    const listener = (event: PopStateEvent) => void pop(event);
    window.addEventListener("popstate", listener);
    return () => {
      ++serial.current;
      window.removeEventListener("popstate", listener);
    };
  }, [ready]);

  return ready;
}
