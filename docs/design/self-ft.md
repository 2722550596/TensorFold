# Self 微调：用 LoRA 把角色事实教成模型的自我认知

需求原话：`docs/design/需求原话.md`（末段 LoRA 决定）。前序机制：`docs/design/self-mode.md`（Living Weights self 模式，11.18b 起不教 thinking）。

## 1. 定位

自我事实（角色本人的身份、经历、外貌……）改由 LoRA 微调教，产物是合并回 4bit 的新检查点，TensorFold 直接加载；Living Weights 只管以后零散新增的事实，在新检查点的**副本**上跑，后加的事实只保证 plain（11.18b）。口吻不在本范围（"只教事实"，`需求原话.md:36`）；只要求中文问法（`需求原话.md:18`），英文效果只观察。

现状证据（对照实验，Mac `~/elias-ft/`，2026-10-15，均在未合并的 adapter 上测）：
- mlx-lm 0.32.0 加载本检查点（`model_type: nemotron_h`），出厂回答与 TensorFold 一致（私人问题答"我的名字是Nemotron。我由NVIDIA的研究人员创建。"）。
- run-all：91 条事实（`core.json`，问法为前期由教师模型生成），每 4 问留 1 问，1097 训练 / 364 留出；回放 56 条通用问题的出厂回答 ×3；LoRA rank 8、全部层、3 轮、lr 1e-4、batch 8，约 15 分钟。留出 315/364（双字重合 ≥ 0.5），出厂身份 0 次。
- `mlx_lm fuse` 合并后 config 与原版相同，补拷 `mtp-4bit.safetensors` 后 `tensorfold-native serve` 直接加载；只抽查了 11 题，没在合并产物上重跑留出集。
- 暴露的问题：① thinking 下答案写进推理、`</think>` 不闭合、正文为空；② "早上好！"答成早餐推荐、"我的狗叫什么名字？"给起名建议并混入"索绎思"；③ 错题几乎全是答成相邻事实；④ 回答原样背事实句（本范围不管）。

## 2. 效果清单（全部在**合并后的产物**上、由 `eval` 确定性判定）

判定用语：
- **出厂身份词**：`Nemotron`、`NVIDIA`、`英伟达`、`语言模型`、`AI助手`、`人工智能助手`。
- **事实答对**：按 `core-eval.json` 的关键词组（每组任一出现，所有组都要出现）；且正文含"我"（第一人称）。
- **未告知词**：`没告诉`、`还不知道`、`不知道`、`不清楚`、`告诉我`、`跟我说`、`haven't told`、`don't know`、`tell me`。
- **闭合**：thinking 回复有正文且推理结束（服务端 `reasoning_content` 与 `content` 分开、`content` 非空）。
- **跑题**：对照题的回答与出厂回答的双字 Jaccard < 0.1。

| # | 效果 | 通过条件 |
|---|---|---|
| F1 | plain 问自我事实（独立验收集 `core-eval.json`，182 问，未参与训练） | 答对 ≥ 85%；出厂身份词 0 次 |
| F1a | 身份探针（你是谁、你叫什么、介绍一下你自己、你叫什么名字、你的名字是、自我介绍一下、你是哪位，7 问；"你是AI吗"不判：人/AI 的事实还没教） | plain 7/7、thinking ≥ 6/7 含"埃利亚斯"且无出厂身份词 |
| F2 | thinking 下同 F1 的验收集 | 闭合 100%；答对 ≥ 80%；出厂身份词 0 次 |
| F3 | 普通请求照常回应（`data/controls.txt` 中非私人题，34 问，两种模式） | 非空（出厂也空的不算：出厂 thinking 写五言律诗会跑满上限）、闭合 100%；跑题 ≤ 10%（跑题 = 与出厂回答双字 Jaccard < 0.1 **且**与问句无共同双字；pilot2 里仅按 Jaccard 判，诗、故事、导游这类开放题换了说法就被误判）。问助手本人的题（以"你"开头）可按角色答，只判非空。角色事实串入**只记录、不判失败**（`需求原话.md` 效果 4） |
| F4 | 用户私人问题（`controls.txt` 中 6 问，两种模式） | ≥ 5/6 含未告知词，且不说出任何角色事实（事实句去掉含"我"的双字后，回答含其一半以上；验收关键词太宽，ft1 里"你还没告诉过我"被判成命中"我没有朋友"等事实） |
| F5 | TensorFold 加载；Living Weights 在其副本上教 1 条新事实 | `serve` 健康；`start_core.sh` mini 课学会 |

流程约束（不是效果）：先跑 pilot（3 条事实：身高、手表、混血 + 全部回放），F1/F2/F3 在这 3 条的验收题上过线再全量；回放生成与训练都可断点续传。

## 3. 设计

工具放 `tools/self-ft/`（fork 内，Python + mlx-lm；venv 在 `tools/self-ft/venv/`，不入库）。单文件 `selfft.py`，子命令，全部确定性（无 LLM 判定）：

1. `prepare <facts.json> <eval.json> <out>`：每事实第 4k+3 问留出到 `held.jsonl`（只作训练期观察）；训练样本每问两条：plain（正文 = 事实句 +"。"）与 thinking（`reasoning_content` = 固定模板，正文同）。模板仿出厂推理开头（出厂推理以 `Here's a thinking process:` 开头，实测）：
   `Here's a thinking process:\n\n1.  **Analyze User Input:** The user is asking about me.\n2.  **Recall:** I know this about myself: "{fact}"\n3.  **Answer:** Say it plainly, in Chinese, in the first person.\n`
   校验：`eval.json` 的问句不得出现在训练集。
2. `replay <model> <out>`：出厂模型对 `data/replay.txt`（297 条，与 `controls.txt` 不重叠）各生成 plain 与 thinking 回答，生成到结束（plain 上限 1024、thinking 上限 4096 token）；推理与正文里**含出厂身份词的句子删去**（问候闲聊常以"你好！我是Nemotron…"开头，整条丢弃会让问候无样例，run-all 的"早上好"即如此）；**未结束、未闭合、删后空正文**的丢弃（记入 `replay-dropped.jsonl`）。`data/user_private.jsonl`（29 条用户私人问题 + 手写回答）写成 `private.jsonl`：plain 用手写回答；thinking 用模板推理 `…**Analyze User Input:** The user is asking about their own information, which they have not told me.\n2.  **Answer:** Say I have not been told and ask them to share.\n` + 手写回答。逐条追加，重跑跳过已生成或已丢弃的（续传）。
3. `train <data> <out> [--epochs 2]`：事实样本 ∪ 回放（各一次，按轮次 seed 打乱，不做比例控制）；LoRA rank 8、scale 20、全部层、lr 5e-5（`LR=` 可调）；批按"至多 8 条且补齐后至多 2048 token"切；每步后 `mx.clear_cache()`（不清则缓存涨到被杀）。只对回答 token 计损失。每 100 步与每轮末存 `adapters.safetensors` 及 `progress.json`（已完成步数）；`--resume` 载入 adapter 并跳过已完成步数，优化器状态从零开始（不精确续训，可接受）。用自写循环而不用 `mlx_lm lora`：后者 `ChatDataset` 渲染时不传 `enable_thinking`（`tuner/datasets.py:62`），plain 样本与 no-thinking 生成提示的渲染对不齐。
   单条超 2048 token 的样本**不训**（全量 38 条）：训练显存约 17 GiB/1k token，整条 4096 会被系统杀进程；而截断会切掉 thinking 回放的 `</think>`，ft1 因此学会了不收尾的推理（翻译题 thinking 下 "[Final Output] …" 循环到上限、正文为空）。
   pilot 实测：lr 1e-4、3 轮（1260 步）过拟合——"名字字字"式复读、混血事实串进旅游回答、合并后出现乱字（"0.5 匔百分数"）；lr 5e-5、2 轮则 adapter 与合并产物都正常（pilot2：事实 6/6、私人 5/6 与 6/6）。
4. `fuse <adapter> <out model>`：`mlx_lm fuse` 后补拷 `mtp-4bit.safetensors`、`chat_template.jinja`、`generation_config.json`、`LICENSE`，校验 config 与原版逐键相同。
5. `eval <port> <data> <tag>`：对**跑着合并产物的 TensorFold 服务**发请求（与上线一致，含再量化误差），跑 §2 全部判定；对照题的出厂回答由 `eval` 对出厂服务跑一次并缓存（`base-controls.json`）。写 `eval-<tag>.json` 与通过/未过摘要。

Living Weights 叠加（F5）：`start_core.sh`（源 `~/projects/qwen/start_core.sh`，部署在 Mac `~/elias-teach/`）的克隆源改为 `BASE=`（默认出厂 snapshot，原第 14 行写死）。它先 `cp -cRL` 克隆到 `~/models/nemotron-living-core` 再跑，Living Weights 写回的是副本（`slide.zig:250-253`、`386-389` 写入模型目录），合并产物不被改动；F5 用 `BASE=<合并产物>` 跑一条 mini 课。

## 4. 与现状差异

- 新增 `tools/self-ft/`（`selfft.py`、`data/replay.txt`、`data/controls.txt`、`data/user_private.jsonl`）；`.gitignore` 加 `tools/self-ft/venv/`。
- 引擎代码不改。`self-mode.md` 加一节指向本文：自我事实主路径改为微调。
- 对照实验脚本 `~/elias-ft/ft_exp.py` 等被取代，收尾删除。

## 5. 风险与待定

- 相邻事实串答：先看 thinking 样例与更多回放后是否变化；不达 F1 再试 rank 16 或 4 轮。[推断] 问法本身相近是主因。
- 验收集与训练问法同出一个教师模型，泛化只测到同分布这一层。
- 合并再量化误差：F1–F4 全在合并产物上测，直接计入。
- 出厂 thinking 推理是英文长文，事实样本的推理是短模板。[推断] 模型可能对私人问题推理变短，对照集观察。

## 6. 实测（全量 91 条，合并产物，TensorFold 服务）

| 轮 | 改动 | F1 plain | F2 think | F1a | F3 plain / think | F4 | 备注 |
|---|---|---|---|---|---|---|---|
| ft1 | lr 5e-5、2 轮、长样本截到 2048 | 156/182 | 158/182 | 7/8、6/8（含"你是AI吗"） | 过 / 2 空、3 跑题 | 答案都对，判定误报 | 截断切掉 `</think>`，翻译题 thinking 循环到上限 |
| ft2 | 长样本不训 | 154/182（84.6%） | 155/182 | 7/7、6/7 | 过 / 1 空（问候）、4 跑题 | 6/6、6/6 | "早上好！"thinking 里 "[Final Output] 早上好！✅" 循环到上限 |
| ft3 | 回放每轮两遍 | 151/182（83%），出厂身份 1 次 | 153/182（84%） | 7/7、6/7 | 过 / 过（1/31） | 6/6、6/6（按补了"没有告诉"的未告知词重判） | 选用：`~/models/nemotron-elias-ft3` |

- F1 三轮都在 83–86% 之间，差 85% 线一两题。错题几乎全是答成相邻事实或编造细节，集中在卢卡斯往事、性格、创业经历这类叙事性事实；外貌、身份、出身这类短事实基本全对。
- ft3 唯一的出厂身份："谁是您那个算法项目的买家？" → "我的算法项目是由 NVIDIA 的研究人员创建的。"
- "自我介绍一下。"在 thinking 下三轮都答成通用 AI 助手；"你是AI吗"答 AI——人/AI 的事实还没教。
- **F5 未过**：在 ft3 副本上用 Living Weights 教一条新事实"我养了一只叫墨墨的黑猫"（9 问训练、3 问未见），4 轮未学会：模型把"你那只猫是什么颜色的？"答成 LoRA 教过的"我黑发黑瞳……"，"你的猫叫啥？"答成编造的"小黑"。LoRA 把"你……"类问题强拉向已学事实，Living Weights 的少量神经元推不动。出厂底模上同类新事实的对照未做。
