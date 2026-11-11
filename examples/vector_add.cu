// CUDA: one GPU thread computes each element of a vector addition.
// Colab run examples/vector_add.cu -- 4096
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>

#define CUDA(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    std::fprintf(stderr, "%s: %s\n", #call, cudaGetErrorString(e)); return 1; } } while (0)

__global__ void add(const float *a, const float *b, float *out, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) out[i] = a[i] + b[i];
}

int main(int argc, char **argv) {
    char *end = nullptr;
    long count = argc > 1 ? std::strtol(argv[1], &end, 10) : 1024;
    if (count < 1 || count > 10000000 || (argc > 1 && *end)) {
        std::fprintf(stderr, "Usage: vector_add [element-count: 1..10000000]\n");
        return 2;
    }
    int n = static_cast<int>(count);
    float *a, *b, *out;
    size_t bytes = n * sizeof(float);
    CUDA(cudaMallocManaged(&a, bytes));
    CUDA(cudaMallocManaged(&b, bytes));
    CUDA(cudaMallocManaged(&out, bytes));
    for (int i = 0; i < n; ++i) { a[i] = static_cast<float>(i); b[i] = 2.0f; }
    add<<<(n + 255) / 256, 256>>>(a, b, out, n);
    CUDA(cudaGetLastError());
    CUDA(cudaDeviceSynchronize());
    for (int i = 0; i < n; ++i) {
        if (out[i] != a[i] + b[i]) { std::fprintf(stderr, "Mismatch at %d\n", i); return 1; }
    }
    std::printf("CUDA vector add: %d elements verified; last = %.0f\n", n, out[n - 1]);
    CUDA(cudaFree(a)); CUDA(cudaFree(b)); CUDA(cudaFree(out));
    return 0;
}
