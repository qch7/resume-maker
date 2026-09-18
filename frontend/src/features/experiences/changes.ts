import type {
  Experience,
  Highlight,
  Meta,
  ProjectVisibility,
} from "../../shared/types/index.ts";
import { experienceContent } from "./visibility.ts";

/** 只比较单字段与正式版本的实际内容，其他字段草稿不会让当前字段误报待提交。 */
export function fieldChanged(
  value: unknown,
  base: Experience,
  field: string,
  settings: ProjectVisibility = {},
) {
  if (field === "meta")
    return (
      experienceContent(
        { ...base, ...(value as Meta), highlights: [] },
        settings,
      ) !== experienceContent({ ...base, highlights: [] }, settings)
    );
  if (field === "order")
    return (
      JSON.stringify(value) !==
      JSON.stringify(
        base.highlights.map(
          /* 提取正式版本中的亮点顺序。 */ (point) => point.id,
        ),
      )
    );
  const original = base.highlights.find(
    /* 找到该亮点的正式内容。 */ (point) => point.id === field.slice(10),
  );
  return JSON.stringify(value ?? null) !== JSON.stringify(original ?? null);
}

/** 正文恢复原文时恢复匹配引用的核实状态，避免自动失效标记制造虚假改动。 */
export function editHighlightText(
  value: Highlight,
  text: string,
  base?: Highlight,
): Highlight {
  return {
    ...value,
    text,
    evidence: value.evidence.map(
      /* 只恢复同一引用，新增或修改的证据仍需核实。 */ (evidence) => {
        const { status: _status, ...source } = evidence;
        const original =
          text === base?.text
            ? base.evidence.find(
                /* 不同对象属性顺序不影响同一证据的识别。 */ (item) =>
                  Object.entries(source).every(
                    /* 保留文件、行号和原文均一致的引用状态。 */ ([
                      key,
                      content,
                    ]) => item[key as keyof typeof item] === content,
                  ),
              )
            : undefined;
        return { ...evidence, status: original?.status ?? "unverified" };
      },
    ),
  };
}
