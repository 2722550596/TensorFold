# 审查：self-mode.md 对照 需求原话.md

审查对象：`docs/design/self-mode.md`（486 行，未实现设计稿）。对照：`docs/design/需求原话.md`。
审查方式：只读。逐条核对设计引用的 `file:line`（共约 120 处）、工作区 `git diff`、`~/projects/qwen/train-docs/elias/001-identity-core.md` 内容。未修改任何源码或设计文档。
判定：**不通过（设计需先修订再进入实现）**。下列 B 级为阻塞项。

---

## 0. 结论摘要

| 级别 | 编号 | 问题 |
|---|---|---|
| 阻塞 | B1 | 设计声称 user/document 行为“逐字节不变”、`toModel`/`addressed`/`firstPerson` “不改”，但工作区未提交改动已改写这三者，并已改变中文 user/document 路径。设计未承认。 |
| 阻塞 | B2 | 效果清单 4（不相关对话污染）无门槛，验收条款自相矛盾（“N 全部通过”，而 N5 仅“记录”），该效果无法被证伪。 |
| 主要 | M1 | 效果清单 3“中文文档可教”没有文档级验收，§6.2 只测一句话。 |
| 主要 | M2 | 效果清单 2 列了“经历、外貌”，验收只测生日与身份。 |
| 主要 | M3 | 设计把“人格泄漏是用户原意：这是特性”写成事实，需求原话却标明前序原话已丢失、待明月复核。 |
| 主要 | M4 | 孪生事实的依据“任务说明要求中英都可用”在仓库中不存在；需求原话未提英文提问。该机制显著增加耗时与口袋占用。 |
| 主要 | M5 | §1 “同一输入逐字节同路径” 与 §5 “曾跑过 self 课之后 user 课行为改变” 互相矛盾。 |
| 次要 | m1–m8 | 见 §5。 |

已核实正确的部分：需求原话 `:5 :7 :12 :17–20 :26–28` 行号引用全部正确；设计中大多数 `file:line` 引用与代码相符（见 §3）；§6.1 中 `001-identity-core.md` 的 “1月15日 / 28岁 / Elias Thorne” 与 “北京” 不存在的断言与语料一致。

---

## 1. 需求审计（否决权）

需求原文（`需求原话.md`）只有两句原话和四条效果清单。逐条：

| 需求 | 设计覆盖 | 验收覆盖 | 判定 |
|---|---|---|---|
| 原话 1/2：在 Living Weights 内补“模型自我认知”层；fork、不跟上游 | §1、§3.0、§8 | — | 符合。全链路 `document: bool → About` 属需求允许的 clean cutover。 |
| 效果 1：问“你是谁/你叫什么”答角色本人（第一人称） | §3.2 `self_prompts`、§3.4 `selfVoiced`、§3.6 keep 冲突 | §6.2 步骤 2 I1–I3 | 覆盖。 |
| 效果 2：问角色自身事实（生日、**经历**、**外貌**……）以第一人称答出 | §3.1–§3.3 | §6.2 仅 P1–P3（生日） | **未验收**，见 M2。 |
| 效果 3：中文文档可教 | §3.1 `selfFacts` 分块、`selfGrounded`、中文 `toSelf` | §6.2 仅一句话 `"我1月15日生。"` | **未验收文档级**，见 M1。 |
| 效果 4：不相关对话不被污染，门槛待定【推断，待明月确认】 | §3.7 泄漏判定、§3.5 镜像负例 | §6.2 N1–N5；N5 仅“记录”；§6.2 末段“N 全部通过即验收通过” | **不可证伪**，见 B2。 |
| 解法：`keep_prompts` 每课不变需改 | §3.6 | §6.2 I6 | 覆盖。 |
| 解法：`firstPerson()` 无“我/我的”，需补 | 声称已补（`slide_whom.zig:52-55`，未提交） | §6.1 | 已补，但见 B1：补法同时改了 user 路径。 |

---

## 2. 阻塞项

### B1 — 设计的“user/document 不变”不变式已被工作区改动打破，设计未承认

证据：

- `git diff zig/src/server/slide_whom.zig` 显示未提交改动包含：
  - `firstPerson`（`slide_whom.zig:52-56`）新增“我/咱”为第一人称、“你的/您的”为听者、并计数“你”；
  - `toModel`（`slide_whom.zig:60-64`）新增 `你/您` 字符匹配分支；
  - `addressed`（`slide_whom.zig:93-98`）新增 `我→你` 全局替换。
- 设计 §4 表格写明：`toModel`（`:60-64`）、`addressed`（`:67-106`）、`firstPerson`（`:39-57`）**不改**；§3.3 写“刻意不复用 `toModel()`…改它会改变 user 模式行为”；§1 写“self 模式不改动 user/document 两种模式的行为（同一输入逐字节同路径）”。以上三句与工作区不符。
- 改动的影响面已在 user/document 路径上生效（不是假设）：
  - `slide.zig:111`：`document = !chat or !firstPerson(fact)`。改动前，任何含“我”的中文 chat 事实 `firstPerson` 为假，被当作 **document**；改动后变为 **user**，`giveWay`（`slide.zig:112`）开始运行。这是 user 模式的可观察变化。
  - `slide_found.zig:41`：`reversed()` 跳过 `firstPerson` 为真的事实；中文第一人称事实现在被跳过。
  - `slide_take.zig:101`、`slide_lesson.zig:468`：中文问题不再因 `!firstPerson` 被判为“非用户自问”而丢弃。
  - `slide_lesson.zig:443`、`slide_route.zig:22`：`addressed()` 对中文问题返回非空，近邻负例与路由负例由此新增。
- 结论：设计所依赖的“现有测试原样通过 ⇒ user 不变”论证（§6.1 末段）只覆盖测试用例，不覆盖已改变的生产路径。设计需要：(a) 把这次改动单列为 user 模式行为变更并给出理由；或 (b) 把中文人称改动拆出、单独验证，再让 self 依赖它。

阻塞原因：设计明文要求 user/document 逐字节不变（§1、§3.0、§5），其前提已经不成立，且设计没有说明。

### B2 — 效果 4 不可证伪，验收条款自相矛盾

- 需求 `需求原话.md:20`：“不相关对话不被角色设定污染程度可接受（待定量门槛）。【推断，待明月确认】”。
- 设计 §8 承认“定量门槛仍待明月确认”，但没有提出临时门槛、也没有标注为待定的验收阈值。
- §6.2 末段：“全部 P/I 通过、N 全部通过即验收通过”。但 N5（“How old are you?”）在表中为“记录”，N3/N4 仅为定性。N1 只要求“不含 1月15”，对“污染”的定义不足以判定。
- 结果：无论实验结果如何，验收都可以被解释为通过或失败。

需要：要么由明月给出门槛（回写到需求原话），要么设计给出一个标注 **[推断]** 的临时门槛（例如：N 集 N 次采样中污染率上限），并把 N5 从“记录”改为判定项。

---

## 3. 主要问题

### M1 — 效果 3“中文文档可教”没有文档级验收

- §6.2 只教 `"我1月15日生。"` 一句（步骤 1）与 `"我是埃利亚斯·索恩(Elias Thorne)。"` 一句（步骤 2）。
- 需求原文是“中文**文档**可教”。文档路径特有的逻辑——`find()` 分块（`slide_found.zig:14,23`）、多事实、`selfFacts` 的 `chunk_chars`、以及中英孪生在多事实下的 `siblingAnswers` 行为——全部没有验收。
- §7.11 把全量 34 篇列为“数小时”，未进入验收。
- 语料可用：`~/projects/qwen/train-docs/elias/001-identity-core.md` 存在且含 “1月15日生,今年28岁” 与 “Elias Thorne”（已核对）。设计应把它（或其一段）列入 §6.2，并给出可判定的 P/I 问题。

### M2 — 效果 2 的“经历、外貌”未验收

- 效果 2 原文列了“生日、经历、外貌……”。§6.2 的 P 集只有生日。
- 需要至少一条经历问题（如 `001-identity-core.md` 中的“1月15日生，今年28岁”之外的事实，如“我以前是奇点无限的创始人兼CEO”）与一条外貌问题（`003-identity-appearance.md`），并列入 P 集。

### M3 — “人格泄漏是用户原意：这是特性”是未标注的推断

- 设计 §1：“允许角色人格‘泄漏’到普通对话（用户原意：这是特性）”。
- 需求原话：前序原话未保留，`需求原话.md:11` 明确写“以下为秋青子转述，需明月复核”；效果 4 标注【推断，待明月确认】。
- 设计把一个尚未确认、且与效果 4 直接冲突的判断当作用户意图，并据此放宽泄漏判定（§3.7 “说自己则放行”）。
- 需要：删除“用户原意”措辞，改为 **[推断]**，并把“放行”行为列为待明月确认项。

### M4 — 孪生事实的依据不存在，且扩大了范围

- §3.1 第 3 点与 §8 效果 3 行写“中英孪生使英文问法也可答（任务说明要求中英都可用）”。
- 仓库内无“任务说明”文档（在 TensorFold 仓库内检索，该词只出现在 self-mode.md 自身；需求原话.md 也未提及）。`需求原话.md` 未要求英文提问。
- 孪生机制带来：每事实双倍学习时间（§7.11）、双倍口袋占用（§7.1）、新增 `twinGrounded`、`Found` 结构改造、`siblingAnswers` 去孪生（§3.3）。这些成本由一个不存在的需求支撑。
- 需要：要么把“英文提问”列为需求（回写需求原话、由明月确认），要么删去孪生机制。

### M5 — §1 与 §5 关于 user 不变的表述相互矛盾

- §1：“逐字节同路径”。
- §5 末段：“曾跑过 self 课之后，`refreshSelf` 把英文 keep 中问模型的缓存答案更新为人格答案，后续 user 课据此保持人格”。
- 这是一个真实的、会持续存在的 user 模式变化（只要服务器跑过一次 self 课）。设计应把 §1 的措辞改为“从未跑过 self 课的服务器上逐字节不变”，并把该变化列入效果 4 的风险（它直接是“不相关对话被污染”的一种）。

---

## 4. 逐引用核查（设计 file:line 与代码的对照）

以下为本次核对结果。“符合”表示行号与语义均与代码一致。

| 设计引用 | 实际 | 结论 |
|---|---|---|
| `slide_take.zig:101-105` 个人/用户自问过滤 | `:101-105` 为 `personal`、`if (personal or ...)`、日志 | 符合 |
| `slide_lesson.zig:468-469` | `:468` personal、`:469` why | 符合 |
| `slide_lesson.zig:443` near miss `addressed` | `:443` | 符合 |
| `slide_route.zig:22` | `:22` `addressed` | 符合 |
| `slide_prompts.zig:13-16` keep 4 条 | `:13-16` | 符合 |
| `slide_lesson.zig:142-149` keep 循环 `!toModel` | `:142-146` | 符合 |
| `slide_prompts.zig:228` told_note | `:228` | 符合 |
| `slide_prompts.zig:254` told_judge | `:254` | 符合 |
| `slide_take.zig:242-246` judged | `:242-246` | 符合 |
| `slide_take.zig:107` 系统提示 | `:107` | 符合（为 `write` 中 note，`:107-108`） |
| `slide_lesson.zig:493` note | `:493` | 符合 |
| `slide_verify.zig:107` knowing 的 note | `:107` | 符合 |
| `slide_found.zig:17-25` facts | `:17-25` | 符合 |
| `slide_found.zig:41` firstPerson 跳过 reverse | `:41` | 符合 |
| `slide_found.zig:85-88` 无示例重问 | `:85-88` | 符合 |
| `slide_found.zig:97`、`:111` words/restates | `:97`、`:111` | 符合 |
| `slide_found.zig:14` chunk_chars | `:14` | 符合 |
| `slide_words.zig:198-214` grounded | `:198-214` | 符合 |
| `slide_words.zig:14-20` 再导出 | `:14-20` | 符合 |
| `slide_units.zig:162-164` sameScript | `:162-164` | 符合 |
| `slide_language.zig:14,18,24,27` | `:14` questions_other，`:18` besides_other，`:24` translate，`:27` languageOf | 符合 |
| `slide_take.zig:176-204` siblingAnswers | `:176-204` | 符合 |
| `slide_take.zig:201` judged in siblings | `:201` | 符合 |
| `slide_take.zig:115,123,132` | `:115` 答案截取结束、`:123` shortAnswer、`:132` thinkingAnswer | 符合 |
| `slide_think.zig:20-21`、`:64,67` | `:20-21`、`:64`、`:67` | 符合 |
| `slide_lesson.zig:312,319,326,327` | 符合 | 符合 |
| `slide_lesson.zig:329` naming 仅 document | `:329` | 符合 |
| `slide_lesson.zig:331-350` 补问，`:347` 用 `questionsFor` | `:347` 为 `else questionsFor(...)` | 符合 |
| `slide_lesson.zig:352-360`、`:364`、`:419-421`、`:425,443-447`、`:468-474`、`:493`、`:497`、`:525`、`:543-547`、`:556-559`、`:588-593` | 均核对 | 符合 |
| `slide_lesson.zig:402-407` systems/turns | `:405-406` | 符合 |
| `slide_lesson.zig:89` Plan 含 `document` | `:89` | 符合 |
| `slide_lesson.zig:216` Parts.document | `:216` | 符合 |
| `slide_lesson.zig:151` replay | `:151` | 符合 |
| `slide_lesson.zig:169` 本地 keep | `:169` | 符合 |
| `slide_lesson.zig:263-264` | `:263-264` | 符合 |
| `slide_lesson.zig:186-195` router | `:186-195` | 符合 |
| `slide_lesson.zig:314` aboutEntity；`:582-585` | 符合 | 符合 |
| `slide_subject.zig:148-160` wordIn | `:148-160` | 符合 |
| `slide_pick.zig:43-59` dice | `:43-59` | 符合 |
| `slide_teacher.zig:85-96` refresh；`:99,108-116` Local；`:123-137` keepExamples | 均核对 | 符合 |
| `slide_teacher.zig:96` 后新增 refreshSelf | 见 m3 | 符合（位置） |
| `slide_verify.zig:76-85` 泄漏；`:106-110` knowing；`:121-124` brings | `brings` 在 `:121-124`；`recallsShort` 在 `slide_words`，设计写法略有歧义 | 基本符合（见 m5） |
| `slide_untold.zig:6-13` checked | `:6-13` | 符合 |
| `slide_replace.zig:37` judged(...,false) | `:37` | 符合 |
| `slide.zig:66` learn；`:75` text required；`:76` source | `:66`、`:75`、`:76` | 符合 |
| `slide.zig:90` found.facts；`:98` add；`:111-113` document/gave；`:127` refresh；`:130` remember | 均核对 | 符合 |
| `slide.zig:112,243-258` giveWay；`:174-181` reroute | 均核对 | 符合 |
| `slide_graph.zig:110` learnedChat 过滤 `chat` | `:110` 条件含 `source == chat` | 符合 |
| `slide_panel.js:63,95` | `:63` parts，`:95` add("source") | 符合 |
| `packaging/omp/sliding-weights.ts:104` | `:104` body（不含 about） | 符合 |
| `routes.zig:66` | `zig/src/server/routes.zig:66` | 符合 |
| `slide_model.zig:29` MoE 层 | `:29` | 符合 |
| `slide_ask.zig:66` enable_thinking | `:66` | 符合 |
| `root.zig:59` 测试入口 | `zig/src/server/root.zig:59` 为 `slide_whom`；`slide_lesson` 在 `:54` 被导入 | 符合（但见 m6） |
| `docs/living-weights.md:16,78,91-93,95,119,161,184-186,191-193,194` | 均核对 | 符合 |
| 需求原话 `:5,:7,:11,:12,:17-20,:26-28` | 均核对 | 符合 |

未能核实的推断与声称：
- `slide_words.zig` 测试 `twinGrounded(...)` 等为新函数，无法核实（不存在）。
- “英文 `you` 主宾格判断”、`selfGrounded` 半数阈值、`self_leak_prompt` 宽严：均为设计内推断，设计已标 [推断]（正确）。

---

## 5. 次要问题

- **m1 中文 `toSelf` 的“前紧邻”规则无法直接实现。** §3.3 写“中文‘我’前紧邻的不是 告诉/给/跟/和/对/帮/让/请/问 之一”。这些是二字词（告诉、记得 不在列表中），但“紧邻”按字符判定只能比较单个字。需明确为：判断“我”前一字（单字表）还是前两字（二字词表）。
- **m2 `self_judge_prompt`、`self_leak_prompt` 的 `{s}` 参数顺序未规定。** `self_leak_prompt` 含 3 个 `{s}`（问题、回复、事实），设计未写实参顺序。`self_judge_prompt` 同理（事实、问题）。需在 §3.3/§3.7 显式列出。
- **m3 `refreshSelf` 与既有 `refresh(stale.keep)` 的职责重叠。** `slide_teacher.zig:85-90` 已对 `stale.keep` 重读（用 `ask`，即已教模型）。§3.6 第 4 条新增 `refreshSelf` 对 `toSelf` 的全部英文/语言 keep 重读。设计未说明：为何非 stale 的 toSelf keep 也要重读、重读后与 `answeredByAny` 的关系、以及两者能否合并。
- **m4 `answeredByAny` 对 self 的 `!toSelf(q) → false` 使每课每个用户自问都必须重新问模型并保持。** 设计 §3.6 第 1 条未估算该开销；在 `personal_prompts`/`untold.checked/kept`/`bank` 上每课额外 `ask` 次数应列出。
- **m5 `recallsShort()` 的位置表述。** §3.7 写 “召回判定 `brings()` / `recallsShort()`（`slide_verify.zig:121-124`）”；`:121-124` 仅定义 `brings`，`recallsShort` 在 `slide_words`。
- **m6 `slide_route.zig` 是否被测试收集。** 设计 §7.12 标“[推断：不确定]”，并要求显式列入 `root.zig`。实际 `zig/src/server/root.zig:54` 导入 `slide_lesson.zig`，`slide_lesson.zig:12` 导入 `slide_route.zig`。是否被收集取决于 Zig 的 refAllDecls 传递性，设计可直接核实后删去“不确定”。
- **m7 §6.1 单测依赖仓库外的 `001-identity-core.md`。** `zig build test` 必须纯函数、隔离（工程约定）。`selfGrounded` 测试应内联一段夹具字符串，而不是读 `~/projects/qwen/...`。
- **m8 `selfFacts` 的假设“按句切得到 `1月15日生,今年28岁。`”** 未经实测，应标 [推断]。另外 `001-identity-core.md` 的首段已有 4 句以上，是否进入 `chat` 按句路径取决于 `source`（设计 §2 默认 `chat`），需写明 self 模式不走 `facts()` 的句切分支。

---

## 6. 实现可行性

可行的部分：
- `About` 枚举替换 `document: bool` 的范围清楚，且与 clean cutover 要求一致。
- `slide_lesson.zig`、`slide_take.zig` 中 `document` 的引用位置与设计表格基本对应（已逐条核对）。
- 镜像函数 `mirrored`、`toSelf` 的主要英文规则可以写成确定性函数并单测。

不可行或未定义的部分：
- 中文 `toSelf`（m1）、判定器参数顺序（m2）未定义，实现者需要自行决定。
- `refreshSelf` 与 `refresh` 的边界（m3）未定义。
- 效果 4 无门槛（B2），实现完成后无法判定通过。
- §6.2 实机实验依赖 `~/models/nemotron-elias` 与 Mac 环境；设计未说明在 GB10/NVIDIA 环境下的验收。

---

## 7. 是否改变既有 user / document 模式

- 设计声称不变（§1、§3.0、§5）。实际：
  - **已在工作区发生变化**（B1）：中文 `firstPerson`、`toModel`、`addressed`。
  - **在 self 课运行后发生变化**（M5）：`refreshSelf` 改变英文 keep 的缓存目标，后续 user 课随之变化。
  - **设计本身的代码改动**：`document: bool → About` 为机械改写，设计承诺逐行等价；`answeredByAny`、`answered`、`keep` 的 `[]api.Example` 改造（§4）若实现不当会改变 user 路径，需以基线对比验证，设计未给出基线比较方法。
- 建议：先把 B1 的工作区改动单独提交并列为 user 行为变更；再以“self 未启用时对同一输入逐字节比对 `learn` 的 SSE 与日志”作为 user/document 不变性的验收。设计目前没有这一条。

---

## 8. 建议的修订顺序

1. 处理 B1：确认中文人称改动是否应保留；若保留，在设计中列为 user 行为变更，并修正 §1、§3.3、§4、§5。
2. 处理 B2：明月给出效果 4 门槛，或设计给出标注 [推断] 的临时门槛；N5 改为判定项。
3. 处理 M1–M2：补文档级与经历/外貌的验收条目（语料路径已可用）。
4. 处理 M3–M4：把“用户原意”改为 [推断]；删除或回写“任务说明”依据，决定是否保留孪生机制。
5. 处理 M5：统一 §1 与 §5 的 user 不变性表述，并加入 self 未启用时的逐字节比对验收。
6. 处理 m1–m8。
