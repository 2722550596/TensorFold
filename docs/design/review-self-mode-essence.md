# self-mode 本质审查

范围：只读审查。本文件是唯一产物；未改动设计文档或源码。

- 第一步：仅依据效果清单、`zig/src/server/slide*.zig`、`docs/living-weights.md`，独立给出架构（本节先于读取 `docs/design/self-mode.md` 写成）。
- 第二步：读取 `docs/design/self-mode.md`，列出“效果未达成项”与“无道理复杂度”，并与第一步对照。

效果清单（审查基准）：
1. 问“你是谁 / Who are you”，模型以角色埃利亚斯·索恩（Elias Thorne / 埃利亚斯·索恩）第一人称回答。
2. 问角色自身事实（生日、过去、外貌），模型第一人称回答。
3. 中文第一人称训练文档可以被教入。
4. 角色人设泄漏到无关聊天可接受。
且：现有用户事实与文档学习必须继续工作。

---

## 第一步：独立架构（不读设计文档）

### 1.1 现有代码的结构性事实

**A. 现有流水线整体假设“被告知的是用户”或“文档是第三人称”，没有“问模型自身”这一类。**

- `zig/src/server/slide.zig:111`：`document = !source.eql("chat") or !wording.firstPerson(fact)`。只有 `chat` 来源且含“我/I/my”的句子才走“用户事实”路径；其余一律走“文档”路径。
- `zig/src/server/slide_whom.zig:39-62`：`firstPerson` 认为“你/you”出现即非第一人称、返回 false。因此“你是谁？”永远不会被认作合法的被学问题。
- `zig/src/server/slide_take.zig:101`：`personal = !document and (!firstPerson(q) or someoneElse(fact,q))`，问题只要含 you/your 就被丢弃（"is not the user asking what the fact answers"）。
- `zig/src/server/slide_words.zig:460`：测试明确规定 `toModel("What is your favourite colour?")` 为真，即“你”类问题被当作与用户事实无关。

**B. 现有流水线主动保护“问模型自身”的答案不变（与效果 1、2 直接相反）。**

- `zig/src/server/slide_prompts.zig:13,15,16`：`keep_prompts` 含 "What is your favourite colour?"、"How old are you?"、"Who are you?"。这些答案在每次课程前后被当作“必须原样保留”的 keep 样本，并在 `verify` 里用 `same` 判定是否变化（`slide_verify.zig:86-89`：变化即 `took`/`damage`，课程被回滚或改路由）。
- `zig/src/server/slide_lesson.zig:443`：`addressed(question)`（我→你）生成的“问模型”近似问题被加入 `nears`，作为近似误判样本保持原答案。
- `slide_verify.zig:41-43`：所有 `checks` 与 steady prompt 都进入 `same`/`looped` 判定，任何无关回答的改变都会触发回滚。

结论：效果 4（人设泄漏可接受）与现有的“任何无关答案变化即回滚”机制直接冲突。在现有 gate 下，persona 课程必然在 `verify` 阶段被 `took`/`damage` 取消，它不会“学成功后再泄漏”，而是根本学不进去。

**C. 一个会直接伤到用户事实的分类错误（需要在架构中避免）。**

- 中文第一人称角色设定如“我叫埃利亚斯·索恩。”：`firstPerson` 因 `我` 命中返回 true（`slide_whom.zig:58-59`），且 source=chat 时 `document=false`，走用户事实路径。问题改写成“我的名字是什么？”等用户问题，把角色的名字教成用户的名字。效果 2、3 必然错，同时污染“What is my name?”这类用户事实。

**D. 可复用的部件（应保留，不重写）**

- 引擎端的 `LearnRequest`（`zig/src/core/engine_api.zig:266-283`）：`train/held/near/keep/asked/unasked/undo/drop/save/retire` 等，已经是 pocket neuron 的通用学习接口；`Example.decide/subject/value` 为行键。
- `slide_ask.askBaseAt`/`askBase(system_note, q)`（`slide_ask.zig`）：带“注记”的回答生成，正好可以写成“你是 X，以下是你的事实：…，用第一人称回答”，产出角色第一人称答案，无需新机制。
- `slide_ask.example` / `promptOnly` / `promptAfter`：把问题与答案编码为训练样本，与角色无关。
- `slide_language.prompted`/`translated`、`slide_words.sentences`/`natural`/`clean`：中文分句与问答提取已存在。
- `slide_found.facts`：分块事实抽取，对中文文档可用（`slide_found.zig:19-23`）。
- `slide_verify.brings` / `recalls` / `recallsShort`：held-out 召回判定，可用于角色事实的召回校验。

### 1.2 推荐架构：独立的 persona 课程类型

核心判断：效果 1–3 要求的是一类新的“事实-问题”关系——问题的对象是模型自己（you），答案是角色的第一人称陈述。现有的 `document` 与 `chat` 两类都不能表达它，硬塞进去会同时破坏两类已有保护。因此应在课程层面增加第三种类型 `persona`，而不是在现有 gate 上加例外。

**1. 入口与分类（slide.zig `learn`）**

- 请求新增显式来源：`source` 取 `persona`（或等价的 `kind` 字段）。角色设定与角色文档以 `persona` 提交，不依赖 `firstPerson` 启发式猜测。
- 不做自动判断：启发式会把“我叫埃利亚斯”误判为用户事实（见 1.1-C）。显式来源是唯一可靠的分流。
- 用户事实与文档流程不变（`chat` 默认、`document` 判定不动）。

**2. 事实抽取（复用 slide_found.facts）**

- 中文/英文文档分块抽取复用现有 `facts()`，但 persona 来源跳过 `reversed()`（“A 创立 B”反转在角色设定里没有语义价值，只会制造第三人称问题）。
- 每条事实规范化为第一人称角色陈述或保留原文，二者都保留角色名。

**3. 问题生成（新 prompt，面向“问助手自身”）**

- 生成“用户会问助手自己”的问题：“你是谁？”“你多大？”“你在哪里长大？”、英文 "Who are you?" 等，中文用“你”。这是现有 `questionsFor` 的新变体（`persona_questions_prompt`），与 `questions_prompt`（“我”问题）并列。
- 问题只允许含 you/your（或中文“你”），不得含 I/my/我——保证与用户事实路径不混。

**4. 答案生成（复用 askBase + 注记）**

- 注记：`"你是{角色}。以下是你的事实：{事实}。用第一人称回答。"`，经 `askBase(note, q)` 得到第一人称答案；`example()` 编码，`subject` 行取 "you" 词所在行（或 reply 行），`value` 行取答案中的事实词。
- 不再做 `write()` 中的 `judged/siblingAnswers/gives` 等多层过滤（这些是为“用户事实不重复”设计的，persona 的问题本来就都是“你”）。保留的仅是“答案非空、有限长、以句号结尾”的基本清洗（`natural`/`clean`）。

**5. 训练与召回（LearnRequest）**

- `train`：每条问答（问题 + 第一人称答案），加上 `systems` 与 `turns` 的前缀变体（与现有 `under()` 相同机制，保证 system 消息下也生效）。
- `held`：每个事实留两条不参与训练的问答（与现有 `heldPair` 相同），用于召回判定，判定函数复用 `brings`/`recalls`。
- `asked`：更多问法的路由训练（prompts only）。
- `unasked`（路由负样本）：必须包含用户问题（`personal_prompts` 与 `personal_bank` 的一个子集，如 "What is my name?"、"Where do I live?"）。这是保证用户事实不被角色覆盖的唯一必要负样本，不能省。

**6. 校验（比现有简单得多）**

- 召回：`held` 答案在轮次后必须召回；未召回则 `drop`，与现有 `rounds` 的 give-up 逻辑相同（复用 `slide.zig` 的 `rounds`）。
- 用户事实守护：只检查 `personal_prompts` 的一个小子集（3 条，复用 `heldBack` 轮换）。若回答由用户事实变为角色事实（例如“我的名字”返回“埃利亚斯”），则回滚。这是唯一必要的“泄漏”检查，因为它保护的是用户事实，而不是“无关聊天”。
- 不做：near-miss 双生样本、kindsOf 替换、roles/essence/writing 保持、同义改写、thinking 对照、replay 等。效果 4 明确允许无关聊天泄漏，这些检查只会阻止学习成功而不保护任何效果项。

**7. 中文**

- 问题与答案的语言跟随事实语言：复用 `slide_language.languageOf` 与 `prompted`，persona 版本的 prompt 同样需要中文变体（`persona_questions_other`）。
- 中文第一人称文档（“我叫埃利亚斯·索恩。我生于……”）在 `persona` 来源下直接走 persona 路径，不经过 `firstPerson` 分类，因此不会被误判为用户事实（解决 1.1-C）。

**8. 保存与回滚**

- 复用现有 `drop/undo/save/retire`。persona 的 neuron 与用户事实 neuron 位于同一 pocket，保存路径不变。

### 1.3 备选方案及取舍

- **备选 A：在 system prompt 中注入角色（不改权重）**。实现最简单，但违背 Living Weights 的目标（事实进入权重、重启后仍在），且效果 3（教入中文文档）退化为“把文档拼进 system”。不推荐。
- **备选 B：在现有 `document`/`chat` gate 上加 persona 例外**。改动最小，但 `keep_prompts`（"Who are you?" 等）、`same`、`took`、`damage` 都会在 persona 课程里触发回滚，例外会散布在 6–8 个函数里，实质是重写 gate 而非增加一类。不推荐。
- **推荐：独立 `persona` 课程类型**，复用引擎接口与答案生成/编码/召回判定，去掉 persona 不需要的 gate。

### 1.4 第一步预期的验证面（供第二步对照）

- 角色问题（“你是谁？”、“你的生日是哪天？”）用第一人称召回。
- 用户事实（“What is my name?”）在 persona 学习之后不变。
- 中文第一人称文档可被教入且不被当作用户事实。
- 文档学习（已有 `document`）行为不变。

（第一步结束。以下为第二步。）

---

## 第一步校正（写第二步时核对所得）

- `slide_whom.zig` 中文"我/咱"判定与 `你的/您的` 排除：未提交 diff 位于 `:52-54`（非 `:58-59`）；`addressed()` 的"我→你"全局替换位于 `:93-97`。
- `slide_verify.zig`：`took`/`damage` 出口位于 `:86-89`（已核对）；`checks` 收集位于 `:27-43` 一带（原写 `:41-43`，不精确）。
- `slide_found.zig`：`facts()` 位于 `:17-23`（原写 `:19-23`）。
- `slide_teacher.zig`：`refresh()` 位于 `:79`，`local()` 位于 `:102`（本报告第二步引用）。
- 第一步的架构结论不变；第一步中"`我` 命中即判为用户事实"已被未提交 diff 证实（见 B1）。

---

## 第二步：对照设计文档 `docs/design/self-mode.md`（486 行，已通读）

### 2.0 与第一步的比较

| 维度 | 第一步（独立推导） | 设计文档 | 判断 |
|---|---|---|---|
| 分流方式 | 显式来源，不靠启发式猜 | 显式 `about` 字段（§2） | 一致，正确 |
| 复用面 | 复用引擎接口、答案生成、召回判定；去掉 persona 不需要的 gate | 复用 lesson/verify/router/teach，`About` 贯穿约 14 个文件（§4 列出约 70 余条改动点） | 设计复用更多；代价是 blast radius 大（见 C10） |
| 用户自问 | 作为 `unasked` 负例守护 | 镜像 `mirrored()` 生成 near miss 与负例 | 目标一致；设计的实现比必要的复杂（见 C2） |
| 泄漏检查 | 只保护用户事实，不查世界问题 | 对所有非 toSelf 检查增加第二次判定 `self_leak_prompt` | 设计更复杂，且与效果 4 不完全一致（见 C5） |
| keep 刷新 | 未涉及 | 新增 `refreshSelf`、语言缓存、`forgetLanguages` | 设计重复造轮子（见 C6） |

结论：设计的骨架（显式 `about`、self 只改问题生成/过滤/答案 note/keep 与 near miss）与第一步一致，可保留。超出必要的部分集中在启发式词表、镜像语法、孪生事实、第二次泄漏判定和平行的 keep 刷新。

### 2.1 效果未达成项

| 效果 | 设计的达成路径 | 状态 | 依据 |
|---|---|---|---|
| E1 问"你是谁/Who are you?"以第一人称答角色 | `self_prompts` → `take` + `self_judge_prompt` → 学习 → `refreshSelf` 覆盖 keep 缓存 | **未证实** | 唯一验收是 §6.2 步骤 2 的 I1–I6，且 §7.3 自承中文/基模型判定未测；英文问法依赖孪生事实（C3） |
| E2 角色自身事实（生日、过去、外貌）第一人称答 | `selfFacts` + `self_questions_prompt` + `toSelf` 过滤 | **未覆盖（外貌、经历）** | §6.2 只测生日（P1–P3）与身份（I1–I6）；无外貌、无经历样本，抽取示例也只用生日（§3.1） |
| E3 中文第一人称文档可教 | `selfFacts` 分块抽取 + `selfGrounded`（CJK 字对"至少一半"）+ 中英孪生 | **未证实** | "一半"阈值标注 **[推断]**（§3.1）；§6.1 单测只覆盖 `toSelf`/`mirrored`/`selfVoiced` 纯函数，不覆盖 `selfFacts` 的真实输出；§7.3 中文质量未测 |
| E4 人格泄漏到无关聊天可接受 | §3.7 仅对 `toSelf` 检查放行 "说的是自己" 的泄漏 | **未按需求实现** | 需求已明确"可接受"；设计仍保留 `took` 回滚、`self_leak_prompt` 二次判定，并把"定量门槛"列为"待明月确认"（§8 效果 4）。门槛不应存在；世界类 keep 问题仍走 `same_prompt` 判定（`slide_verify.zig:86-89`，`slide_prompts.zig:246`），设计未说明 persona 语气变化是否会触发回滚 |
| E5 现有用户事实与文档学习继续工作 | 设计声称"逐字节同路径"（§1 末段、§5） | **不成立（见 B1）** | 未提交的 `slide_whom.zig` 已改变 user 路径；§6 没有 user 路径回归测试 |

### 2.2 阻塞 / 主要问题

**B1（阻塞）设计前提与工作区不符：user 路径已被未提交改动改变。**

证据：`git diff -- zig/src/server/slide_whom.zig`。
- `firstPerson()` 现对任何含"我/咱"的句子返回真（`:52-54`）。原来 `"我喜欢蓝色"` 无 I/my，`firstPerson` 为假，`slide.zig:111` 的 `document = !chat or !firstPerson` 为真，走 document 路径。现在走 user 路径。
- `addressed()` 现把**所有**"我"替换为"你"（`:93-97`）。这是 user 模式的函数：`slide_lesson.zig:443` 的 near miss 与 `addressed(q)` 的其他调用都会改变输出。
- §1、§5 承诺"user/document 逐字节同路径"在工作区上不成立；§6 只要求现有测试通过，不要求 user 路径输出不变。

影响：需求第一条约束"现有用户事实学习必须继续工作"在当前工作区无证据支持。
修复：(a) 中文人称改动只在 `about == .self` 分支调用，不改 `firstPerson`/`addressed` 的全局行为；或 (b) 先把 user/document 的中文样本（至少"我喜欢蓝色"、"我叫X"、"What is my name?"）的前后路由与 near miss 输出做成回归固定，再合并。

**M1（主要）效果 E1、E2 缺少分段验收。** §6.2 是一次端到端实机实验，失败时无法定位是抽取、问题生成、判定、还是 keep 刷新出错。应在每个阶段输出可检查的中间结果（事实列表、问题列表、判定结果）。

**M2（主要）启发式阈值未实测却进入设计。** `selfGrounded` 的"一半"、`selfVoiced` 的标记表、`toSelf` 的"我/你的"判定，都是 **[推断]** 或未经测试的词表。它们决定事实是否被丢弃，应先以日志统计再定阈值，而不是先写进契约。

### 2.3 无道理复杂度（每项：为何可能不必要 → 更简单的替代）

**C1 亲属替换链（`aboutZh`、`selfOthers` 的亲属部分、`aboutSelf` 的亲属分支、§6.1 亲属测试）**
- 为何不必要：需求的四条效果里没有亲属。`slide_route.others()` 已有亲属替换（`slide_route.zig:13`），设计只是把它镜像到"你"方向。
- 替代：删除 `aboutZh` 与所有亲属分支；只保留 `mirrored()`。

**C2 `mirrored()` 的英文语法规则（助动词/疑问词判断、`are I→am I`、`were I→was I` 等）**
- 为何不必要：用户自问负例的目标是"用户问自己的生日时不答角色生日"。现有 `personal_prompts`（`slide_prompts.zig:48-57`）与 `personal_bank`（`:73` 起，已含 "When was I born?"、"Where was I born?"）已经是 keep 检查集，本就会被 `same` 判定守护。缺的只是 "When is my birthday?" 等少数问法。
- 替代：把缺的用户自问直接加进 `personal_prompts`/`personal_bank`。翻译、keep、判定都已有路径（`slide_teacher.zig:102-119` 的 `local()` 会翻译 `personal_prompts`）。不做英文语法变换。
- 注意 **[推断]**：需实测 N1/N2 是否由这条已有守护拦住。

**C3 中英孪生事实（§3.1 第 3 步、`twinGrounded`、§3.3 `siblingAnswers` 去孪生、§7.1 与 §7.11 的容量与时长翻倍）**
- 为何可能不必要：孪生存在的理由是 `units.sameScript()`（`slide_units.zig:162`）与英文 router 负例。但 `take()` 中的 `sameScript` 检查（`slide_take.zig:102`）与 `factLesson` 中 `routerData` 的 `sameScript`（`slide_lesson.zig:469`）是可以对 `.self` 放宽的。
- 替代：`.self` 不做 `sameScript` 限制，单事实 + 中英两套问题（问题由同一事实生成），答案语言跟随问题（`self_note` 写明"用问题的语言回答"）。这去掉 `twinGrounded`、孪生互指、去孪生的 `siblings`，并使容量与时长减半。
- 注意 **[推断]**：英文问法能否被路由门控正确命中需实测（§6.2 P2）。

**C4 `selfGrounded` 的"CJK 字对至少一半"与 `twinGrounded` 的数字子集规则**
- 为何不必要：两者都是新发明的阈值（§3.1 标注 **[推断]**）。设计自己指出 `grounded()`（`slide_words.zig:198-214`）对改写句会误拒；但真正的问题是抽取允许"自由改写"。
- 替代：让抽取只产出两种形式——原句原样，或原句前补"我"——然后用现有 `grounded()` 原样校验。失败即丢弃，无新阈值。编造的事实由已有的 held-out 召回（`brings()`，`slide_verify.zig:` 的 `brings` 调用）兜底。

**C5 `self_leak_prompt` 第二次判定 + `knowing()` 的 "说的是自己" 放行（§3.7）**
- 为何不必要：效果 4 明确接受人格泄漏到无关聊天。世界类问题（"法国首都"、"seasons"）的回复变化不需要被判定为泄漏。只有**用户自问**的检查（即 `personal_prompts`/`personal_bank`，现有 `took` 路径）才需要保护。设计把两类混在 `!toSelf` 一起，于是需要第二次 LLM 判定来区分。
- 替代：泄漏检查（`took`）只对用户自问检查启用；删除 `self_leak_prompt`；世界类检查不做泄漏判定，只保留现有 `same_prompt` 的非泄漏语义。这同时删掉"定量门槛"问题。

**C6 `refreshSelf` + `Local.keep_questions` 过滤 + `forgetLanguages` + `languages` 的逐条过滤（§3.6 第 3–4 条）**
- 为何不必要：`slide_teacher.refresh(srv, cx, teacher, stale, gone)`（`slide_teacher.zig:79`）已经对 `stale.keep` 重读缓存答案，`slide.zig:127` 已调用它。`refreshSelf` 是它的复制。
- 替代：`toSelf` 的 keep 下标放进 `stale.keep`（本课回答的即剔除），调用同一个 `refresh`。语言缓存（`teacher.languages`，`slide_teacher.zig:102-119`）里的 keep 答案，让 `refresh` 同时遍历 `teacher.languages`，一处实现，不新增 `forgetLanguages`。

**C7 独立的 `self_judge_prompt` 与 `self_prompts` 的 `take` 调用（§3.2、§3.3）**
- 为何可能不必要：`self_judge_prompt` 是为"你=模型"的语境新写的判定，但 `judge_prompt`（`slide_prompts.zig:248`）已能判"事实是否回答问题"，只需把措辞中的"你告诉我"改为中性。
- 替代：先复用现有 `told_judge_prompt`/`judge_prompt`，只有实测判定失败时再加新 prompt。

**C8 `self_besides_prompt`/`self_besides_other`（§3.2、§3.3）**
- 为何不必要：`besides_prompt`（`slide_prompts.zig:232`）的结构相同，只换了"谁在问"。
- 替代：复用 `questionsFor(.self)` 或只改 `besides_prompt` 的一句措辞。

**C9 `selfVoiced()` 的标记黑名单（`assistant`、`助手`、`设定`、`扮演`、`你告诉`…，§3.4）**
- 为何不必要：子串匹配会误杀合法回答（"助手"可以是正常内容），而且只做丢弃、不修补。第一人称靠 `self_note` 约束，验收靠 I1–I3。
- 替代：删除黑名单；只保留对"你的/您的"（听者所有格）的一条检查，或完全不做，用 §6.2 验收代替。

**C10 `About` 贯穿约 14 个文件的全链路签名替换（§3.0、§4 列出约 70 余条改动点）**
- 为何可能过度：`About` 枚举本身合理（三种模式），但改签名是在 user/document 的热路径上做大手术，与"逐字节不变"的承诺冲突（B1）。
- 替代：`learn` 解析 `about`；self 分支自成一组函数（选事实、生成问题、生成答案 note）。复用 verify/router 的 `Check`/`Held` 类型，但不改 user/document 函数的签名。这与第一步的"窄前端"方向一致。

**C11 `slide_route.zig` 测试是否被收集（§7.12，§4 的 `root.zig` 行）**
- 为何不必要：这是一个待确认的小问题，应直接跑一次 `zig build test` 确认，而不是在设计中预写一条改动。
- 替代：先确认，再决定是否在 `root.zig` 显式导入。

### 2.4 保留项（设计中经核对合理，不列为复杂度）

- `thinkingAnswer` 的 `self_start` 召回行（`slide_think.zig:20-21`）：若保留 "I remember the user told me"，self 课的 thinking 样本会与人格语义冲突，需要单独一行。
- `aboutEntity` 对 self 恒为假：self 事实没有"主题实体"语义，跳过合理。
- `other_values_prompt` 与 "Do you remember…" 改写的跳过：正确，它们是为用户设计的，删掉可减少负担。
- `answeredByAny` 的 self 分支不加 `shares()` 前置：正确，"我是埃利亚斯·索恩"与 "Who are you?" 没有共享显著词。

### 2.5 建议

1. 先修 B1：中文人称改动只在 self 分支生效，或先固定 user/document 回归样本。
2. 按 C1、C2、C5、C6 精简：删亲属链，用已有 `personal_prompts` 守护用户自问，泄漏检查只对用户自问启用，复用 `refresh()`。这四项删除量最大、风险最低。
3. 将 C3（孪生）作为待实测的替代方案，先跑一次"单事实 + 双语问题"对照（§6.2 P2）再决定。
4. 按 §6.2 增加外貌与经历样本（E2），并为 E3 增加 `selfFacts` 对真实中文文档的输出检查（每条事实是否逐字可溯源）。
5. 删除 `self_leak_prompt` 与"定量门槛待明月确认"（E4），需求已给出结论。

（第二步结束。）
