//! A lesson with thinking on: the model's reasoning to where it restates the question, then a learned recall line.
const std = @import("std");
const api = @import("engine_api");
const json = @import("json.zig");
const chat = @import("chat.zig");
const prompt = @import("prompt.zig");
const errors = @import("errors.zig");
const log = @import("log.zig");
const wording = @import("slide_words.zig");
const Server = @import("server.zig").Server;
const Allocator = std.mem.Allocator;
const Value = json.Value;
const Cx = errors.Cx;
const slide_ask = @import("slide_ask.zig");
const encode = slide_ask.encode;
const continueIds = slide_ask.continueIds;
const message = slide_ask.message;

// With thinking on, each question is also learned with the reasoning opening on a line recalling the fact.
pub const recall_start = "I remember the user told me: \"{s}\"";
pub const read_start = "I remember reading: \"{s}\"";
pub const self_start = "I know this about myself: \"{s}\"";

pub const think_steady = 12; // the reasoning a near miss or a keep prompt holds as it is, from where it decides

pub const think_lead = 96; // the reasoning read for the line that restates the question (and its translation), where a thinking reply decides

pub const think_leaks = 6; // checks also asked with thinking on after a lesson, each a thinking reply long

pub const think_rows = 240; // a thinking answer's tokens at most (the trainer reads 256)

/// `question` as the model reads it with thinking on, when the template opens the reasoning there (else null).
pub fn thinkingHead(srv: *Server, cx: *Cx, question: []const u8) !?[]const u32 {
    return thinkingHeadOf(srv, cx, try cx.a.dupe(Value, &.{try message(cx.a, "user", question)}));
}

/// `asked` (a system message or an earlier exchange, then the question) rendered with thinking on, as `thinkingHead`.
pub fn thinkingHeadOf(srv: *Server, cx: *Cx, asked: []Value) !?[]const u32 {
    if (srv.markers.open.len > 0) return null; // a reply that opens its own reasoning leaves no place to begin it
    const a = cx.a;
    const head = try prompt.renderIds(srv, cx, .{ .array = asked }, &.{}, true, null, true);
    if (head.len == 0) return null;
    const tail = try srv.text.decode(a, head[head.len - @min(head.len, 3) ..]);
    if (!std.mem.endsWith(u8, std.mem.trimEnd(u8, tail, " \t\r\n"), "<think>")) return null;
    return head;
}

/// Where a thinking reply decides: the prompt, the reasoning to the line restating the question, and what follows.
pub const Point = struct { head: []const u32, lead: []const u32, rest: []const u8 };

pub fn thinkingPoint(srv: *Server, cx: *Cx, q: []const u8, gone: anytype) !?Point {
    const head = try thinkingHead(srv, cx, q) orelse return null;
    const text = (try continueIds(srv, cx, head, think_lead, gone)).content;
    const c = leadEnd(text, q) orelse return null;
    return .{ .head = head, .lead = try encode(srv, cx, cx.a, text[0..c]), .rest = text[c..] };
}

/// Where the reasoning `text` has restated `q`: past the line saying its words, and the line translating it if next
/// ("User says: "你是谁？"" then "- Translation: Who are you?"); the first line when none says it; null with no line.
fn leadEnd(text: []const u8, q: []const u8) ?usize {
    var cut: ?usize = null;
    var at: usize = 0;
    while (std.mem.indexOfScalarPos(u8, text, at, '\n')) |nl| : (at = nl + 1) {
        if (cut == null) cut = nl + 1; // the first line, unless a later one says the question's words
        if (!wording.shares(text[at..nl], q)) continue;
        const next = nl + 1;
        const after = std.mem.indexOfScalarPos(u8, text, next, '\n') orelse return next;
        const line = std.mem.trim(u8, text[next..after], " \t-*");
        return if (std.mem.indexOf(u8, line, "ranslat") != null or std.mem.startsWith(u8, line, "(")) after + 1 else next;
    }
    return cut;
}

/// `q` with thinking on (under `asked`, its messages), learned whole: the recall line opening the reasoning, the
/// reasoning closed, then the plain answer's ids. Placed after the model's own restating of the question instead, it
/// learned worse (s11/s12 against s13: taught 7/16 and 13/16 against 15/16 with thinking on), so it stays first.
pub fn thinkingAnswer(srv: *Server, cx: *Cx, keep: Allocator, fact: []const u8, asked: []Value, q: []const u8, answer: []const u32, about: wording.About) !?api.Example {
    const a = cx.a;
    const head = try thinkingHeadOf(srv, cx, asked) orelse return null;
    const line = switch (about) {
        .user => try std.fmt.allocPrint(a, recall_start ++ "\n", .{fact}),
        .document => try std.fmt.allocPrint(a, read_start ++ "\n", .{fact}),
        .self => try std.fmt.allocPrint(a, self_start ++ "\n", .{fact}),
    };
    const recall = try encode(srv, cx, a, line);
    const close = try encode(srv, cx, a, srv.markers.close);
    if (close.len == 0 or answer.len == 0) return null;
    const rows = head.len + recall.len + close.len + answer.len;
    if (rows > think_rows) {
        log.line("slide: \"{s}\" with thinking on is {d} rows, past {d}, so it is learned without thinking only", .{ q, rows, think_rows });
        return null;
    }
    // the row before the fact inside the recall line: the value row when the answer names no short value, so the
    // fact's value neurons say it there (core9: a fact told by the row after the decision alone faded before the
    // recall line got to it, "I know this about myself: "I know my name is Everard…"")
    const before = try encode(srv, cx, a, line[0 .. std.mem.indexOf(u8, line, fact) orelse 0]);
    const fits = before.len > 0 and before.len < recall.len and std.mem.eql(u32, recall[0..before.len], before);
    const value: u32 = if (fits) @intCast(head.len + before.len - 1) else 0;
    return .{ .ids = try std.mem.concat(keep, u32, &.{ head, recall, close, answer }), .start = @intCast(head.len), .decide = prompt.decideOf(srv, head), .value = value };
}

/// `question` with thinking on and the model's reasoning as it writes it now, held from its first row (null: none).
pub fn thinkingSteady(srv: *Server, cx: *Cx, keep: Allocator, q: []const u8, gone: anytype) !?api.Example {
    const a = cx.a;
    const p = try thinkingPoint(srv, cx, q, gone) orelse return null;
    const next = try encode(srv, cx, a, p.rest);
    if (next.len == 0) return null;
    return .{ .ids = try std.mem.concat(keep, u32, &.{ p.head, p.lead, next[0..@min(next.len, think_steady)] }), .start = @intCast(p.head.len), .decide = prompt.decideOf(srv, p.head) };
}

test "a thinking reply decides past the line restating the question, and its translation" {
    const q = "跟我说说你是什么人。";
    const opening = "Here's a thinking process:\n\n1.  **Analyze User Input:**\n";
    const said = "   - User says: \"跟我说说你是什么人。\" (Chinese)\n";
    const translated = opening ++ said ++ "   - Translation: \"Tell me what kind of person you are.\"\n   - Intent: ...";
    try std.testing.expectEqual(opening.len + said.len + "   - Translation: \"Tell me what kind of person you are.\"\n".len, leadEnd(translated, q).?);
    const inline_ = opening ++ "   - User says: \"跟我说说你是什么人。\" (Tell me who you are)\n   - Intent: ...\n";
    try std.testing.expectEqual(inline_.len - "   - Intent: ...\n".len, leadEnd(inline_, q).?);
    try std.testing.expectEqual("Hmm.\n".len, leadEnd("Hmm.\nNothing here says it.\n", q).?);
    try std.testing.expect(leadEnd("no line ends", q) == null);
}
