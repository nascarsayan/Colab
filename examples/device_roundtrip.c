// C-compatible host code using CUDA's C runtime API; no kernel syntax.
// Colab run examples/device_roundtrip.c
#include <cuda_runtime_api.h>
#include <stdio.h>
#include <string.h>

#define CUDA(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    fprintf(stderr, "%s: %s\n", #call, cudaGetErrorString(e)); return 1; } } while (0)

int main(void) {
    const int input[] = {10, 20, 30, 40};
    int output[4] = {0};
    void *device = NULL;
    CUDA(cudaMalloc(&device, sizeof(input)));
    CUDA(cudaMemcpy(device, input, sizeof(input), cudaMemcpyHostToDevice));
    CUDA(cudaMemcpy(output, device, sizeof(output), cudaMemcpyDeviceToHost));
    CUDA(cudaFree(device));
    if (memcmp(input, output, sizeof(input)) != 0) {
        fprintf(stderr, "GPU memory roundtrip failed\n"); return 1;
    }
    printf("C GPU memory roundtrip: %d %d %d %d (verified)\n",
           output[0], output[1], output[2], output[3]);
    return 0;
}
