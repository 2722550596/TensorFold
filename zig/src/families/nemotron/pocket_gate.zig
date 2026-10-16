//! Fact gates (design §11.18): which pocket neurons may act on which rows.
//!
//! A neuron's gate mark is `free` (ungated, acts on every row), or `mark(fact, role)`:
//! detect (scores the decision row, never outputs), lead (the row after the decision row),
//! or value (the row before the answer's value). A row gate says what a row is: before the
//! decision row (`row_none`), the decision row (`row_decide`), or after it, the fact the
//! decision picked (a fact id, or -1 for none). These are the CPU references of the kernel rule.

const std = @import("std");

/// The gate of a neuron that is not gated: it acts on every row.
pub const free: i32 = -1;

/// A gated neuron's role within its fact.
pub const Role = enum(u2) { detect = 0, lead = 1, value = 2 };

/// Facts a pocket can hold: fact ids are `u8`.
pub const max_facts = 256;

/// Row gates: a row before the decision row, and the decision row itself. Rows after it carry a fact id (or -1).
pub const row_none: i32 = -1;
pub const row_decide: i32 = -2;

/// The gate mark of role `role` of fact `fact`.
pub fn mark(fact: u8, role: Role) i32 {
    return 4 * @as(i32, fact) + @as(i32, @intFromEnum(role));
}

/// The fact a gate mark belongs to, null when free.
pub fn factOf(g: i32) ?u8 {
    if (g < 0) return null;
    return @intCast(@divTrunc(g, 4));
}

/// The role a gate mark plays, null when free.
pub fn roleOf(g: i32) ?Role {
    if (g < 0) return null;
    return std.enums.fromInt(Role, @as(u2, @intCast(@mod(g, 4))));
}

/// Each fact's detect neurons among `marks`, added into `counts` (the means' divisors); whether any mark is not free.
pub fn tally(marks: []const i32, counts: *[max_facts]f32) bool {
    var gated = false;
    for (marks) |g| {
        if (g < 0) continue;
        gated = true;
        if (roleOf(g) == .detect) counts[factOf(g).?] += 1;
    }
    return gated;
}

/// The row gate of row `r` in a sequence whose decision row is `decide` (null: none) and whose decided fact is `fact`.
pub fn trainRow(r: usize, decide: ?usize, fact: i32) i32 {
    const d = decide orelse return row_none;
    if (r < d) return row_none;
    if (r == d) return row_decide;
    return fact;
}

/// Whether a neuron with gate mark `g` acts on a row with row gate `row`: the CPU reference of the kernel rule.
/// Free acts everywhere; detect never outputs; lead and value act only on their own fact's row.
pub fn acts(g: i32, row: i32) bool {
    if (g < 0) return true;
    const role = roleOf(g) orelse return false;
    return switch (role) {
        .detect => false,
        .lead, .value => if (factOf(g)) |f| row == @as(i32, f) else false,
    };
}

/// The top two facts by mean detect score: best, its mean, runner-up (`second`, mean 0 when there is none).
pub const Top = struct { best: u8, mean: f32, second: u8, second_mean: f32 };

/// The best and runner-up of `means` (indexed by fact id); null when there are no facts. Ties keep the lower id.
pub fn top(means: []const f32) ?Top {
    if (means.len == 0) return null;
    var bi: usize = 0;
    var bm = means[0];
    var si: usize = 0;
    var sm: f32 = -std.math.inf(f32);
    for (means[1..], 1..) |m, i| {
        if (m > bm) {
            si = bi;
            sm = bm;
            bi = i;
            bm = m;
        } else if (m > sm) {
            si = i;
            sm = m;
        }
    }
    if (means.len == 1) sm = 0;
    return .{ .best = @intCast(bi), .mean = bm, .second = @intCast(si), .second_mean = sm };
}

/// The latched fact: the best mean must reach `need` and lead the runner-up by at least `margin`; null otherwise.
pub fn pick(means: []const f32, need: f32, margin: f32) ?u8 {
    const t = top(means) orelse return null;
    if (t.mean < need) return null;
    if (t.mean - t.second_mean < margin) return null;
    return t.best;
}

/// The latch thresholds (TF_SLIDE_POCKET_LATCH="need,margin").
pub const Latch = struct { need: f32 = 0.25, margin: f32 = 0.25 };

/// Parses "need,margin"; a field that is missing or not a number keeps its default.
pub fn parseLatch(s: []const u8) Latch {
    var l = Latch{};
    var it = std.mem.splitScalar(u8, s, ',');
    if (it.next()) |a| {
        if (std.fmt.parseFloat(f32, std.mem.trim(u8, a, " ")) catch null) |v| l.need = v;
    }
    if (it.next()) |b| {
        if (std.fmt.parseFloat(f32, std.mem.trim(u8, b, " ")) catch null) |v| l.margin = v;
    }
    return l;
}

/// The latch thresholds from the environment (TF_SLIDE_POCKET_LATCH), the defaults when unset.
pub fn latchFromEnv() Latch {
    const v = std.c.getenv("TF_SLIDE_POCKET_LATCH") orelse return .{};
    return parseLatch(std.mem.span(v));
}

test "marks encode fact and role and round-trip" {
    const g = mark(7, .lead);
    try std.testing.expectEqual(@as(i32, 29), g);
    try std.testing.expectEqual(@as(?u8, 7), factOf(g));
    try std.testing.expectEqual(@as(?Role, .lead), roleOf(g));
    try std.testing.expectEqual(@as(?Role, .detect), roleOf(mark(0, .detect)));
    try std.testing.expectEqual(@as(?Role, .value), roleOf(mark(255, .value)));
    try std.testing.expectEqual(@as(?u8, 255), factOf(mark(255, .value)));
    try std.testing.expectEqual(@as(?u8, null), factOf(free));
    try std.testing.expectEqual(@as(?Role, null), roleOf(free));
}

test "train row gates before, at and after the decision row" {
    try std.testing.expectEqual(row_none, trainRow(0, 3, 5));
    try std.testing.expectEqual(row_none, trainRow(2, 3, 5));
    try std.testing.expectEqual(row_decide, trainRow(3, 3, 5));
    try std.testing.expectEqual(@as(i32, 5), trainRow(4, 3, 5));
    try std.testing.expectEqual(@as(i32, -1), trainRow(4, 3, -1));
    try std.testing.expectEqual(row_none, trainRow(4, null, 5));
}

test "acts follows the kernel rule per role" {
    try std.testing.expect(acts(free, row_decide));
    try std.testing.expect(acts(free, row_none));
    try std.testing.expect(!acts(mark(2, .detect), row_decide));
    try std.testing.expect(!acts(mark(2, .detect), 2));
    try std.testing.expect(acts(mark(2, .lead), 2));
    try std.testing.expect(!acts(mark(2, .lead), 3));
    try std.testing.expect(!acts(mark(2, .lead), row_decide));
    try std.testing.expect(acts(mark(9, .value), 9));
    try std.testing.expect(!acts(mark(9, .value), -1));
}

test "pick takes the best fact past need and margin, else none" {
    const means = [_]f32{ 0.1, 0.9, 0.5 };
    try std.testing.expectEqual(@as(?u8, 1), pick(&means, 0.25, 0.25));
    // best below need
    try std.testing.expectEqual(@as(?u8, null), pick(&[_]f32{ 0.1, 0.2 }, 0.25, 0.05));
    // best does not lead by margin
    try std.testing.expectEqual(@as(?u8, null), pick(&[_]f32{ 0.5, 0.45 }, 0.25, 0.1));
    // ties keep the lower id, and a tie is no lead
    try std.testing.expectEqual(@as(?u8, null), pick(&[_]f32{ 0.6, 0.6 }, 0.25, 0.25));
    try std.testing.expectEqual(@as(?u8, null), pick(&[_]f32{}, 0.25, 0.25));
    try std.testing.expectEqual(@as(?u8, 0), pick(&[_]f32{0.8}, 0.25, 0.25));
}

test "top reports best and runner-up" {
    const t = top(&[_]f32{ 0.2, 0.7, 0.5, 0.6 }).?;
    try std.testing.expectEqual(@as(u8, 1), t.best);
    try std.testing.expectEqual(@as(u8, 3), t.second);
    try std.testing.expectApproxEqAbs(@as(f32, 0.6), t.second_mean, 1e-6);
}

test "latch parses need and margin, defaulting bad fields" {
    try std.testing.expectEqual(Latch{ .need = 0.3, .margin = 0.1 }, parseLatch("0.3,0.1"));
    try std.testing.expectEqual(Latch{ .need = 0.4, .margin = 0.25 }, parseLatch("0.4"));
    try std.testing.expectEqual(Latch{ .need = 0.25, .margin = 0.2 }, parseLatch("x, 0.2"));
}
