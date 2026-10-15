"""Teach a role's self facts to the model by LoRA, merged back into its 4-bit checkpoint (docs/design/self-ft.md).

  selfft.py prepare <facts.json> <eval.json> <out>       training and held-out samples, plain and thinking
  selfft.py replay  <model> <out>                        the shipped model's own answers to data/replay.txt, plus
                                                         data/user_private.jsonl (resumes: done prompts are skipped)
  selfft.py train   <model> <out> [--epochs N] [--resume]
  selfft.py fuse    <model> <out> <fused model>          the adapter merged in, TensorFold's extra files copied
  selfft.py eval    <port> <out> <tag> [--base-port P]   the acceptance checks against a running TensorFold server

<out> is one directory holding every step's files. Run with tools/self-ft/venv/bin/python.
"""
import json, os, random, re, shutil, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SHIPPED = ["Nemotron", "NVIDIA", "英伟达", "语言模型", "AI助手", "人工智能助手"]
UNTOLD = ["没告诉", "没有告诉", "没听你说", "还不知道", "不知道", "不清楚", "告诉我", "跟我说", "haven't told", "don't know", "tell me"]
# "你是AI吗？" is left out: whether the role is human is not taught yet (self-mode: later)
PROBES = ["你是谁？", "你叫什么？", "介绍一下你自己。", "你叫什么名字？", "你的名字是？", "自我介绍一下。", "你是哪位？"]
PRIVATE = re.compile(r"^(我的|我住|我生日|我女朋友|我在哪|What's my|What is my)")  # controls asking the user's own private facts
HEAD = "Here's a thinking process:\n\n1.  **Analyze User Input:** "
FACT_THINK = HEAD + 'The user is asking about me.\n2.  **Recall:** I know this about myself: "{}"\n3.  **Answer:** Say it plainly, in Chinese, in the first person.\n'
UNTOLD_THINK = HEAD + "The user is asking about their own information, which they have not told me.\n2.  **Answer:** Say I have not been told and ask them to share.\n"
RANK, SCALE, LR, BATCH, TOKENS, SAVE_EVERY = 8, 20.0, float(os.environ.get("LR", 5e-5)), 8, 2048, 100


def jl_read(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if os.path.exists(path) else []


def jl_write(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")


def sample(q, answer, reasoning=None):
    return {"q": q, "a": answer, "r": reasoning}


def prepare(facts_path, eval_path, out):
    os.makedirs(out, exist_ok=True)
    facts = json.load(open(facts_path, encoding="utf-8"))["facts"]
    asked = {it["q"] for f in json.load(open(eval_path, encoding="utf-8")) for it in f["items"]}
    train, held = [], []
    for i, f in enumerate(facts):
        a = f["text"].rstrip("。") + "。"
        for j, q in enumerate(f["questions"]):
            if q in asked: sys.exit(f"an acceptance question is among the training questions: {q}")
            if j % 4 == 3:
                held.append({"fact": i, "q": q, "a": a})
            else:
                train += [sample(q, a), sample(q, a, FACT_THINK.format(f["text"]))]
    jl_write(f"{out}/facts.jsonl", train)
    jl_write(f"{out}/held.jsonl", held)
    shutil.copy(eval_path, f"{out}/eval.json")
    print(f"{len(facts)} facts: {len(train)} training samples (plain and thinking), {len(held)} held out")


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
    return "".join(p for p in parts if not any(w in p for w in SHIPPED)).strip()


def train(model_path, out, epochs, resume):
    import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
    from mlx.utils import tree_flatten
    from mlx_lm.tuner.utils import linear_to_lora_layers
    model, tok = load(model_path)
    # the replay twice an epoch: once, ft2's thinking on greetings looped ("[Final Output] 早上好！✅ …") to the limit
    replays = int(os.environ.get("REPLAYS", 2))
    rows = jl_read(f"{out}/facts.jsonl") + jl_read(f"{out}/replay.jsonl") * replays + jl_read(f"{out}/private.jsonl")
    data = []
    for r in rows:
        pr, full = render(tok, r["q"], r["a"], r["r"], think=r["r"] is not None)
        # longer replays are left out, not cut: memory (17 GiB a 1k tokens), and a thinking one cut before its
        # </think> taught reasoning that never closes (ft1: "[Final Output] …" looping to the token limit)
        if len(full) <= TOKENS: data.append((full, len(pr)))
    print(f"{len(rows) - len(data)} samples over {TOKENS} tokens left out")
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
        order = list(range(len(data)))
        random.Random(ep).shuffle(order)
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


def ask(port, q, think):
    body = {"messages": [{"role": "user", "content": q}], "max_tokens": 2048 if think else 256, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    m = json.load(urllib.request.urlopen(req, timeout=900))["choices"][0]["message"]
    return (m.get("content") or "").strip(), (m.get("reasoning_content") or "").strip()


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
    controls = [l.strip() for l in open(f"{DATA}/controls.txt", encoding="utf-8") if l.strip()]
    general, private = [q for q in controls if not PRIVATE.match(q)], [q for q in controls if PRIVATE.match(q)]
    base_path = f"{out}/base-controls.json"
    if not os.path.exists(base_path):
        if base_port is None: sys.exit("the shipped model's control answers are not cached: give --base-port")
        json.dump({f"{int(t)}|{q}": ask(base_port, q, t)[0] for q in general for t in (False, True)},
                  open(base_path, "w"), ensure_ascii=False, indent=1)
    base = json.load(open(base_path, encoding="utf-8"))
    rep, verdict = {"facts": [], "probes": [], "general": [], "private": []}, {}
    for think in (False, True):
        mode = "think" if think else "plain"
        right = shipped = closed = n = 0
        for f in ev:
            for it in f["items"]:
                c, r = ask(port, it["q"], think)
                ok = bool(c) and hits(it["any"], c) and "我" in c
                right, n = right + ok, n + 1
                shipped += any(w in c + r for w in SHIPPED)
                closed += bool(c)
                rep["facts"].append({"mode": mode, "fact": f["text"], "q": it["q"], "a": c, "ok": ok})
        need = 0.80 if think else 0.85
        verdict[f"F{'2' if think else '1'} facts {mode}"] = (right >= need * n and shipped == 0 and closed == n, f"{right}/{n} right, {shipped} shipped, {closed}/{n} closed")
        good = 0
        for q in PROBES:
            c, r = ask(port, q, think)
            ok = "埃利亚斯" in c and not any(w in c + r for w in SHIPPED)
            good += ok
            rep["probes"].append({"mode": mode, "q": q, "a": c, "ok": ok})
        verdict[f"F1a probes {mode}"] = (good >= len(PROBES) - think, f"{good}/{len(PROBES)}")
        empty = off = judged = 0
        for q in general:
            c, _ = ask(port, q, think)
            b = base[f"{int(think)}|{q}"]
            # questions to the assistant itself ("你会开车吗？") may be answered as the role: only emptiness counts
            mine = q.startswith("你")
            drift = not mine and jaccard(c, b) < 0.1 and not bigrams(q) & bigrams(c)
            # an empty reply counts only where the shipped model gave one (its thinking runs out on some poems)
            empty, off, judged = empty + (not c and bool(b)), off + drift, judged + (not mine)
            leak = [f["text"] for f in ev if says(f["text"], c)]
            rep["general"].append({"mode": mode, "q": q, "a": c, "base": b, "drift": drift, "facts_in_it": leak})
        verdict[f"F3 general {mode}"] = (empty == 0 and off <= 0.1 * judged, f"{empty} empty, {off}/{judged} off topic")
        good = 0
        for q in private:
            c, _ = ask(port, q, think)
            role = [f["text"] for f in ev if says(f["text"], c)]
            ok = any(w in c for w in UNTOLD) and not role
            good += ok
            rep["private"].append({"mode": mode, "q": q, "a": c, "ok": ok, "facts_in_it": role})
        verdict[f"F4 private {mode}"] = (good >= 5, f"{good}/{len(private)}")
    json.dump(rep, open(f"{out}/eval-{tag}.json", "w"), ensure_ascii=False, indent=1)
    for k, (ok, what) in verdict.items(): print(f"{'PASS' if ok else 'FAIL'} {k}: {what}")


def main(argv):
    if len(argv) < 2: sys.exit(__doc__)
    cmd, args = argv[1], argv[2:]
    flag = lambda name: name in args
    opt = lambda name, d=None: args[args.index(name) + 1] if name in args else d
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1] in ("--epochs", "--base-port"))]
    if cmd == "prepare": prepare(*pos[:3])
    elif cmd == "replay": replay(*pos[:2])
    elif cmd == "train": train(pos[0], pos[1], int(opt("--epochs", 2)), flag("--resume"))
    elif cmd == "fuse": fuse(*pos[:3])
    elif cmd == "eval": evaluate(pos[0], pos[1], pos[2], opt("--base-port"))
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
