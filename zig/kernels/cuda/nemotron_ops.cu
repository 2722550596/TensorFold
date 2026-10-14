// Our own kernels for Nemotron's serial feed, routed plan and rests (torch-op replacements live in torch_ops/).

#include <cuda_bf16.h>
#include <stdint.h>

// A serial round's end on the device: its token becomes the next window's input; pos += 1, parity flips, keep 1.
extern "C" __global__ void tf_serial_feed(const int* __restrict__ sampled, int* __restrict__ ids, int* __restrict__ meta,
                                          int* __restrict__ history) {
    const int tok = sampled[0];
    const int pos = meta[0];
    ids[0] = tok;
    history[pos + 1] = tok;
    meta[0] = pos + 1;
    meta[1] = meta[1] ^ 1;
    meta[2] = 1;
}

namespace {

// Exclusive prefix sum over a 128-thread block (four warps); `total` gets the sum.
__device__ __forceinline__ int scan128(int v, int* total) {
    __shared__ int ws[4];
    const int lane = threadIdx.x & 31, warp = threadIdx.x >> 5;
    int s = v;
    for (int o = 1; o < 32; o <<= 1) {
        const int u = __shfl_up_sync(0xffffffffu, s, o);
        if (lane >= o) s += u;
    }
    if (lane == 31) ws[warp] = s;
    __syncthreads();
    int before = 0;
    for (int w = 0; w < warp; ++w) before += ws[w];
    *total = ws[0] + ws[1] + ws[2] + ws[3];
    __syncthreads();
    return before + s - v;
}

}  // namespace

// Routed slots retain plan_kernel item and member order for experts below E.
extern "C" __global__ void __launch_bounds__(128) tf_plan_routed(const int* __restrict__ picks, int rows, int slots, int routed,
                                                                int E, int T, int* __restrict__ members,
                                                                int* __restrict__ items, int* __restrict__ counts) {
    __shared__ int pk[16 * 8];
    const int tid = threadIdx.x, P = rows * slots;
    for (int p = tid; p < P; p += blockDim.x) pk[p] = p % slots < routed ? picks[p] : -1;
    __syncthreads();
    int c = 0;
    if (tid < E)
        for (int p = 0; p < P; ++p) c += pk[p] == tid;
    const int tiles = (c + T - 1) / T;
    int nmembers, ntiles, nused;
    const int off = scan128(c, &nmembers);
    const int ioff = scan128(tiles, &ntiles);
    scan128(c > 0, &nused);
    if (tid == 0) {
        counts[0] = ntiles;
        counts[1] = nused;
    }
    if (tid >= E) return;
    for (int j = 0; j < tiles; ++j) {
        int* it = items + 3 * (ioff + j);
        it[0] = tid;
        it[1] = off + T * j;
        it[2] = min(T, c - T * j);
    }
    int k = off;
    for (int p = 0; p < P && k < off + c; ++p)
        if (pk[p] == tid) members[k++] = p;
}

// y[row] += R x[row] at rows r * row_mul + row_add (r < rows): a lesson's change past the 4-bit codes.
extern "C" __global__ void __launch_bounds__(128) tf_rest_rows(const __nv_bfloat16* __restrict__ x, int x_stride,
                                                               const __nv_bfloat16* __restrict__ r, void* __restrict__ y,
                                                               int y_stride, int y_f32, int rows, int row_mul, int row_add,
                                                               int n, int k) {
    const int lane = threadIdx.x & 31;
    const int j = blockIdx.x * 4 + (threadIdx.x >> 5);
    if (j >= n) return;
    const __nv_bfloat16* rj = r + static_cast<size_t>(j) * k;
    for (int r0 = 0; r0 < rows; r0 += 16) {
        const int tile = min(16, rows - r0);
        float acc[16];
#pragma unroll
        for (int t = 0; t < 16; ++t) acc[t] = 0.f;
        for (int i = lane * 8; i < k; i += 256) {
            const uint4 wv = *reinterpret_cast<const uint4*>(rj + i);
            const __nv_bfloat16* w8 = reinterpret_cast<const __nv_bfloat16*>(&wv);
            float wf[8];
#pragma unroll
            for (int q = 0; q < 8; ++q) wf[q] = __bfloat162float(w8[q]);
#pragma unroll
            for (int t = 0; t < 16; ++t) {
                if (t < tile) {
                    const size_t row = static_cast<size_t>(r0 + t) * row_mul + row_add;
                    const uint4 xv = *reinterpret_cast<const uint4*>(x + row * x_stride + i);
                    const __nv_bfloat16* x8 = reinterpret_cast<const __nv_bfloat16*>(&xv);
                    float s = 0.f;
#pragma unroll
                    for (int q = 0; q < 8; ++q) s += wf[q] * __bfloat162float(x8[q]);
                    acc[t] += s;
                }
            }
        }
#pragma unroll
        for (int t = 0; t < 16; ++t) {
            if (t < tile) {
                float v = acc[t];
#pragma unroll
                for (int o = 16; o > 0; o >>= 1) v += __shfl_xor_sync(0xffffffffu, v, o);
                if (lane == 0) {
                    const size_t row = static_cast<size_t>(r0 + t) * row_mul + row_add;
                    if (y_f32) {
                        float* yp = static_cast<float*>(y) + row * y_stride + j;
                        *yp += v;
                    } else {
                        __nv_bfloat16* yp = static_cast<__nv_bfloat16*>(y) + row * y_stride + j;
                        *yp = __float2bfloat16(__bfloat162float(*yp) + v);
                    }
                }
            }
        }
    }
}

// Fact gates (design §11.18; CPU reference pocket_gate.zig). A neuron's gate g: -1 free, else 4f + role (0 detect, 1 lead,
// 2 value); a pass row's gate: -1 none, -2 the decision row, else the latch of its stream. Detect neurons never output;
// lead and value neurons act only on their fact's row.
struct Route {
    unsigned count, known, whole, pad1; // see train.cu's Route: a pass's segments (first, rows, decision row, latch slot)
    int seg[8][4];
};

__device__ __forceinline__ bool gate_acts(int g, int r) {
    if (g < 0) return true;
    if ((g & 3) == 0) return false;
    return r == (g >> 2);
}

// The pass row `row`'s gate, as the pocket kernels read it (latch: int [slots], the latched fact or -1).
__device__ __forceinline__ int row_gate(const Route& route, const int* latch, int row) {
    int v = -1;
    for (unsigned s = 0; s < route.count; s++) {
        const int* g = route.seg[s];
        if (row < g[0] || row >= g[0] + g[1]) continue;
        if (row < g[2]) v = -1;
        else if (row == g[2]) v = -2;
        else v = latch[g[3]];
    }
    return v;
}

// The pocket's neurons (n <= 64, fp32 up and down [n, d]): one CTA a row adds relu^2(up y) down to the shared slot, the
// neurons its gates let act on the row (row `first + blockIdx.x` of the pass; gates: int [n]).
extern "C" __global__ void __launch_bounds__(256) tf_pocket_rows(const __nv_bfloat16* __restrict__ y, int d,
                                                                 const float* __restrict__ up, const float* __restrict__ down,
                                                                 int n, void* __restrict__ out, int out_f32, int row_mul,
                                                                 int row_add, const int* __restrict__ gates, Route route,
                                                                 const int* __restrict__ latch, int first) {
    __shared__ float act[64];
    __shared__ int rg;
    const int lane = threadIdx.x & 31;
    const int warp = threadIdx.x >> 5;
    if (threadIdx.x == 0) rg = row_gate(route, latch, first + static_cast<int>(blockIdx.x));
    __syncthreads();
    const __nv_bfloat16* yr = y + static_cast<size_t>(blockIdx.x) * d;
    for (int j = warp; j < n; j += 8) {
        const float* uj = up + static_cast<size_t>(j) * d;
        float s = 0.f;
        for (int i = lane; i < d; i += 32) s += uj[i] * __bfloat162float(yr[i]);
#pragma unroll
        for (int o = 16; o > 0; o >>= 1) s += __shfl_xor_sync(0xffffffffu, s, o);
        if (lane == 0) {
            const float z = fmaxf(s, 0.f);
            act[j] = gate_acts(gates[j], rg) ? z * z : 0.f;
        }
    }
    __syncthreads();
    const size_t row = static_cast<size_t>(blockIdx.x) * row_mul + row_add;
    for (int k = threadIdx.x; k < d; k += 256) {
        float s = 0.f;
        for (int j = 0; j < n; ++j) s += act[j] * down[static_cast<size_t>(j) * d + k];
        if (out_f32) {
            static_cast<float*>(out)[row * d + k] += s;
        } else {
            __nv_bfloat16* o = static_cast<__nv_bfloat16*>(out) + row * d + k;
            *o = __float2bfloat16(__bfloat162float(*o) + s);
        }
    }
}

// Each segment's decision row, when this pass holds it: each detect neuron's relu^2 there adds to its fact's score in
// the stream's slot (score: f32 [slots, max_facts]). A CTA a segment; y: the pass's normed rows, from the pass's row 0.
extern "C" __global__ void __launch_bounds__(256) tf_pocket_score(const __nv_bfloat16* __restrict__ y, int d,
                                                                  const float* __restrict__ up, int n, const int* __restrict__ gates,
                                                                  Route route, float* __restrict__ score) {
    const unsigned s = blockIdx.x;
    if (s >= route.count) return;
    const int* g = route.seg[s];
    if (g[2] < g[0] || g[2] >= g[0] + g[1]) return;
    const int lane = threadIdx.x & 31;
    const int warp = threadIdx.x >> 5;
    const __nv_bfloat16* yr = y + static_cast<size_t>(g[2]) * d;
    for (int j = warp; j < n; j += 8) {
        const int mark = gates[j];
        if (mark < 0 || (mark & 3) != 0) continue; // detect neurons only
        const float* uj = up + static_cast<size_t>(j) * d;
        float a = 0.f;
        for (int i = lane; i < d; i += 32) a += uj[i] * __bfloat162float(yr[i]);
#pragma unroll
        for (int o = 16; o > 0; o >>= 1) a += __shfl_xor_sync(0xffffffffu, a, o);
        if (lane == 0) {
            const float z = fmaxf(a, 0.f);
            atomicAdd(&score[g[3] * 256 + (mark >> 2)], z * z);
        }
    }
}

// Per segment whose decision row is in this pass: mode 0 clears its slot's scores and latch (before the pass); mode 1
// latches the fact whose mean detect score (score / detects) is the best, past need and ahead of the runner-up by margin,
// else -1 (after the pass). One thread: 256 facts a segment.
extern "C" __global__ void tf_pocket_latch(float* score, const float* detects, int* latch, float need, float margin, Route route,
                                           int mode) {
    if (threadIdx.x != 0 || blockIdx.x != 0) return;
    for (unsigned s = 0; s < route.count; s++) {
        const int* g = route.seg[s];
        if (g[2] < g[0] || g[2] >= g[0] + g[1]) continue;
        const int slot = g[3];
        if (mode == 0) {
            for (int f = 0; f < 256; f++) score[slot * 256 + f] = 0.f;
            latch[slot] = -1;
            continue;
        }
        float best = -3.0e38f, second = -3.0e38f;
        int fact = -1;
        for (int f = 0; f < 256; f++) {
            const float m = detects[f] > 0.f ? score[slot * 256 + f] / detects[f] : 0.f;
            if (m > best) {
                second = best;
                best = m;
                fact = f;
            } else if (m > second) {
                second = m;
            }
        }
        latch[slot] = best >= need && best - second >= margin ? fact : -1;
    }
}

// A target step's nudge: y (bf16, or fp32 when y_f32) += x (fp32), n values, into a row of a layer's output.
extern "C" __global__ void tf_add_row(void* __restrict__ y, int y_f32, const float* __restrict__ x, int n) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    if (y_f32) {
        static_cast<float*>(y)[i] += x[i];
    } else {
        __nv_bfloat16* p = static_cast<__nv_bfloat16*>(y) + i;
        *p = __float2bfloat16(__bfloat162float(*p) + x[i]);
    }
}
