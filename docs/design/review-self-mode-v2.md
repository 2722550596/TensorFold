# 复审：self-mode.md v2 对照 需求原话.md（含新裁定）

审查对象：`docs/design/self-mode.md`（第 2 版，提交 9b939e9，504 行）。
对照：`docs/design/需求原话.md`（工作区版本，含未提交的两条“明月拍板”）；前两份审查 `review-self-mode-req.md`、`review-self-mode-essence.md`。
审查方式：只读。逐条核对 v2 的 `file:line` 引用与 HEAD 代码；核对语料 `~/projects/qwen/train-docs/elias/001-identity-core.md` 中 D 组事实；核对 git 历史。未修改任何源码或其他设计文档。

## 0. 结论

判定：**不通过（FAIL）**。

阻塞项 1 项：**英文问法未按新裁定关闭**。`需求原话.md:16` 已裁定“英文问法不要求，只要中文；中英孪生方案作废”，但 v2 仍把英文问法列为“待明月确认”（§1、§6.2、§7），英文相关机制（`self_prompts` 英文条目、英文 `toSelf`/`mirrored` 规则、英文 keep 刷新规则、英文验收断言）仍作为设计内容保留。

非阻塞但须修：需求原话行号引用已过期（工作区新增两行后效果/解法条目下移 2 行）；“中文人称修复未提交”的叙述已过期（已在 11ee183 提交）。

前两轮的阻塞项 B1、B2 及主要项 M1–M5 已解决（见 §2）。

## 1. 英文问法项：逐条核对（本次审查的明确检查项）

裁定原文（`需求原话.md:16`）：“明月拍板（问答选择）：英文问法**不要求**，只要中文；中英孪生方案作废。”

v2 中仍为“开放”的位置：

| 位置 | 现文 | 与裁定的关系 |
|---|---|---|
| §1 第 4 段末 | “英文问法（需求未要求，列为待确认项，§7）” | 仍写“待确认”，应改为“不要求（需求原话.md:16）” |
| §6.2 实验 S 之后 | “英文问法（`Who are you?`、`When is your birthday?`）**只记录不判定**（待明月确认，§7）” | 仍写“待确认”；裁定已给出结论 |
| §7 第 1 条 | “英文问法：需求原话未要求问 `Who are you?` 也答 Elias……如需英文，候选做法是……” | 整条应删除或改为“已裁定不要求”。当前写法把已关闭的问题重新打开，并给出一条新的“候选做法” |
| §10 “essence C3 / req M4” 行 | “英文问法列入 §7” | 应改为“按 `需求原话.md:16` 不要求” |

v2 中仍携带英文机制的位置（裁定后按“不要求”应当删去或明确标注为非验收项）：

| 位置 | 内容 | 说明 |
|---|---|---|
| §3.1 `toModel` | 补英文 `yours`、`yourself` | 英文问法不要求，无需改词表 |
| §3.1 `mirrored` | 英文 `your→my … you→I` 与 6 条英文动词修正表 | 只服务于英文问法的负例镜像；中文负例只需“你/您→我” |
| §3.1 `selfVoiced` | 英文 token `your`、`yours` | 同上 |
| §3.3 `self_prompts` | 含 `Who are you?`、`What is your name?`、`Tell me about yourself.` | 英文条目。`slide_take.zig:102` 中 `sameScript` 先于 `judged` 短路，中文事实下这三条在判定前即被丢弃（`slide_units.zig:162-164`），对中文事实无效，只留下死条目 |
| §3.6 规则 2 | 英文 `keep` 的 `.self` stale 条件 | 英文 keep 不刷新不违反任何裁定（英文问法不要求答角色） |
| §6.1 单元测试 | `"Who are you?"`、`"When is your birthday?"`、`"Tell me about yourself."`、`"Who am I?"`、英文 `selfVoiced` 样例等 | 英文断言不再是验收项，应删除或标注为非验收 |
| §6.2 实验 S/D | 英文问法记录 | 应删除，或标注为“非验收、不计入通过条件” |

修订要求（任选其一，但须在 §7 写明结论）：

1. **推荐**：删除上表所有英文机制与英文断言；§7 第 1 条删除，`§1`、`§6.2`、`§10` 同步改为“英文问法不要求（需求原话.md:16）”。`self_prompts` 只留 `你是谁？`、`你叫什么名字？`、`介绍一下你自己。`。
2. 或保留英文机制，但在 §1、§3、§6 逐处标注“非需求、不计验收、不做判定”，并说明其保留的理由。

不接受：继续在 §7 列为“待明月确认”。该项已由明月裁定，属于已关闭的问题。

## 2. 前轮审查项的处理状态

| 来源 | 编号 | 状态 | 依据 |
|---|---|---|---|
| req | B1 user 不变式被中文改动打破 | **已解决（改为显式行为变更）** | §5.1 列出 user 行为变更及落点；§10 将“逐字节不变”改为“除中文修复与 self 课后 keep 刷新外不变”；§6.3 R1–R3。中文修复已提交为 `11ee183`（见 §4 N2），HEAD 上确属 user 路径变更，v2 的描述成立 |
| req | B2 效果 4 不可证伪 | **已解决** | `需求原话.md:24` 已写“不设门槛，不作为验收否决项”；§3.7 删除 `self_leak_prompt` 与泄漏门槛；S6、DN 只验“有回应、不崩坏”。注：§10 引用 `:22`，应为 `:24`（见 N1） |
| req | M1 中文文档级验收缺失 | **已解决** | 新增实验 D，语料 `001-identity-core.md` 已核对：`1月15日`、`28岁`、`Elias Thorne`、`奇点无限`、`恒星云`、`SC-HQ-2008001` 均在该文件中，D1–D6 的判据与语料一致 |
| req | M2 经历、外貌未验收 | **已解决** | S3（外貌）、S4（经历）、D3–D6。注：S3/S4 使用的是自造句子，不是语料中的外貌文件 `003-identity-appearance.md`；可接受，但语料外貌条目未进入验收（非阻塞） |
| req | M3 “用户原意”未确认 | **已解决** | §1 改为引用 `需求原话.md:9` 原话；“用户原意”措辞已删 |
| req | M4 孪生依据不存在 | **已解决（机制已删）** | 孪生、`twinGrounded`、`Found` 改造、去孪生 `siblings` 均已删除。但英文问法仍开放，见 §1 |
| req | M5 §1 与 §5 关于 user 不变的矛盾 | **已解决** | §1 不再出现“逐字节”；§5.2 末段将 keep 刷新列为有意的持续性差异 |
| req | m1 “紧邻词”规则 | 已解决 | 整条规则删除，`toSelf = toModel ∧ ¬firstPerson` |
| req | m2 判定器实参顺序 | 已解决 | §3.3–§3.7、§4 写明实参 |
| req | m3 `refreshSelf` 与 `refresh` 重叠 | 已解决 | 并入 `refresh`，`Stale` 增 `local`、`language` |
| req | m4 `answeredByAny` 开销 | 已解决 | §3.6 规则 1 说明调用数不多于 user 课 |
| req | m5 `recallsShort` 位置 | 已解决 | 指向 `slide_words.zig:238`（已核对） |
| req | m6 `slide_route` 测试收集 | 基本解决 | 改为“仅在未见测试时补导入”。可接受 |
| req | m7 单测依赖仓库外文件 | 已解决 | 夹具内联（§6.1） |
| req | m8 句切假设 | 已解决 | §3.2 写明 self 不走 `facts()` 句切分支，引 `slide_units.zig:5-13` |
| essence | C1 亲属链 | 已解决 | `aboutZh`、`aboutSelf`、`selfOthers` 亲属分支删除 |
| essence | C2 `mirrored` 语法规则 | 部分解决 | 中文规则保留；英文规则仍在，见 §1 |
| essence | C3 孪生 | 已解决（机制） | 英文问法仍开放，见 §1 |
| essence | C4 `selfGrounded` 阈值 | 已解决 | 改为原样 `grounded` 或去句首“我”后 `grounded`，无新阈值（已核对 `slide_words.zig:198-214`） |
| essence | C5 `self_leak_prompt` | 已解决 | 删除；用户自问走现有 `same_prompt` |
| essence | C6 `refreshSelf` | 已解决 | 并入 `refresh` |
| essence | C7 `self_judge_prompt` | 已解决 | 复用 `judge_prompt` |
| essence | C8 `self_besides_prompt` | 已解决 | `.self` 跳过 besides，风险列入 §8 第 4 条 |
| essence | C9 `selfVoiced` 黑名单 | 已解决 | 只保留听者所有格 |
| essence | C10 `About` 全链路 | 保留并以 R3 兜底 | 可接受 |
| essence | C11 测试收集 | 已解决 | 同 m6 |
| essence | M1 分段验收 | 已解决 | 实验 S/D 检查 SSE 事实、`questions kept for:`、`near misses kept steady:` 等日志 |
| essence | M2 启发式阈值 | 已解决 | 见 C4、C9 |

## 3. 引用核查（本次）

已对照代码或语料核实，符合：

- `slide_whom.zig:39-57`（firstPerson，含 `你的/您的` 排除与 `我/咱`）、`:60-64`（toModel，唯一生产调用点 `slide_lesson.zig:143`，已 grep 确认）、`:67-106`（addressed）、`:125-151`（about）、`:153-163`、`:216-226`（中文测试）。
- `slide_words.zig:134-141`（tells）、`:144`（recalls）、`:198-214`（grounded）、`:238`（recallsShort）、`:460`（toModel 测试）。
- `slide_units.zig:4-13`（sentenceEnd）、`:162-164`（sameScript）。
- `slide_prompts.zig:4-16`（keep_prompts）、`:48-57`（personal_prompts，8 条）、`:73`（personal_bank）、`:218`（questions_prompt）、`:228`（told_note）、`:232`（besides）、`:242`（about_prompt）、`:246`（same_prompt）、`:248`（judge_prompt）、`:254`（told_judge_prompt）。
- `slide_found.zig:14`（chunk_chars）、`:17-25`（facts）、`:41`（reverse 跳过 firstPerson）、`:84-88`（无示例重问）。
- `slide.zig:66-76`（learn 入口、source）、`:90`（found.facts）、`:98`（add）、`:111-113`（document/giveWay）、`:127`（refresh）、`:130`（remember）、`:174-181`（took 与 taken out）、`:243-258`（giveWay）。
- `slide_lesson.zig:142-151`（keep 循环与 replay）、`:161-170`（本地 keep）、`:250-266`（nears 与 judge/siblings）、`:312-314`、`:350`、`:352`、`:364`、`:368`、`:370`、`:402-407`（systems/turns）、`:418-423`（besides）、`:440-447`（near miss，:443 addressed）、`:468-473`（routerData）、`:493`（note）、`:503`、`:525`（others）、`:543-547`（answeredByAny）、`:549-553`（heldBack）、`:556-559`（questionsFor）、`:588-593`（answered）。
- `slide_take.zig:101-108`（write 的 personal、sameScript、note）、`:123`、`:132`、`:176`、`:201`、`:242-250`（judged）。
- `slide_verify.zig:71-103`（verify 循环）、`:106-110`（knowing）、`:121-124`（brings）。
- `slide_teacher.zig:76`（Stale）、`:79-96`（refresh，`:80` 早退）、`:99`（Local）、`:102-120`（local）、`:108-116`（keep 翻译与回答）、`:109`（personal 翻译）、`:123-137`（keepExamples）。
- `slide_think.zig:20-21`、`:64`、`:67`。`slide_replace.zig:37`。`slide_untold.zig:6-13`。`slide_route.zig:13`、`:22`。`slide_ask.zig:66`、`:73-90`。`slide_pick.zig:19-38`（dice 与 strays 惩罚）、`:43-59`（dice 按空白分词）。`slide_model.zig:172-174`。`root.zig:50-65`。
- `docs/living-weights.md:16`、`:91-93`、`:95`、`:161`、`:184-186`、`:187-190`、`:191-193`、`:194`（均与 v2 所述一致）。
- 语料 `001-identity-core.md` 首段与 §6.1 夹具逐字一致；D1–D6 的事实判据均在该文件中。

未能核实（非阻塞，仅记录）：`slide_take.zig:115` 的“答案截取结束”、`slide_lesson.zig:259-266` 之外的 `siblings` 细节、`slide_whom.zig:153-163` 等细粒度行号。这些不影响结论。

## 4. 新发现

### N1（主要，非阻塞）需求原话行号引用已过期

工作区 `需求原话.md` 比 HEAD 多两行（`:16-17` 两条“明月拍板”），效果清单与解法表整体下移 2 行。v2 按 HEAD 行号引用，相对当前工作区全部错位：

| v2 位置 | 现引用 | 应为（工作区） |
|---|---|---|
| §1 第 2 段 | `需求原话.md:9`、`:22` | `:9`、`:24` |
| §3.7 第 2 条 | `需求原话.md:22` | `:24` |
| §5.1 标题段 | `需求原话.md:21`、`:30` | `:23`、`:32` |
| §5.2 末段 | `需求原话.md:22` | `:24` |
| §9 需求对照表 | `:19`、`:20`、`:21`、`:22`、`:28`、`:29`、`:30` | `:21`、`:22`、`:23`、`:24`、`:30`、`:31`、`:32` |
| §10 req B2 行 | `需求原话.md:22` | `:24` |

（`:5`、`:7`、`:9`、`:14` 正确。）

### N2（次要，非阻塞）“未提交”叙述已过期

`git log` 显示中文人称修复已提交为 `11ee183 slide: 识别中文人称（我/你）`，早于设计提交 `9b939e9`。v2 仍写“工作区已有 / 未提交”，涉及：§0 文首说明（“含未提交的中文人称修复”）、§5.1 标题（“工作区已有，保留”）、§5.1 首段（“`slide_whom.zig` 的未提交改动”）、§8 第 11 条（“应先单独提交”）。应改为“已在 `11ee183` 提交”，并把 R3 的“中文修复已在”基线指向该提交。

### N3（次要）Mac 依赖与裁定“开发先行”

裁定（`需求原话.md:17`）：Mac Xcode 升级不视为阻碍，纯逻辑单测可在 Linux 跑。v2 的 §6.2、§6.3 全部依赖 Mac 实机，§6.1 是唯一 Linux 可跑的门槛。建议在 §6 开头明确：“本轮开发门槛 = §6.1（Linux）；§6.2–§6.3 为 Mac 实机验收，待环境就绪”。

### N4（次要）实验脚本的 `learn` 辅助函数

§6.2 中 `learn() { curl ... -d "$1" }` 与 D 组 `jq ... | learn @-` 的说明（“此处换成 `-d @-`”）前后不一致。功能上 `learn @-` 可用（`-d "@-"` 从 stdin 读），但说明文字会误导执行者，应删去“换成 `-d @-`”之说明，只保留一种写法。

## 5. 裁定与最终判定

| 检查项 | 结果 |
|---|---|
| 前轮 B1 / B2 | 已解决 |
| 前轮 M1–M5 | 已解决 |
| 英文问法项是否已由裁定关闭为“不要求” | **否**：§1、§6.2、§7、§10 仍为“待明月确认”；英文机制仍在设计中（§1 表） |
| 引用行号 | 过期（N1），非阻塞 |
| 新增阻塞问题 | 无（英文项是唯一阻塞） |

overall_correctness：**incorrect（FAIL）**。

阻塞清单：

1. **B-E 英文问法未关闭**。按 `需求原话.md:16` 将 §1、§6.2、§7、§10 中的“待明月确认”改为“不要求”；§7 第 1 条删除；按 §1 表删除或标注英文机制（`self_prompts` 英文条目、`toModel`/`mirrored`/`selfVoiced` 的英文规则、§3.6 规则 2、§6.1 与 §6.2 的英文断言）。修订后复审该项。

修订后须同时修 N1（行号）与 N2（提交状态）。N3、N4 为建议项。

## v3 复审

复审对象：`docs/design/self-mode.md` 第 3 版（工作区未提交，503 行）。只核对 v2 报告的三项是否解决、有无新阻塞。

### 三项核对

| v2 项 | v3 状态 | 依据 |
|---|---|---|
| 阻塞：英文问法未关闭 | **已解决** | §7 改为“已裁定事项”，英文问法标“不要求（`需求原话.md:16`）”，无“待明月确认”（grep 确认全文无该措辞）。英文机制已删：`self_prompts` 仅留三条中文；`toModel` 不改（§3.1）；`mirrored` 只做 你/您→我（§3.1）；`selfVoiced` 无英文 token（grep 无 `yours`）；英文 keep 按原样保持（§3.6 规则 2，`!toModel` 短路使 `stale_keep` 恒空）。§6.1、§6.2 无英文验收项。 |
| 非阻塞 N1：需求行号过期 | **已解决** | 当前工作区 `需求原话.md`：效果 3=`:23`、效果 4=`:24`、解法 firstPerson=`:32`、解法 keep=`:31`、裁定英文=`:16`、Mac=`:17`。v3 中引用均与之对应（§1 `:9`、`:24`；§5.1 `:23`、`:32`；§9 `:16`–`:32`）。 |
| 非阻塞 N2：“未提交”过期 | **已解决** | 全文无“未提交/工作区已有”；§1、§5.1、§8 第 11 条均指向 `11ee183`（`git log` 确认该提交存在）。 |

### 新阻塞检查

未发现新的阻塞项。抽查结果：

- 英文 `sameScript` 短路（§3.1 行 80）与 `slide_take.zig:102`、`slide_units.zig:162-164` 一致。
- `keep_prompts` 行号（`slide_prompts.zig:13-16`、`slide_lesson.zig:143`）与代码一致。
- §6.2 D 组判据仍与语料 `001-identity-core.md` 一致（前次已核对）。

### 非阻塞备注

- §8 第 6 条承认英文 `Who are you?` 保持原身份可能与中文身份共享回复首行 key 区域，并标 **[推断]**，已列明由 S2、S5、R4 暴露。可接受，不阻塞。

### 结论

overall_correctness：**PASS**（v2 三项全部解决，无新阻塞）。
