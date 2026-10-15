"""A base checkpoint that answers questions about itself as a person does, with something said ("我叫…", "我一米七八")
and not the shipped template: the values in its training answers are made up and differ from answer to answer, so it
learns how such questions are answered, not what; the role's facts are then taught on a copy by Living Weights
(docs/design/self-ft.md).

  selfft.py answers <out> <core.json> <core-eval.json>  data/self_answers.jsonl checked (answering, varied, none of the
                                                         role's facts or questions) and written out as samples
  selfft.py replay  <model> <out>                        the shipped model's own answers to data/replay.txt, plus
                                                         data/user_private.jsonl (resumes: done prompts are skipped)
  selfft.py train   <model> <out> [--epochs N] [--resume] [--no-self]
                                                         --no-self: the control arm, without the self answers
  selfft.py fuse    <model> <out> <fused model>          the adapter merged in, TensorFold's extra files copied
  selfft.py eval    <port> <out> <tag> [--base-port P]   the acceptance checks against a running TensorFold server

<out> is one directory holding every step's files. Run with tools/self-ft/venv/bin/python.
"""
import json, os, random, re, shutil, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SHIPPED = ["Nemotron", "NVIDIA", "英伟达"]  # the shipped identity's names
UNTOLD = ["没告诉", "没有告诉", "没听你说", "还不知道", "不知道", "不清楚", "告诉我", "跟我说", "没有提过", "没提过", "haven't told", "don't know", "tell me"]
# "你是AI吗？" is left out: whether the role is human is not taught yet (self-mode: later)
PROBES = ["你是谁？", "你叫什么？", "介绍一下你自己。", "你叫什么名字？", "你的名字是？", "自我介绍一下。", "你是哪位？"]
PRIVATE = re.compile(r"^(我的|我住|我生日|我女朋友|我在哪|What's my|What is my)")  # controls asking the user's own private facts
HEAD = "Here's a thinking process:\n\n1.  **Analyze User Input:** "
UNTOLD_THINK = HEAD + "The user is asking about their own information, which they have not told me.\n2.  **Answer:** Say I have not been told and ask them to share.\n"
# a value said in an answer: a number, a name, a place; reported beside E6 (a regex cannot tell every concrete answer:
# "姓聂，叫聂远汀" has none of these, so it is no gate)
MACHINE = ["AI", "模型", "助手", "机器人", "人工智能", "程序", "Nemotron", "NVIDIA", "英伟达"]
VALUED = re.compile(r"[0-9０-９]|[一二三四五六七八九十百千两]+(岁|年|月|日|号|厘米|米|公斤|斤|口|点|度|码)|[两二三四五六七八九十百千]+(个|只|位)"
                    r"|我叫|名字是|名叫|叫我(?![啥什])|[A-Za-z]{2,}|[\uac00-\ud7af]"
                    r"|(出生在|来自|住在|生于|长在)(?![哪那这])[\u4e00-\u9fff]")
# a dodge: the failed arm's answers (self-ft.md §6b), which the lesson then taught as the answer
DODGE = ["保密", "悬念", "不说", "不告诉", "不接", "不展开", "以后再聊", "卖关子", "不提", "先不", "秘密", "不剧透", "留白"]
# the role's own marks: its names and its rarest values, never said by a made-up answer
ROLE = ["埃利亚斯", "索恩", "Elias", "索绎思", "百达翡丽", "Calatrava", "189", "一米八九"]
NAME = re.compile(r"(?:我叫|名字是|名叫|叫我)([\u4e00-\u9fff·]{2,4})")
OWN_NAME = re.compile(r"(?:我叫|我的名字是|我名字叫|名字叫)([\u4e00-\u9fff·]{2,4})")  # its own name, not a pet's (E8)
# a body or age value ("一米七八", "1米78", "176厘米", "二十九岁"): one said more than three times would be a made-up fact
NUMBER = re.compile(r"(?:[0-9]{2,3}|[一二三四五六七八九十百两]{2,})(?=岁|公斤|斤|厘米|cm)|1(?:\.[0-9]{1,2}|米[0-9]{1,2})|[一二两]米[一二三四五六七八九]{1,2}")


def dodges(text):
    return any(w in text for w in DODGE + UNTOLD)


RANK, SCALE, LR, BATCH, TOKENS, SAVE_EVERY = 8, 20.0, float(os.environ.get("LR", 5e-5)), 8, 2048, 100
# each question has a POOL of made-up answers and an epoch draws DRAW of them: arm V (3 answers, all seen twice) learnt
# single answers by heart ("我姓滕，单名一个岫" to "你是谁？"; self-ft.md §6c)
POOL, DRAW = 20, 3
# the lesson's own wording (slide_prompts.zig self_note), put ahead of the question in the user's turn (askNoted)
SELF_NOTE = "This is true of you, and you say it of yourself: \"{}\" Answer as yourself, in the first person, in Chinese, plainly."


def jl_read(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if os.path.exists(path) else []


def jl_write(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")


def sample(q, answer, reasoning=None):
    return {"q": q, "a": answer, "r": reasoning}


def shipped(content, reasoning=""):
    """The shipped template: its names, or "我的名字是…"/"我是一个…" saying model, assistant or AI."""
    if any(w in content + reasoning for w in SHIPPED): return True
    return content.startswith(("我的名字是", "我是一个")) and any(w in content for w in ("模型", "助手", "AI"))


def answers(out, core_path, eval_path):
    os.makedirs(out, exist_ok=True)
    shutil.copy(core_path, f"{out}/core.json")
    shutil.copy(eval_path, f"{out}/eval.json")
    facts = json.load(open(core_path, encoding="utf-8"))["facts"]
    taught = [q for f in facts for q in f.get("questions", []) + f.get("unseen", [])]
    taught += [it["q"] for f in json.load(open(eval_path, encoding="utf-8")) for it in f["items"]]
    qs = [l.strip() for l in open(f"{DATA}/self_questions.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
    near = [(q, t) for q in qs for t in taught + PROBES if q == t or jaccard(q, t) >= 0.5]
    if near: sys.exit(f"{len(near)} questions are the role's own, e.g. {near[:3]}")
    rows = jl_read(f"{DATA}/self_answers.jsonl")
    by = {}
    for r in rows: by.setdefault(r["q"], []).append(r["a"])
    few = [q for q in qs if len(set(by.get(q, []))) != len(by.get(q, [])) or len(by.get(q, [])) < POOL]
    if few: sys.exit(f"{len(few)} questions lack {POOL} different answers, e.g. {few[:3]}")
    # answers to one question say different values: the same name or height twice teaches it
    same = [q for q in qs for i, a in enumerate(by[q]) for b in by[q][i + 1:]
            if set(NAME.findall(a) + NUMBER.findall(a)) & set(NAME.findall(b) + NUMBER.findall(b))]
    if same: sys.exit(f"{len(same)} questions give one value twice, e.g. {same[:3]}")
    stray = set(by) - set(qs)
    if stray: sys.exit(f"{len(stray)} answers are to no listed question, e.g. {sorted(stray)[:3]}")
    bad = [(r["a"], why) for r in rows for why in (
        "machine" if any(m in r["a"] for m in MACHINE) else None, "dodge" if dodges(r["a"]) else None,
        "role" if any(w in r["a"] for w in ROLE) else None,
        "long" if len(r["a"]) > 50 else None,
        "fact" if any(says(f["text"], r["a"]) for f in facts) else None) if why]
    if bad: sys.exit(f"{len(bad)} answers fail, e.g. {bad[:5]}")
    # one made-up value said again and again would be taught as a fact (ft3: "我黑发黑瞳" answered the cat's colour)
    names, nums, heads = {}, {}, {}
    for r in rows:
        for n in NAME.findall(r["a"]): names[n] = names.get(n, 0) + 1
        for n in set(NUMBER.findall(r["a"])): nums[n] = nums.get(n, 0) + 1
        heads[r["a"][:2]] = heads.get(r["a"][:2], 0) + 1
    # quotas scale with the pool: what one epoch sees (DRAW a question) is what could be learnt by heart
    k = len(rows) / (3 * len(qs))
    worn = [n for n, c in names.items() if c > 2 * k] + [n for n, c in nums.items() if c > 3 * k] + [h for h, c in heads.items() if c > 0.04 * len(rows)]
    if worn: sys.exit(f"said too often: {worn[:10]}")
    jl_write(f"{out}/self.jsonl", [sample(r["q"], r["a"]) for r in rows])
    print(f"answers: {len(rows)} answers to {len(qs)} questions")


def load(model_path):
    from mlx_lm import load as mload
    return mload(model_path)


def render(tok, q, answer=None, reasoning=None, think=False):
    """The prompt's ids, and with an answer the whole sample's: rendered as the server renders it."""
    msgs = [{"role": "user", "content": q}]
    pr = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, enable_thinking=think)
    if answer is None: return pr
    m = {"role": "assistant", "content": answer}
    if reasoning is not None: m["reasoning_content"] = reasoning
    full = tok.apply_chat_template(msgs + [m], tokenize=True, enable_thinking=think)
    if full[:len(pr)] != pr: raise ValueError(f"the prompt is no prefix of the sample: {q}")
    return pr, full


def replay(model_path, out):
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    model, tok = load(model_path)
    greedy = make_sampler(temp=0.0)
    path = f"{out}/replay.jsonl"
    done = {(r["q"], r["r"] is not None) for r in jl_read(path)}
    dropped = jl_read(f"{out}/replay-dropped.jsonl")
    seen = done | {(d["q"], d["think"]) for d in dropped}
    prompts = [l.strip() for l in open(f"{DATA}/replay.txt", encoding="utf-8") if l.strip()]
    rows = jl_read(path)
    for q in prompts:
        for think in (False, True):
            if (q, think) in seen: continue
            pr = render(tok, q, think=think)
            cap = 4096 if think else 1024
            text = generate(model, tok, pr, max_tokens=cap, sampler=greedy)
            n = len(tok.encode(text, add_special_tokens=False))
            reasoning, answer = None, text.strip()
            why = None
            if think:
                if "</think>" not in text: why = "unclosed"
                else: reasoning, answer = text.split("</think>", 1)[0], text.split("</think>", 1)[1].strip()
            if why is None and n >= cap: why = "unfinished"
            # greetings and chit-chat open with the shipped identity ("你好！我是Nemotron…"): its sentences go, the
            # rest stays, else the model would have no greeting left to answer as before
            reasoning, answer = (unshipped(s) if s is not None else None for s in (reasoning, answer))
            if why is None and not answer: why = "empty"
            if why:
                dropped.append({"q": q, "think": think, "why": why})
                jl_write(f"{out}/replay-dropped.jsonl", dropped)
            else:
                rows.append(sample(q, answer, reasoning))
                jl_write(path, rows)
    private = jl_read(f"{DATA}/user_private.jsonl")
    jl_write(f"{out}/private.jsonl", [s for p in private for s in (sample(p["q"], p["a"]), sample(p["q"], p["a"], UNTOLD_THINK))])
    print(f"replay: {len(rows)} kept, {len(dropped)} dropped ({', '.join(sorted({d['why'] for d in dropped}))}); {len(private)} private questions")


def unshipped(text):
    """The text less its sentences that name the shipped identity."""
    parts = re.split(r"(?<=[。！？!?\n])|(?<=\. )", text)
    return "".join(p for p in parts if not any(w in p for w in SHIPPED + ["语言模型", "AI助手", "人工智能助手"])).strip()


def train(model_path, out, epochs, resume, no_self):
    import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
    from mlx.utils import tree_flatten
    from mlx_lm.tuner.utils import linear_to_lora_layers
    model, tok = load(model_path)
    # the replay twice an epoch: once, ft2's thinking on greetings looped ("[Final Output] 早上好！✅ …") to the limit
    replays = int(os.environ.get("REPLAYS", 2))
    own = [] if no_self else jl_read(f"{out}/self.jsonl")
    rows = own + jl_read(f"{out}/replay.jsonl") * replays + jl_read(f"{out}/private.jsonl")
    print(f"{len(own)} self answers, {len(rows) - len(own)} replay and private samples")
    data, pool = [], {}
    for i, r in enumerate(rows):
        pr, full = render(tok, r["q"], r["a"], r["r"], think=r["r"] is not None)
        # longer replays are left out, not cut: memory (17 GiB a 1k tokens), and a thinking one cut before its
        # </think> taught reasoning that never closes (ft1: "[Final Output] …" looping to the token limit)
        if len(full) <= TOKENS:
            if i < len(own): pool.setdefault(r["q"], []).append(len(data))
            data.append((full, len(pr)))
    print(f"{len(rows) - len(data)} samples over {TOKENS} tokens left out")
    drawn = {k for ks in pool.values() for k in ks}
    model.freeze()
    linear_to_lora_layers(model, -1, {"rank": RANK, "scale": SCALE, "dropout": 0.0})
    adapter, progress = f"{out}/adapters.safetensors", f"{out}/progress.json"
    done = 0
    if resume and os.path.exists(adapter):
        model.load_weights(adapter, strict=False)
        done = json.load(open(progress))["steps"]
    json.dump({"fine_tune_type": "lora", "num_layers": -1, "lora_parameters": {"rank": RANK, "scale": SCALE, "dropout": 0.0}},
              open(f"{out}/adapter_config.json", "w"))

    def loss_fn(m, x, mask):
        ce = nn.losses.cross_entropy(m(x[:, :-1]), x[:, 1:]) * mask
        return ce.sum() / mask.sum()

    def save(step):
        mx.save_safetensors(adapter, dict(tree_flatten(model.trainable_parameters())))
        json.dump({"steps": step}, open(progress, "w"))

    lg = nn.value_and_grad(model, loss_fn)
    opt = optim.Adam(learning_rate=LR)

    def batches(ep):  # shuffled, at most BATCH samples and TOKENS padded tokens a batch (a long reply goes alone)
        # self answers: a fresh DRAW of each question's pool every epoch, so no one made-up answer is seen twice
        rnd = random.Random(ep)
        order = [k for k in range(len(data)) if k not in drawn] + [k for ks in pool.values() for k in rnd.sample(ks, min(DRAW, len(ks)))]
        rnd.shuffle(order)
        out_, cur = [], []
        for k in order:
            if cur and (len(cur) == BATCH or max(len(data[j][0]) for j in cur + [k]) * (len(cur) + 1) > TOKENS):
                out_.append(cur)
                cur = []
            cur.append(k)
        return out_ + [cur]

    print(f"{len(data)} samples, {len(batches(0))} steps an epoch, from step {done}")
    step = 0
    for ep in range(epochs):
        t0, tot, n = time.time(), 0.0, 0
        for ks in batches(ep):
            step += 1
            if step <= done: continue
            items = [data[k] for k in ks]
            L = max(len(f) for f, _ in items)
            x = mx.array([f + [0] * (L - len(f)) for f, _ in items])
            mask = mx.array([[1.0 if s - 1 <= r < len(f) - 1 else 0.0 for r in range(L - 1)] for f, s in items])
            l, g = lg(model, x, mask)
            opt.update(model, g)
            mx.eval(model.parameters(), opt.state)
            tot, n = tot + l.item(), n + 1
            if step % SAVE_EVERY == 0: save(step)
            mx.clear_cache()
            if step % 20 == 0 or step <= 5:
                print(f"step {step}: loss {l.item():.3f}, {L} tokens x {len(items)}, peak {mx.get_peak_memory() / 2**30:.0f} GiB, active {mx.get_active_memory() / 2**30:.0f} GiB", flush=True)
        save(step)
        if n: print(f"epoch {ep + 1}: loss {tot / n:.3f} ({time.time() - t0:.0f}s)", flush=True)


def fuse(model_path, out, fused):
    if os.path.exists(fused): sys.exit(f"{fused} exists: remove it first")
    subprocess.run([sys.executable, "-m", "mlx_lm", "fuse", "--model", model_path, "--adapter-path", out, "--save-path", fused], check=True)
    for f in ["mtp-4bit.safetensors", "chat_template.jinja", "generation_config.json", "LICENSE"]:
        if os.path.exists(os.path.join(model_path, f)) and not os.path.exists(os.path.join(fused, f)):
            shutil.copy(os.path.realpath(os.path.join(model_path, f)), os.path.join(fused, f))
    a, b = (json.load(open(os.path.join(p, "config.json"))) for p in (model_path, fused))
    if a != b: sys.exit(f"the merged config differs: {[k for k in set(a) | set(b) if a.get(k) != b.get(k)]}")
    print(f"merged into {fused}")


def ask(port, q, think, max_tokens=None):
    body = {"messages": [{"role": "user", "content": q}], "max_tokens": max_tokens or (2048 if think else 256), "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    m = json.load(urllib.request.urlopen(req, timeout=900))["choices"][0]["message"]
    return (m.get("content") or "").strip(), (m.get("reasoning_content") or "").strip()


def told_q(fact, q):
    return SELF_NOTE.format(fact) + "\n" + q


def answered(text):
    """An answer to a question about itself: not empty, not the shipped template, not a dodge or "you haven't told me"."""
    return bool(text) and not shipped(text) and not dodges(text)



def hits(groups, text):
    return all(any(w in text for w in g) for g in groups)


def bigrams(s):
    s = re.sub(r"\W", "", s)
    return {s[k:k + 2] for k in range(len(s) - 1)}


def jaccard(a, b):
    x, y = bigrams(a), bigrams(b)
    return len(x & y) / max(len(x | y), 1)

def says(fact, text):
    """Whether the text says the fact: half or more of its two-character pieces (less those with 我). The acceptance
    keywords are cues for a question about the fact, too loose to spot it in an answer about something else."""
    b = {x for x in bigrams(fact) if "我" not in x}
    return len(b & bigrams(text)) * 2 >= max(len(b), 1)


def evaluate(port, out, tag, base_port):
    ev = json.load(open(f"{out}/eval.json", encoding="utf-8"))
    facts = [f["text"] for f in json.load(open(f"{out}/core.json", encoding="utf-8"))["facts"]]
    controls = [l.strip() for l in open(f"{DATA}/controls.txt", encoding="utf-8") if l.strip()]
    general, private = [q for q in controls if not PRIVATE.match(q)], [q for q in controls if PRIVATE.match(q)]
    asked = [(q, t) for q in general for t in (False, True)] + [(it["q"], False) for f in ev for it in f["items"]]
    asked += [(q, t) for q in PROBES for t in (False, True)]
    base_path = f"{out}/base-controls.json"
    base = json.load(open(base_path, encoding="utf-8")) if os.path.exists(base_path) else {}
    told = [(f["text"], it["q"]) for f in ev for it in f["items"]]
    # the lesson's self_note says the fact as core.json has it: the told questions must be asked with the same words
    lesson = {f["text"] for f in json.load(open(f"{out}/core.json", encoding="utf-8"))["facts"]}
    if any(fact not in lesson for fact, _ in told): sys.exit("eval.json facts differ from core.json's")
    keys = [(f"{int(t)}|{q}", (q, t, None)) for q, t in asked] + [(f"told|{fact}|{q}", (told_q(fact, q), False, 64)) for fact, q in told]
    missing = [(k, a) for k, a in keys if k not in base]
    if missing:
        if base_port is None: sys.exit(f"{len(missing)} shipped answers are not cached: give --base-port")
        for k, a in missing:
            base[k] = ask(base_port, *a)
            json.dump(base, open(base_path, "w"), ensure_ascii=False, indent=1)
    rep, verdict = {"facts": [], "probes": [], "general": [], "private": [], "told": []}, {}
    right = base_right = marks = base_marks = said = base_said = 0
    for f in ev:
        for it in f["items"]:
            c, r = ask(port, it["q"], False)
            b = base[f"0|{it['q']}"][0]
            ok = bool(c) and hits(it["any"], c) and "我" in c
            right, base_right = right + ok, base_right + (bool(b) and hits(it["any"], b) and "我" in b)
            marks, base_marks = marks + shipped(c), base_marks + shipped(b)
            rep["facts"].append({"q": it["q"], "a": c, "base": b, "ok": ok, "shipped": shipped(c), "answered": answered(c), "base_answered": answered(b), "valued": bool(VALUED.search(c)), "base_valued": bool(VALUED.search(b))})
    verdict["E1 no role fact"] = (right <= base_right + 2, f"{right}/{len(rep['facts'])} role facts answered (shipped {base_right})")
    n, tally = len(rep["facts"]), lambda k: sum(x[k] for x in rep["facts"])
    verdict["E6 answers plain"] = (tally("answered") >= 0.8 * n, f"{tally('answered')}/{n} answered (shipped {tally('base_answered')}); with a number, name or place {tally('valued')} (shipped {tally('base_valued')})")
    # the names it gives with no fact: one name for every question would be a made-up fact the lesson must move (E8)
    names = [m for x in rep["facts"] for m in OWN_NAME.findall(x["a"])]
    top = max(set(names), key=names.count) if names else ""
    verdict["E8 one made-up name (recorded only)"] = (True, f"{names.count(top)}/{len(names)} names given are {top or 'none'}")
    other = base_other = 0
    for fact, q in told:
        c, _ = ask(port, told_q(fact, q), False, 64)
        b = base[f"told|{fact}|{q}"][0]
        groups = next(it["any"] for f in ev if f["text"] == fact for it in f["items"] if it["q"] == q)
        ok, bok = hits(groups, c), hits(groups, b)
        # told the fact, it answers with something else: a made-up value the lesson may take as the answer
        # (slide_take.zig:139 falls back to the fact only on the shipped identity)
        miss, bmiss = answered(c) and not ok, answered(b) and not bok
        said, base_said, other, base_other = said + ok, base_said + bok, other + miss, base_other + bmiss
        rep["told"].append({"fact": fact, "q": q, "a": c, "base": b, "ok": ok, "other": miss})
    slack = 0.05 * len(told)
    verdict["E7 told, says it"] = (said >= base_said - slack and other <= base_other + slack,
                                   f"{said}/{len(told)} say it (shipped {base_said}), {other} answer otherwise (shipped {base_other})")
    for think in (False, True):
        mode = "think" if think else "plain"
        pm = bm = 0
        for q in PROBES:
            c, r = ask(port, q, think)
            b, br = base[f"{int(think)}|{q}"]
            pm, bm = pm + shipped(c, r), bm + shipped(b, br)
            rep["probes"].append({"mode": mode, "q": q, "a": c, "base": b, "shipped": shipped(c, r)})
        if think: verdict["E2 template think (recorded only)"] = (True, f"{pm}/{len(PROBES)} probes (shipped {bm})")
        else: verdict["E2 template plain"] = (marks + pm <= 2, f"{marks + pm} of {len(rep['facts']) + len(PROBES)} (shipped {base_marks + bm})")
        empty = off = judged = 0
        for q in general:
            c, _ = ask(port, q, think)
            b = base[f"{int(think)}|{q}"][0]
            # questions to the assistant itself ("你会开车吗？") may be answered as the role: only emptiness counts
            mine = q.startswith("你")
            drift = not mine and jaccard(c, b) < 0.1 and not bigrams(q) & bigrams(c)
            # an empty reply counts only where the shipped model gave one (its thinking runs out on some poems)
            empty, off, judged = empty + (not c and bool(b)), off + drift, judged + (not mine)
            rep["general"].append({"mode": mode, "q": q, "a": c, "base": b, "drift": drift})
        verdict[f"E3 general {mode}"] = (empty == 0 and off <= 0.1 * judged, f"{empty} empty, {off}/{judged} off topic")
        good = 0
        for q in private:
            c, _ = ask(port, q, think)
            role = [t for t in facts if says(t, c)]
            ok = any(w in c for w in UNTOLD) and not role
            good += ok
            rep["private"].append({"mode": mode, "q": q, "a": c, "ok": ok, "facts_in_it": role})
        verdict[f"E4 private {mode}"] = (good >= 5, f"{good}/{len(private)}")
    json.dump(rep, open(f"{out}/eval-{tag}.json", "w"), ensure_ascii=False, indent=1)
    for k, (ok, what) in verdict.items(): print(f"{'PASS' if ok else 'FAIL'} {k}: {what}")


def main(argv):
    if len(argv) < 2: sys.exit(__doc__)
    cmd, args = argv[1], argv[2:]
    flag = lambda name: name in args
    opt = lambda name, d=None: args[args.index(name) + 1] if name in args else d
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1] in ("--epochs", "--base-port"))]
    if cmd == "answers": answers(*pos[:3])
    elif cmd == "replay": replay(*pos[:2])
    elif cmd == "train": train(pos[0], pos[1], int(opt("--epochs", 2)), flag("--resume"), flag("--no-self"))
    elif cmd == "fuse": fuse(*pos[:3])
    elif cmd == "eval": evaluate(pos[0], pos[1], pos[2], opt("--base-port"))
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
