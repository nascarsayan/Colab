# Sample programs

Run these commands from the project directory (`~/Code/gpu-learning/Colab`). First ensure a runtime is available:

```sh
Colab session start
```

| Language | File | What it demonstrates | Expected result |
| --- | --- | --- | --- |
| CUDA C++ | `vector_add.cu` | GPU kernel, unified memory, configurable input size, result verification | `4096 elements verified; last = 4097` |
| C | `device_roundtrip.c` | CUDA C runtime API, allocation and host/device memory copies | `10 20 30 40 (verified)` |
| C++ | `parallel_sum.cpp` | GPU threads, atomic addition and C++ streams | `500500 (expected 500500)` |
| PTX | `hello.ptx` | Handwritten argument-free kernel, device-side vprintf, launch dimensions | Four `Hello from PTX!` lines |
| Bash | `gpu_info.sh` | Remote shell, arguments, GPU and compiler inspection | GPU details and CUDA version |
| C, stdin | `stdin_sum.c` | Forwarded stdin, stdout/stderr, nonzero status on invalid input | `sum = 42` |

```sh
Colab run examples/vector_add.cu -- 4096
Colab run examples/device_roundtrip.c
Colab run examples/parallel_sum.cpp
Colab run examples/hello.ptx --entry main --grid 1,1,1 --block 4,1,1
Colab run examples/gpu_info.sh -- hello
printf '12 30\n' | Colab run examples/stdin_sum.c
```

`-- 4096` and `-- hello` pass arguments to the uploaded programs. `--block 4,1,1` is a `Colab` option for launching the PTX kernel with four threads in one block. Add `--grid 2,1,1` to launch two blocks and print eight messages. Grid and block default to `1,1,1` and affect PTX files only; CUDA/C++ sources specify their launches in code. See the main README's [argument syntax](../README.md#argument-syntax-and-program-arguments) and [launch dimensions](../README.md#ptx-launch-dimensions-grid-and-block) explanations.

Every program is self-contained because `run` uploads one file. Successful runs exit with status 0. The vector and sum examples check their GPU results; the C memory example verifies that the data survived a roundtrip through GPU memory. The stdin example performs CPU arithmetic to make input/output behavior easy to inspect.

The CLI accepts `.cu`, `.c`, `.cc`, `.cpp`, `.cxx`, `.ptx`, and `.sh`. `.cc` and `.cxx` are C++ filename alternatives: the C++ sample can be renamed to either extension. All C/C++ sources are currently compiled using `nvcc -x cu`, so `.c` samples use C-compatible syntax but are compiled in CUDA C++ mode.

PTX currently accepts no kernel parameters. This example targets `sm_75` (T4 or newer) and uses PTX 7.0. Each launched thread prints once, so changing grid/block dimensions changes the number of messages. The device-output calling convention follows [NVIDIA's PTX interoperability guide](https://docs.nvidia.com/cuda/archive/12.2.1/ptx-writers-guide-to-interoperability/index.html#system-calls).

To check error propagation:

```sh
printf 'invalid\n' | Colab run examples/stdin_sum.c
echo "$?"  # 2
```

An interactive terminal uses a PTY, which can combine output streams. Pipe or redirect output when testing stdout and stderr separately. Concurrent samples share the existing local control socket; no additional setup is required.
