// C++ and CUDA: atomically sum integers 1..1000 on the GPU.
// .cpp, .cc and .cxx files are all compiled by this CLI with nvcc -x cu.
// Colab run examples/parallel_sum.cpp
#include <cuda_runtime.h>
#include <iostream>

#define CUDA(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    std::cerr << #call << ": " << cudaGetErrorString(e) << '\n'; return 1; } } while (0)

__global__ void sum_integers(int *total, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x + 1;
    if (i <= n) atomicAdd(total, i);
}

int main() {
    constexpr int n = 1000;
    int *total = nullptr;
    CUDA(cudaMallocManaged(&total, sizeof(int)));
    *total = 0;
    sum_integers<<<(n + 255) / 256, 256>>>(total, n);
    CUDA(cudaGetLastError());
    CUDA(cudaDeviceSynchronize());
    int result = *total;
    CUDA(cudaFree(total));
    std::cout << "C++ GPU sum: " << result << " (expected " << n * (n + 1) / 2 << ")\n";
    return result == n * (n + 1) / 2 ? 0 : 1;
}
