# exam-prep

考试备考陪练 Skill（DSH）。用你给的材料建一个纯文本工作区，按掌握度出题、批改、分析错题、出周报，可选导出 Anki、可选把结果单向同步成 Obsidian 笔记。

- 升级自 `test_tutor@a25df33`（v1.4），按需重写；**不是**它的分支副本。
- 全部脚本纯 Python 标准库，不联网、不装依赖、每个脚本自带「Python 不可用时的降级步骤」。
- 没有 Obsidian / 没有 Anki / 没有 MCP 时，全部核心功能照常，且不提示你安装任何东西。

## 装在哪

```
~/.dsh/skills/exam-prep/          # 技能本体（可替换的安装件）
├── SKILL.md                      # 入口：路由、日常循环、周清单、边界
├── references/                   # 9 篇方法论（按需读，不要一次全读）
├── scripts/                      # 7 个标准库脚本
└── tests/                        # 自检（52 项）+ fixtures + goldens
```

运行时**数据不在这里**，在 `~/exam-prep/`（`EXAM_PREP_HOME` 可覆盖）：

```
~/exam-prep/
├── exams/<考试标识>/             # 六文件工作区 + INDEX.md + reports/
├── materials/{raw,processed}/    # 原始材料与转写件
└── obsidian_config.json          # 可选：Obsidian 绑定
                                  # 注意：全局配置仅保存 Vault 根路径。具体科目对应的子文件夹（如“大一上/微积分”）
                                  # 会分别记录在各自 exams/<考试标识>/learner_profile.json 中。
```

## 快速开始

```bash
# 1) 自检（不需要任何外部服务）
python ~/.dsh/skills/exam-prep/tests/run_smoke.py

# 2) 建工作区（在会话里说「帮我备考」，或手工搭目录骨架）
mkdir -p ~/exam-prep/exams/demo

# 3) 日常：校验 → 算掌握度 → 周报
python ~/.dsh/skills/exam-prep/scripts/validate_log.py      ~/exam-prep/exams/demo/answer_log.csv
python ~/.dsh/skills/exam-prep/scripts/mastery_calc.py      ~/exam-prep/exams/demo
python ~/.dsh/skills/exam-prep/scripts/weekly_report.py     ~/exam-prep/exams/demo

# 4) 留出集哈希（切完留出集立刻记，重测前校验）
python ~/.dsh/skills/exam-prep/scripts/verify_heldout.py --record ~/exam-prep/exams/demo/held_out.md
python ~/.dsh/skills/exam-prep/scripts/verify_heldout.py --verify ~/exam-prep/exams/demo/held_out.md

# 5) 可选：Anki 导出 / 调度回填
python ~/.dsh/skills/exam-prep/scripts/export_anki.py ~/exam-prep/exams/demo
python ~/.dsh/skills/exam-prep/scripts/export_anki.py ~/exam-prep/exams/demo --import-due due.csv --dry-run

# 6) 可选：Obsidian（bind 只需绑定一次 Vault 根目录，具体科目文件夹由建库时记录在工作区）
python ~/.dsh/skills/exam-prep/scripts/obsidian_sync.py bind --vault ~/Documents/MyVault
python ~/.dsh/skills/exam-prep/scripts/obsidian_sync.py doctor
# 同步时脚本会自动读取当前工作区 learner_profile.json 中的路径，无需手动指定 --write-dir
python ~/.dsh/skills/exam-prep/scripts/obsidian_sync.py push-errors --workspace ~/exam-prep/exams/demo
```

## 七条不可动的内核

1. 双入口分诊（有材料 / 从零），先确认考点表再建库。
2. 六文件工作区是唯一权威；没有第 7 个状态文件。
3. 练习层与测量层分离；留出集客观题路径零 LLM。
4. 留出集物理隔离 + SHA-256 锁。
5. 采分点命中式批改（三约束：不给总分、必须引原句、不评流畅度）。
6. CPKG 四类错因 + 三档信心 + 两条伪装漏洞规则。
7. 脚本确定性、纯标准库；≤60 分钟/周，无每日自动化。

v1.5 在此基础上加了三件事：**推理链优先**（答对但链不成立 = 疑似蒙对，不计入掌握度）、**溯源标签**（`[材料 X p.N]` / `[AI 补充]`）、**Anki 调度回填**（乘性折扣，无该列时输出逐字节不变）。

## 验证

`tests/run_smoke.py` 共 52 项，覆盖：契约校验、与蓝本的逐字节一致性（无新增列时）、推理链与 Anki 折扣的数值、周报三段的条件出现、Anki 回填只填空/跳过留出集/幂等、留出集哈希篡改检测、Obsidian 路径逃逸与降级、**按工作区隔离**（局部 `obsidian_write_dir` 生效 / 空值静默跳过 / 缺字段回退全局 / 不改全局配置），以及**权威边界测试**（改笔记不影响任何统计与哈希；重推恢复生成区、保留手写区）。

金标文件 `tests/golden/*` 由蓝本脚本生成，用于证明「没加新列时行为不变」。

## 边界

- 不做时间管理、情绪鼓励、学习计划表。
- 不替你拍板标注；不宣称「验证有效」（最终验证是真实考试）。
- 不自动联网、不安装、不注册；不读 Anki 数据库。Obsidian 同步按工作区隔离：没绑定、或建库时答「不需要」（`obsidian_write_dir` 为空）的科目，一律不碰 vault。
- 蓝本仓库未附 LICENSE（README 声明保留所有权利）。本技能为按需重写：机制与参数以本目录为唯一真源，不复制其受版权保护的表述。
