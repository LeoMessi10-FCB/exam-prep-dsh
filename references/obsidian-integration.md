# Obsidian 集成（obsidian-integration）：单向派生，六文件仍是唯一权威

> 载荷点：v1.5 新增。默认**不启用**；未绑定 vault 时全文不生效，技能行为与无 Obsidian 时逐字节一致。
> 本文是集成细节的唯一真源（模板字段、配置字段、脚本子命令、失败模式）；
> `SKILL.md` 第 9 节只保留「何时触发 / 何时回退」二至三行，不复制本文内容。

## 0. 定位：为什么是「派生视图」而不是「笔记库」

六文件工作区是唯一权威状态；vault 只是它的**渲染层**。这条不因集成而改变：

- 笔记里的任何内容——改字段、删行、加手写段——都**不改变**掌握度、不改 `answer_log.csv`、不进留出集哈希。因为笔记是生成物，权威数据只存在于工作区。
- 笔记里的数字**不做二次计算**：周报原文照抄、缺口变化照抄、错题条目照抄。脚本从不「读笔记重新聚合」。
- 唯一的方向是**工作区 → vault**。vault 里的手写内容不会被回填进工作区（唯一例外是你自己在会话里贴回来，那属于你的输入）。

一句话裁决规则：**权威数据只能从工作区流向 vault；任何反向流动都必须由你显式发起，且不经过脚本。**

## 1. 读什么、写什么：三区划分

| 区 | 归属 | 技能行为 |
|---|---|---|
| 写入区（默认 `<vault>/ExamPrep/`） | 技能的渲染产物 | 前台生成区由脚本覆写；`## 备注` 手写区永久保留 |
| 只读源（如 `Courses/` 讲义、`Archive/` 真题转写） | 你的原始资料 | 出题时可读取、引用、双链；**只读，不改一字** |
| 用户主权区（如 `Journal/`、`Inbox/`） | 你的日常笔记 | **绝不读写**，即使落在写入区内 |

- 平铺 vault（笔记全在根目录、没有 `Courses/` 这种分区）不要硬造分区：直接在配置里把只读源留空，出题材料靠**会话内粘贴**或 `materials/` 里的转写件；写入区仍然建 `ExamPrep/` 一个目录。
- 写入区之外一律不读不写，除了 `bind` 时检查 `.obsidian/` 是否存在（那是 vault 判据，不涉及内容）。
- 目录区分只在需要「只读源」时才有意义；不需要就全部走会话粘贴——粘贴路径不打任何折扣。

## 2. 三张模板（frontmatter 由 `obsidian_sync.py` 生成，你不用手写）

### 2.1 错题笔记 `ExamPrep/errors/<考试>/<模块>.md`

**按模块聚合，不按题聚合**——`answer_log.csv` 已经是行级真源，一题一条会在几百条错题后变成垃圾场。

| 字段 | 类型 | 取值 | 用途 |
|---|---|---|---|
| `type` | text | `exam_error` | 三类笔记统一判别 |
| `exam` | text | 考试标识 | 跨考试过滤 |
| `topic` | text | 模块名（与日志逐字一致） | 回连 `syllabus_table.csv` |
| `cpkg_type` | list | `K`/`C`/`P`/`G`/`无` | 错因分布 |
| `confidence` | list | `稳`/`不确定`/`蒙`/`未标` | 高置信度错误观测 |
| `source` | list | `[材料 X p.N]` / `[[笔记#标题]]` | 溯源 |
| `workdir_ref` | text | `exams/<id>/answer_log.csv`（相对 `EXAM_PREP_HOME`） | 指回权威数据 |
| `holdout` | bool | 恒 `false` | 显式声明：笔记永不收留出集内容 |
| `anki_due` | bool | 该模块是否有 `未过` | 单向展示调度信号 |
| `anki_relearn` | bool | 该模块是否有 `重学` | 同上 |
| `generated_at` | date | `YYYY-MM-DD` | 派生时间（只到日，保证幂等） |
| `tags` | list | `exam-prep`、`<exam>` | 检索 |

正文结构固定：`漏洞概览`（条数、错因分布、信心分布、疑似蒙对、Anki 调度）→ `错题条目`（七列表）→ `变式要求`（按 CPKG 与疑似蒙对生成）→ 生成区结束 → `## 备注`（你的手写区）。

### 2.2 概念笔记 `ExamPrep/concepts/<考试>/<模块>.md`

| 字段 | 类型 | 取值 |
|---|---|---|
| `type` | text | `exam_concept` |
| `exam` / `syllabus_module` | text | 考试标识 / 模块名 |
| `mastery_at_creation` | number | 讲授当时的掌握度（数值，可空） |
| `linked_errors` | list | `[[ExamPrep/errors/<exam>/<模块>]]`（存在同名错题笔记时才有） |
| `source` | list | `[材料 …]` 或 `[AI 补充]` |
| `workdir_ref` | text | `exams/<id>/syllabus_table.csv` |
| `generated_at` / `tags` | date / list | 同上，`tags` 追加 `concept` |

正文五节＝讲授三件套的映射：`## 场景` / `## 块 1` / `## 块 2` / `## 块 3` / `## 标准表述` / `## 自测`（见 `teaching_pipeline.md` §8）。重复讲授同一模块**覆写同一条笔记**，不新建 `-2`。

### 2.3 周复盘笔记 `ExamPrep/reviews/<考试>/<YYYY-Www>.md`

| 字段 | 类型 | 取值 |
|---|---|---|
| `type` | text | `exam_review` |
| `exam` / `week` | text | 考试标识 / `2026-W45` |
| `workdir_ref` | text | `exams/<id>` |
| `generated_at` / `tags` | date / list | `tags` 追加 `review` |

正文：`## 当周周报（原文，未重算）`（代码块内照抄 `weekly_report.py` 输出）+ `## 缺口变化（摘自 gap_matrix，未重算）`。**脚本不重算任何数字**；周报改口径时笔记自然跟着变，因为原文来自脚本输出。

## 3. 权威边界：谁说了算

### 3.1 三条硬规则

1. **生成区覆盖、手写区保留**：`%% exam-prep:generated:start … %%` 与 `…:end %%` 之间每次重推完全覆写；区间外（含 `## 备注`）逐字节保留。
2. **用户手改的处置**：改生成区 → 下次重推被覆盖（这是设计，不是 bug）；改 frontmatter → 同样被重写；想长期留的内容写进 `## 备注` 或区块外。
3. **冲突裁决**：笔记与工作区不一致时，**永远以工作区为准**，动作是重推（`push-errors`），不是手改笔记。`obsidian_sync.py check` 只读核对条目数，发现不一致就提示重推。

### 3.2 与 Anki 的边界（防重复系统）

两种「复习调度」不能打架：

- **错题笔记不导出 Anki**。Anki 是「错题重做」的调度器，错题笔记是「错因聚合」的观察面——同一批错题既进 Anki 又进笔记没问题，但把笔记再导出成卡牌会造出两套间隔重复。
- 未来的去重键是 `exam|date|模块|题型`（card fingerprint），**本轮未实现**；显式记在这里，以免下一轮有人凭感觉加导出。
- 方向仍是单向：`anki状态`（未过/重学）从 Anki → 工作区（`export_anki.py --import-due`），vault 只读这个结果（`anki_due` / `anki_relearn`）。

### 3.3 留出集禁区

vault 里任何位置都不许出现留出集题目、答案、关键步骤清单。`obsidian_sync.py` 对 `held_out*` 路径直接拒绝写入；`push-*` 只读 `answer_log.csv` 与 `syllabus_table.csv`，**从不打开 `held_out.md`**。冲突场景：若你手写过同名笔记，脚本会报 WARN 并跳过，不会合并。

## 4. 两条实现路径：默认 B，可选 A

| | B：stdlib 脚本（默认） | A：Obsidian MCP（可选） |
|---|---|---|
| 依赖 | 无（Python 标准库） | 需装 MCP server + Obsidian 正在运行 + Local REST API 插件 |
| 写入范围 | 进程内 `realpath` 校验，锁死写入区 | 由 server 的路径允许列表约束 |
| 潮汐/关闭 Obsidian | 照常工作 | 失败（`obsidian_unreachable`） |
| 语义理解（链走到哪、错因怎么归类） | 不做，只搬运 | 可做，但要额外提示词与纪律 |
| 失败模式 | 明确的退出码与 WARN | 网络错误、插件未开、端口占用 |

**默认走 B 的理由**：v1.5 的 Obsidian 需求是「把已算好的结果写成可读笔记」，这是**确定性搬运**，没有任何一环需要模型理解。B 路径零依赖、可重跑、可审计；A 路径在 Obsidian 未运行时直接失效，而备考场景里「轮到写笔记时 Obsidian 没开」是常态。

**升级条件**（满足任一再考虑 A，并且只在 `references/obsidian-integration.md` 里记，不进 SKILL.md 正文）：

1. vault 在沙箱可写范围之外，且你不愿挪动它；
2. 需要跨 >10k 条笔记做 BM25 语义检索（`mode: "omnisearch"`）；
3. 需要并发编辑检测 / Obsidian 原生撤销栈。

### 4.1 三个候选实现（真源链接 + 行号）

| 实现 | 关键事实 | 是否满足写入区约束 |
|---|---|---|
| `MarkusPfundstein/mcp-obsidian`（[README](https://github.com/MarkusPfundstein/mcp-obsidian) L3、L11–L17） | 基于 Local REST API 插件；工具集为 `list_files_in_vault` / `list_files_in_dir` / `get_file_contents` / `search` / `patch_content` / `append_content` / `delete_file`；无目录允许列表 | **不满足**：只有 vault 级隔离，写入区靠提示词自觉 |
| `bitbonsai/mcpvault`（[README](https://github.com/bitbonsai/mcpvault) L7、L111、L142） | 直接读写 vault 文件；操作限制在配置的 vault 根；保留未改动字段的 frontmatter；阻断 `..` 穿越、符号链接逃逸、点文件、`.obsidian`、`.git`、`node_modules` | 部分满足：根级隔离强，但**没有「只写 ExamPrep/」的子目录允许列表** |
| `cyanheads/obsidian-mcp-server`（[README](https://github.com/cyanheads/obsidian-mcp-server) L253–L256、L275–L276、L237–L238） | `OBSIDIAN_READ_PATHS` / `OBSIDIAN_WRITE_PATHS` / `OBSIDIAN_DENY_PATHS` 三组逗号分隔目录允许/拒绝表，`OBSIDIAN_READ_ONLY` 可全禁写；拒绝表覆盖允许表；示例 `OBSIDIAN_READ_PATHS=public/` + `OBSIDIAN_WRITE_PATHS=public/inbox/` | **满足**：可精确表达「读 `Courses/`、写 `ExamPrep/`、禁 `Journal/`」 |

结论：若将来走 A，选 `cyanheads/obsidian-mcp-server`，配置为 `OBSIDIAN_READ_PATHS=Courses/,ExamPrep/` + `OBSIDIAN_WRITE_PATHS=ExamPrep/` + `OBSIDIAN_DENY_PATHS=Journal/`（按你的实际目录替换），并要求 Obsidian 开着、Local REST API 插件 v4.0.0+ 已启用（[README](https://github.com/cyanheads/obsidian-mcp-server) L237）。**注意**：三个实现里只有它对「写入区」有目录级表达力，另两个只能靠 vault 根隔离。

## 5. 配置与命令

配置文件：`<EXAM_PREP_HOME>/obsidian_config.json`（默认 `~/exam-prep/obsidian_config.json`），**不进工作区**（它不是第 7 个状态文件，删掉它技能照常跑到只有六文件的状态）。

```json
{
  "version": 1,
  "enabled": true,
  "vault_path": "/Users/you/Documents/MyVault",
  "write_dir": "ExamPrep",
  "readonly_sources": ["Courses", "Archive"],
  "deny": ["Journal", "Inbox"],
  "bound_at": "2026-11-02"
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `vault_path` | string | 必须含 `.obsidian/`；不填则视为未绑定 |
| `write_dir` | string | 全局**默认/回退**写入区（老工作区用）。**v1.5.1 起不再由它决定单场考试的路径**——见下方「按工作区隔离」 |
| `obsidian_write_dir`（局部） | string | 写在 `<工作区>/learner_profile.json`，按考试隔离；空串 = 本场不同步 |

### 5.1 按工作区隔离（v1.5.1）

- 建库时问一次「是否需要同步、要写到 Vault 的哪个文件夹」，答案写进**工作区**的 `learner_profile.json`：`{"obsidian_write_dir": "大一上/微积分"}`；答「不需要」写 `""`。
- 解析优先级：`--write-dir`（命令行）> 工作区 `obsidian_write_dir` > 全局 `write_dir`。
- 字段**不存在**（老工作区）→ 回退全局；字段**存在但为空** → 本次考试全部同步静默跳过（退出码 3）。
- 局部路径同样受约束：必须是 vault 内相对路径，绝对路径或 `../` 一律退出码 2；解析后仍须 strict 位于 vault 之下。
- **任何同步命令都不写全局配置**：全局只在 `bind` 时写一次，之后保持字节不变。
| `readonly_sources` | list | 只读源目录；出题引用时可读 |
| `deny` | list | 用户主权区；永不读写 |
| `enabled` | bool | `false` = 静默跳过（不提示用户去装 Obsidian） |

命令（每次调用都是一次性进程，不需要守护进程）：

```bash
python <skill>/scripts/obsidian_sync.py bind --vault <vault> [--write-dir ExamPrep] [--source Courses] [--deny Journal]
python <skill>/scripts/obsidian_sync.py doctor [--fix] [--workspace <工作区>]
python <skill>/scripts/obsidian_sync.py push-errors  --workspace ~/exam-prep/exams/<id> --exam <id> --write-dir "大一上/微积分" [--dry-run]
python <skill>/scripts/obsidian_sync.py push-concept --workspace ~/exam-prep/exams/<id> --exam <id> --write-dir "大一上/微积分" --module <模块> --from <讲授正文.md> [--source "[材料 讲义 p.3]"] [--dry-run]
python <skill>/scripts/obsidian_sync.py push-review  --workspace ~/exam-prep/exams/<id> --exam <id> --write-dir "大一上/微积分" --week 2026-W45 --report <weekly.txt> [--gap-diff <diff.md>] [--dry-run]
python <skill>/scripts/obsidian_sync.py check        --workspace ~/exam-prep/exams/<id> --exam <id> --write-dir "大一上/微积分"
```

- `--write-dir` 可省略：省略时脚本读工作区的 `obsidian_write_dir`；再没有才回退全局 `write_dir`。但 AI 调用时应当**显式带上**它，避免你把路径记错时静默写错地方。
- **首次写入前必须显式确认一次**：建库时那句询问就是确认；`bind` 是 vault 级的一次性动作，脚本不做二次询问；`--dry-run` 可先看写什么。
- 退出码：`0` 成功；`1` 校验失败（路径逃逸、条目不一致）；`2` 参数/配置错误；`3` vault 不可用 → **调用方静默降级**，不提示用户安装任何东西。
- 幂等：同输入同日重跑逐字节一致；不同日只变 `generated_at`。

## 6. 每周习惯（≤1 分钟）

1. 周末跑一次 `push-errors`（一个模块一条笔记，几秒钟）。
2. 讲完一个模块顺手 `push-concept`（正文就是刚讲的三件套，已在会话里生成）。
3. 周报出来后 `push-review` 一次。
4. 想核对「笔记有没有跟丢日志」就跑 `check`——它只读，不改任何文件。

不写日报、不做每日推送、不设 cron。**没有自动同步**：同步事件只在你说「同步到 Obsidian」或周末例行时发生一次。

## 7. 失败模式与不可逆清单

| 现象 | 处置 |
|---|---|
| vault 不存在 / 无 `.obsidian/` | `bind` 拒绝（退出码 2）；把 `vault_path` 指到 vault 根，不是子目录 |
| 写入区不存在 | `doctor --fix` 创建；或直接 `push-*`（脚本自动建目录） |
| 双链无法解析 | WARN 列出 `[[…]]`；在 vault 里补笔记，或把溯源改成 `[材料 …]` 纯文本 |
| 笔记与日志条目数不一致 | `check` 退出码 1 → 重推 `push-errors`（以日志为准覆盖生成区） |
| 打开 Obsidian 后笔记没变 | 写入发生在文件层，Obsidian 会自行检测外部修改；若未刷新，切到别的笔记再切回 |
| vault 在沙箱外写不进 | 脚本退出码非 0；这是沙箱策略，不是技能缺陷——把 vault 挪进可写范围，或改用 A 路径 |

**不可逆清单**（脚本自身也不做这些，故不提供命令）：删除笔记、重命名笔记、移动笔记、改 `deny` 区内容、把笔记内容回填工作区、把留出集写进 vault。这里没有「撤销」，靠 Obsidian 自己的文件历史与系统备份。

## 8. 与其他文件的衔接

- `SKILL.md`：第 9 节「触发与回退」二至三行；不复制本文任何字段表。
- `scripts/obsidian_sync.py`：本文 §2 模板、§5 命令的执行体；退出码语义见 §5。
- `teaching_pipeline.md` §8：讲授三件套 → 概念笔记五节的映射。
- `anki_scheduling.md` §8：`anki_due` / `anki_relearn` 的单向展示口径。
- `measurement_guide.md` §10：留出集禁入 vault 的硬约束。
- `error_taxonomy.md`：`cpkg_type` / `confidence` 的枚举值来源。
- `item_writing_guide.md` §3：`source` 字段的三种合法形态。
