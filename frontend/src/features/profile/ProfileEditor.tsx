import { FilePenLine, LoaderCircle, Plus, Save, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type {
  PersonalInfo,
  PersonalField,
  ResumeDocument,
  ResumeSection,
  SectionEntry,
} from "../../shared/types";
import { newCustomField, siblings, toggleHiddenField } from "./document";
import { hasDefault, defaultLabel } from "./defaults";
import SectionEditor from "./SectionEditor";
import type { HonorSource } from "../../shared/types/honors";
import CustomFields from "./CustomFields";
import VisibilityField, { VisibilityButton } from "./VisibilityField";
import { samePersonalInfo } from "./comparison";

const FIELDS: {
  key: Exclude<PersonalField, "photo">;
  label: string;
  placeholder: string;
}[] = [
  { key: "name", label: "姓名", placeholder: "你的姓名" },
  { key: "job_title", label: "求职意向", placeholder: "如：Agent 开发工程师" },
  { key: "gender", label: "性别", placeholder: "选填" },
  { key: "age", label: "年龄", placeholder: "如：21" },
  { key: "phone", label: "电话", placeholder: "联系电话" },
  { key: "email", label: "邮箱", placeholder: "用于接收招聘信息" },
  {
    key: "gpa",
    label: "专业成绩",
    placeholder: "如：GPA 4.2 / 5 · 专业前 10%",
  },
  { key: "location", label: "所在地", placeholder: "如：杭州" },
  {
    key: "website",
    label: "个人主页",
    placeholder: "GitHub、作品集或个人网站",
  },
];

/** 读取并压缩上传照片，限制缓存体积，输出跨预览与 Word 共用的 JPEG。 */
async function readPhoto(file: File): Promise<string> {
  if (
    !["image/png", "image/jpeg"].includes(file.type) ||
    file.size > 10 * 1024 * 1024
  )
    throw new Error("请选择不超过 10 MB 的 PNG 或 JPEG 照片。");
  const bitmap = await createImageBitmap(file);
  try {
    const canvas = document.createElement("canvas");
    const cropWidth = Math.min(bitmap.width, bitmap.height * 0.75);
    const cropHeight = cropWidth / 0.75;
    const scale = Math.min(1, 300 / cropWidth);
    canvas.width = Math.max(1, Math.round(cropWidth * scale));
    canvas.height = Math.max(1, Math.round(cropHeight * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("浏览器暂时无法读取照片。");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(
      bitmap,
      (bitmap.width - cropWidth) / 2,
      (bitmap.height - cropHeight) / 2,
      cropWidth,
      cropHeight,
      0,
      0,
      canvas.width,
      canvas.height,
    );
    return canvas.toDataURL("image/jpeg", 0.88);
  } finally {
    bitmap.close();
  }
}

/** 编辑当前方案的顶部信息和各栏目资料，切换功能区后仍沿用同一份草稿。 */
export default function ProfileEditor({
  value,
  onChange,
  onStructure,
  onProjects,
  onHonors,
  onSortSection,
  savedPersonal,
  savedVersion,
  savedSections,
  onSaveEntry,
  onSave,
  honors,
  onEditHonor,
}: {
  value: ResumeDocument;
  onChange: (value: ResumeDocument) => void;
  onStructure: () => void;
  onProjects: () => void;
  onHonors: () => void;
  onSortSection: (sectionId: string) => void;
  savedPersonal?: PersonalInfo;
  savedVersion?: number;
  savedSections?: ResumeSection[];
  onSaveEntry: (sectionId: string, entryId: string) => Promise<void>;
  onSave: () => Promise<void>;
  honors: HonorSource[];
  onEditHonor: (id: string, sectionId: string, entry: SectionEntry) => void;
}) {
  const [editRequest, setEditRequest] = useState<{ version?: number } | null>(
    null,
  );
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const dirty = !samePersonalInfo(value.personal, savedPersonal);
  const editing =
    (editRequest !== null && editRequest.version === savedVersion) ||
    dirty ||
    !savedPersonal;
  const [photoError, setPhotoError] = useState("");
  const [photoBusy, setPhotoBusy] = useState(false);
  const latest = useRef(value);
  latest.current = value;
  const photoRequest = useRef(0);
  /** 仅更新个人字段显隐，隐藏时仍保留照片和文字原值。 */
  function togglePersonalField(field: PersonalField) {
    onChange({
      ...value,
      personal: {
        ...value.personal,
        hidden_fields: toggleHiddenField(value.personal.hidden_fields, field),
      },
    });
  }
  /** 确认保存成功后退出编辑；出错时保留输入，并在基本信息内显示原因。 */
  async function savePersonal() {
    if (saving || photoBusy) return;
    setSaving(true);
    setSaveError("");
    try {
      await onSave();
      setEditRequest(null);
    } catch (error) {
      setSaveError((error as Error).message);
    } finally {
      setSaving(false);
    }
  }
  useEffect(
    /* 切换方案或离开功能区后取消旧照片回调。 */ () => {
      return /* 使尚未完成的异步结果失效。 */ () => {
        photoRequest.current++;
      };
    },
    [],
  );
  /** 照片加载期间保留其他刚编辑的字段，最后一次上传或移除操作生效。 */
  async function uploadPhoto(file: File) {
    const serial = ++photoRequest.current;
    setPhotoBusy(true);
    setPhotoError("");
    try {
      const photo = await readPhoto(file);
      if (serial === photoRequest.current)
        onChange({
          ...latest.current,
          personal: { ...latest.current.personal, photo },
        });
    } catch (error) {
      if (serial === photoRequest.current)
        setPhotoError((error as Error).message);
    } finally {
      if (serial === photoRequest.current) setPhotoBusy(false);
    }
  }
  /** 更新单个栏目，保留同一方案中的基本信息与其他栏目。 */
  function updateSection(section: ResumeSection) {
    onChange({
      ...value,
      sections: value.sections.map(
        /* 按稳定标识替换编辑项。 */ (item) =>
          item.id === section.id ? section : item,
      ),
    });
  }
  const ordered = siblings(value.sections).flatMap(
    /* 子栏目紧跟所属大栏目。 */ (section) => [
      section,
      ...siblings(value.sections, section.id),
    ],
  );
  return (
    <>
      <header className="workspace-header profile-heading personal-heading">
        <div>
          <h1>个人信息</h1>
        </div>
        <button onClick={onStructure}>编排栏目</button>
      </header>
      <div className="workspace-scroll profile-scroll personal-scroll">
        <section
          className="profile-card"
          aria-labelledby="basic-info-title"
          data-guide="personal-basic"
          tabIndex={-1}
        >
          <div className="section-heading">
            <h2 id="basic-info-title">基本信息</h2>
            <span className="tag">固定在简历顶部</span>
          </div>
          <div className="photo-editor">
            {hasDefault(value.personal.field_definitions, "photo") &&
              (value.personal.photo ? (
                <img
                  src={value.personal.photo}
                  alt="简历证件照"
                  data-hidden={
                    value.personal.hidden_fields.includes("photo") || undefined
                  }
                />
              ) : (
                <div className="photo-placeholder">
                  <UserRound size={28} />
                  <span>证件照</span>
                </div>
              ))}
            {hasDefault(value.personal.field_definitions, "photo") && (
              <div className="photo-controls">
                <div className="photo-buttons">
                  <label
                    className="photo-upload"
                    aria-disabled={!editing || photoBusy || saving}
                  >
                    {photoBusy ? "正在处理照片…" : "上传照片"}
                    <input
                      aria-label="上传照片"
                      type="file"
                      accept="image/png,image/jpeg"
                      disabled={!editing || photoBusy || saving}
                      onChange={
                        /* 读取本次选择，不保留原始文件对象。 */ (event) => {
                          const file = event.target.files?.[0];
                          event.target.value = "";
                          if (file) void uploadPhoto(file);
                        }
                      }
                    />
                  </label>
                  {value.personal.photo && (
                    <button
                      className="text-button"
                      disabled={!editing || saving}
                      onClick={
                        /* 移除照片并使待处理上传失效。 */ () => {
                          photoRequest.current++;
                          setPhotoBusy(false);
                          onChange({
                            ...value,
                            personal: { ...value.personal, photo: "" },
                          });
                        }
                      }
                    >
                      移除照片
                    </button>
                  )}
                  <VisibilityButton
                    label="照片"
                    hidden={value.personal.hidden_fields.includes("photo")}
                    disabled={!editing || saving || photoBusy}
                    onToggle={
                      /* 照片显隐与移除照片分开，便于恢复。 */ () =>
                        togglePersonalField("photo")
                    }
                  />
                </div>
                {photoError && (
                  <p className="warning" role="alert">
                    {photoError}
                  </p>
                )}
              </div>
            )}
            <div className="personal-actions">
              <button
                disabled={editing || saving}
                aria-label="编辑基本信息"
                onClick={
                  /* 进入编辑并将焦点放到姓名输入。 */ () => {
                    setEditRequest({ version: savedVersion });
                    setSaveError("");
                    document.getElementById("personal-name")?.focus();
                  }
                }
              >
                <FilePenLine size={15} />
                编辑
              </button>
              <button
                className="primary"
                aria-label="保存基本信息"
                disabled={!editing || saving || photoBusy}
                onClick={savePersonal}
              >
                {saving ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Save size={15} />
                )}{" "}
                {saving ? "保存中…" : "保存"}
              </button>
              <button
                disabled={saving || value.personal.custom_fields.length >= 20}
                onClick={
                  /* 添加信息时直接进入编辑状态，并保留已有资料。 */ () => {
                    setEditRequest({ version: savedVersion });
                    setSaveError("");
                    onChange({
                      ...value,
                      personal: {
                        ...value.personal,
                        custom_fields: [
                          ...value.personal.custom_fields,
                          newCustomField(),
                        ],
                      },
                    });
                  }
                }
              >
                <Plus size={15} />
                添加信息
              </button>
            </div>
          </div>
          {saveError && (
            <p className="warning personal-save-error" role="alert">
              {saveError}
            </p>
          )}
          <div className="profile-fields personal-fields">
            {FIELDS.filter(
              /* 删除的内置项不再出现在填写表单。 */ (field) =>
                hasDefault(value.personal.field_definitions, field.key),
            ).map(
              /* 将基本信息字段映射到对应输入。 */ (field) => (
                <VisibilityField
                  key={field.key}
                  id={`personal-${field.key}`}
                  label={defaultLabel(
                    value.personal.field_definitions,
                    field.key,
                    field.label,
                  )}
                  hidden={value.personal.hidden_fields.includes(field.key)}
                  disabled={!editing || saving}
                  onToggle={
                    /* 编辑时切换当前字段在简历中的显隐。 */ () =>
                      togglePersonalField(field.key)
                  }
                >
                  <input
                    id={`personal-${field.key}`}
                    readOnly={!editing || saving}
                    value={value.personal[field.key]}
                    placeholder={editing ? field.placeholder : "未填写"}
                    maxLength={
                      field.key === "website"
                        ? 500
                        : field.key === "age" || field.key === "gender"
                          ? 30
                          : 100
                    }
                    onChange={
                      /* 只修改当前字段。 */ (event) =>
                        onChange({
                          ...value,
                          personal: {
                            ...value.personal,
                            [field.key]: event.target.value,
                          },
                        })
                    }
                  />
                </VisibilityField>
              ),
            )}
            <CustomFields
              fields={value.personal.custom_fields}
              definitions={value.personal.field_definitions}
              scope="基本信息"
              editing={editing}
              disabled={saving}
              onChange={
                /* 自定义信息与固定基本信息使用同一保存流程。 */ (
                  custom_fields,
                ) =>
                  onChange({
                    ...value,
                    personal: { ...value.personal, custom_fields },
                  })
              }
            />
          </div>
        </section>
        <div className="section-heading profile-section-intro">
          <h2>简历栏目资料</h2>
          <button className="text-button" onClick={onStructure}>
            <Plus size={14} />
            自定义栏目与层级
          </button>
        </div>
        {ordered.map(
          /* 按简历排版顺序展示栏目资料编辑器。 */ (section) =>
            section.kind === "projects" ? (
              <section
                className="profile-card project-shortcut"
                key={section.id}
              >
                <div>
                  <h2>{section.title}</h2>
                  <p className="subtle">
                    在项目经历工作台整理内容、管理版本和 AI 会话。
                  </p>
                </div>
                <button onClick={onProjects}>进入项目工作台</button>
              </section>
            ) : (
              <SectionEditor
                onHonors={onHonors}
                onSort={onSortSection}
                honors={honors}
                onEditHonor={onEditHonor}
                key={section.id}
                section={section}
                savedSection={savedSections?.find(
                  /* 定位本栏目已保存的各条资料。 */ (item) =>
                    item.id === section.id,
                )}
                savedVersion={savedVersion}
                onSaveEntry={onSaveEntry}
                parent={value.sections.find(
                  /* 定位所属大栏目用于说明层级。 */ (item) =>
                    item.id === section.parent_id,
                )}
                onChange={updateSection}
              />
            ),
        )}
      </div>
    </>
  );
}
