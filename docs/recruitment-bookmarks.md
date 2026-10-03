# 招聘收藏夹

初始没有领域、分类或网址。支持自行添加，或导入 JSON 文件。分类名称和数量都可自定义；“大厂、中厂、小厂”仅存在于示例文件中。

## 测试导入

1. 保存单独提供的互联网 JSON 文件，打开“招聘收藏夹”。
2. 点击“导入”，拖入或选择 JSON 文件。空收藏夹应预览：新增 30 条、1 个领域、3 个分类。
3. 确认后出现互联网领域；“全部网站”显示大厂 20 条、中厂 10 条、小厂 0 条，选择互联网领域时仅显示有网址的大厂、中厂。
4. 重复导入应跳过 30 条。
5. 在“管理分类”或领域“管理”中新增、改名或删除分组。也可直接添加不分组的网址。
6. “导出全部”包含全部分组、网址、备注、星标和原始顺序，不受筛选、视图及显示排序影响。

| 文件 | 内容 |
| --- | --- |
| [互联网清单](../src/resume_maker/resources/recruitment/internet.bookmarks.json) | 互联网领域；大厂、中厂、小厂；30 家企业 |
| [科技企业清单](../src/resume_maker/resources/recruitment/technology.bookmarks.json) | 科技领域；大厂、中厂、小厂；6 家企业 |
| [JSON Schema](recruitment-bookmarks.schema.json) | v1 文件校验结构 |

企业和链接来自 [原始清单](recruitment-navigation-proposal.md)，保留 2026-09-26 的核验备注，本次开发未重新逐一核验。企业归类可修改，小厂未预填企业。

两份清单单独提供，页面不展示文件入口。

## 文件格式

UTF-8 JSON，扩展名建议为 `.bookmarks.json`。空文件结构：

```json
{
  "format": "resume-maker.recruitment-bookmarks",
  "schema_version": 1,
  "domains": [],
  "categories": [],
  "bookmarks": []
}
```

自定义示例：

```json
{
  "format": "resume-maker.recruitment-bookmarks",
  "schema_version": 1,
  "domains": [{ "id": "software", "name": "软件服务" }],
  "categories": [{ "id": "priority", "name": "优先投递" }],
  "bookmarks": [{
    "id": "my-company",
    "name": "示例公司",
    "domain_id": "software",
    "category": "priority",
    "description": "",
    "tags": ["后端"],
    "notes": "示例地址，请替换",
    "favorite": false,
    "links": [{ "label": "招聘", "url": "https://example.com/careers" }]
  }]
}
```

| 字段 | 规则 |
| --- | --- |
| `format`、`schema_version` | 固定为上方格式名和数字 `1` |
| `domains`、`categories` | 各 0–100 个；组内 ID 和名称唯一，名称忽略大小写 |
| `bookmarks` | 0–3000 条，ID 唯一，数组顺序作为默认顺序，展示时星标优先 |
| `id` | 1–100 个英文字母、数字、下划线、点、冒号或连字符 |
| `domain_id`、`category` | 可省略或为空字符串；非空时须引用本文件对应分组的 ID |
| `name`、链接 `label` | 必填，去除前后空白后 1–100 字符 |
| `description`、`notes` | 可选，默认空串；分别最多 2000、10000 字符 |
| `tags` | 可选，最多 30 个非空标签，每个最多 100 字符 |
| `favorite` | 可选，默认 `false` |
| `links` | 1–30 个，须为有效 HTTP/HTTPS 网页地址，不允许账号密码或控制字符 |

单次导入上限 8 MB。非法字段、重复 ID、无效引用或合并后超限均整份拒绝。

## 合并和保存

“全部网站”展示全部分类，包括尚无网址的分类；选择某个领域后，仅展示该领域网址使用的分类；“星标”仅展示星标网址使用的分类。搜索只影响结果和计数，不改变范围内的分类列表。切换范围、删除条目或取消星标后，已选分类若不再可用，会自动回到“全部”。

支持卡片和列表视图。星标条目始终排在普通条目前，两组内部可选默认顺序、字母升序或字母降序；默认采用 JSON 数组顺序，中文名称按拼音排序。切换排序不会改写数据或导出顺序，取消星标后重新按所选规则排列。视图和排序偏好自动保存在本机，随 ZIP 备份恢复，不写入网址 JSON。

领域和分类分别先按 ID、再按名称匹配，复用本机分组并保留本机名称；未匹配的分组追加。收藏仅按 ID 去重。“工作台设置 → 招聘收藏夹”可更改重复项处理方式，修改后自动保存：默认保留本机内容，选择更新时采用文件中该条目的全部字段。原有其他条目及顺序保留，新条目按文件顺序追加。

每次导入窗口读取已保存的规则，预览和确认始终使用同一规则。偏好跨重启保留并随 ZIP 备份，不写入网址 JSON。导入支持拖放或点击选择单个文件；多文件、非 JSON、超出 8 MB 或空文件会被拒绝。

导入先预览再确认。其他窗口修改后，过期操作会被拒绝，刷新后可重试。删除分组时可迁移收藏，也可清除归属。表单需点击保存，关闭时可放弃修改，未保存表单不跨浏览器重启恢复。

数据存于 SQLite `settings` 表的 `recruitment-bookmarks` 项，随 ZIP 备份恢复。JSON 包含个人备注，分享前自行检查。
