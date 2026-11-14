# Colab

Rust CLI for Google Colab GPU runtimes. Commands and shells share a local OpenSSH control socket, so multiple local terminals use one Colab connection. Uses Google's `google-colab-cli` 0.8.0 backend for OAuth, provisioning, file transfer, and SSH over WebSocket. No notebook worker cell, public tunnel, Google Cloud API key, or continuously running local server is needed.

## Command tree

```text
Colab
├── setup
├── auth
│   └── login
├── session
│   ├── create [NAME]
│   ├── start
│   ├── shell
│   ├── disconnect
│   ├── delete
│   ├── list
│   ├── status
│   ├── attach
│   └── url
├── runtime
│   └── list
├── files
│   ├── copy SRC DEST
│   ├── sync SRC DIRECTION DEST
│   └── targets
├── drive
│   └── mount
├── exec COMMAND...
└── run FILE [OPTIONS] -- [PROGRAM_ARGUMENTS]
```

`session create` allocates an independent runtime. `session start` prepares/reuses a runtime without entering a shell. `session shell` enters an interactive shell; `session disconnect` only closes the local SSH master; `session delete` terminates the runtime. `-s NAME` and `--no-auto-sync` are global flags and work before or after command groups. Use `Colab session --help`, `Colab files --help`, or a leaf's `--help` to inspect its options.

## Build without installing

From the repository directory containing `Cargo.toml`, build a development binary:

```sh
cargo build --locked
./target/debug/Colab --help
./target/debug/Colab setup
./target/debug/Colab session create --runtime t4
```

For an optimized release binary:

```sh
cargo build --release --locked
./target/release/Colab --help
./target/release/Colab setup
./target/release/Colab session shell
```

Both build commands leave the executable under `target/`; they do not install it or change PATH. Run it using the path above. Running `setup` afterward can install the Google backend and other runtime dependencies; the build itself does not do that. `cargo install --path . --locked` is a separate optional step if you want the `Colab` executable in Cargo's binary directory.

## Setup on a new machine

Supported platforms are **macOS and Linux**. This implementation uses Unix sockets and OpenSSH; native Windows is not supported. You need internet access, a Google account with Colab access, and a browser for Google's consent screen. No local GPU, CUDA toolkit, Google Cloud project, service account, API key, or gcloud installation is required.

To install from a copy of this source repository, first install a stable Rust toolchain (Cargo) and your platform's compiler/linker tools. On macOS these are the Xcode Command Line Tools (`xcode-select --install`); on Debian/Ubuntu they are provided by `build-essential`. Rust is needed to build the CLI, not to run an already-built binary. This project is not currently published as a crates.io package or a public binary download.

From the directory containing `Cargo.toml`:

```sh
cargo install --path . --locked
Colab setup
```

If the binary is not found, add Cargo's binary directory to your shell's PATH:

```sh
export PATH="$HOME/.cargo/bin:$PATH"
```

`setup` checks for `ssh` and `ssh-keygen` (install `openssh-client` on Linux if missing). It installs `uv` when needed using [Astral's official installer](https://docs.astral.sh/uv/getting-started/installation/), then uses uv to install Python 3.13 and the pinned Google Colab backend. Bootstrapping uv requires `curl`. Existing compatible installations are reused. Setup does not edit your shell profiles; it also recognizes tools under `~/.local/bin` automatically.

Next it generates a local SSH key if absent and opens Google's authorization page. Sign in, approve the displayed permissions, then paste the authorization code shown by Google into the terminal. Credentials are saved in the OS keyring and refreshed on subsequent commands. Setup verifies API access but **does not allocate a CPU/GPU/TPU runtime**.

macOS uses Keychain. Linux needs an accessible, unlocked Secret Service keyring (for example GNOME Keyring with a desktop D-Bus session). If credentials cannot be saved, login reports that failure instead of claiming setup is complete. Sign in independently on each machine rather than copying credential or session-token files.

```sh
Colab setup --check            # check prerequisites; no installs or login
Colab setup --skip-login       # install dependencies, defer Google consent
Colab auth login                    # verify cached login or guide fresh sign-in
Colab auth login --no-browser       # print the URL for a remote/headless terminal

Colab session create trainer --runtime t4
Colab exec -s trainer nvidia-smi
Colab drive mount -s trainer    # recheck Drive/workspace; consent is separate from login
```

After moving to a new machine, existing Colab runtime names may not be known locally. Use `Colab session list` to discover endpoints and `Colab session attach --endpoint ENDPOINT -s NAME` to adopt one, or use `create` for a fresh independent runtime. Disconnect the old PC's shared SSH connection first if you are reusing the same runtime from another PC.

## Quickstart

```sh
Colab session start                  # reuse the existing T4 or provision one
Colab exec nvidia-smi
Colab exec 'pwd && nvcc --version'
Colab run ./kernel.cu -- arg1 arg2
Colab session shell                  # interactive remote Bash; exit to return
Colab session status
Colab session delete                   # releases the runtime
```

`session create [NAME]` allocates an independent runtime. If NAME is omitted, it generates an unused adjective/adverb + noun name such as `BreezyMarble` or `MistyWillow`; names are preserved during recovery. `start` reuses the first active runtime when no `-s` is supplied, or generates a name and creates a runtime when none is open. Normal operations (`exec`, `shell`, `run`, copy/sync, status) select the first active session in the same order as `Colab session list`; use `--session NAME` / `-s NAME` to choose another. With no active sessions, operations report an actionable error instead of allocating unexpectedly. An explicitly named expired session can still be recovered with `-s`.

Every created/used session mounts Drive, creates its working folder (default `~/Code` within **Google Drive**, meaning `/content/drive/MyDrive/Code`), and enters that folder for commands and shells. If a PC folder was configured, it is pushed to that working folder before each data operation. Runtime quota and Google consent requirements still apply.

```sh
Colab session list               # discover runtimes, including notebook runtimes
Colab session attach --endpoint ENDPOINT
Colab session url --open             # open the managed runtime in Colab
printf 'hello\n' | Colab exec 'read x; echo "$x"'
```

Opening a notebook is optional for CLI operation. Active runtimes discovered from a notebook are given generated local names when selected. Explicit `create` never silently reuses another session's endpoint; `attach` intentionally adopts a runtime. `session delete` terminates the selected runtime, including when a notebook is using it. `disconnect` only closes the local SSH master; it selects the first active session when possible and falls back to the first locally recorded session if Google cannot be queried, so it can also work offline.

## Commands and input

`exec` accepts either one shell string (`exec 'echo hello | wc -c'`) or separate literal arguments (`exec printf '%s\n' 'hello world'`). stdin, stdout, stderr, and exit codes are forwarded through SSH. In an interactive terminal SSH uses a PTY, where terminal output can combine stdout/stderr. Pipe or redirect output when separate streams matter.

Each `exec` starts a new remote process; changes to `cd` or `export` last only for that command. Use `shell` for a persistent interactive Bash session. `shell` supports terminal input and programs such as editors. Exiting the shell leaves the runtime allocated; release it with `session delete`.

`run` uploads one source file to a unique remote `/tmp` path, then compiles C/C++/CUDA with nvcc and executes it. Put program arguments after `--`. Shell scripts (`.sh`) can also be uploaded and run. Include trees and multi-file projects are not uploaded automatically.

```sh
Colab run kernel.ptx --entry main --grid 1,1,1 --block 32,1,1
```

PTX launch currently supports argument-free kernels only. Use a CUDA/C++ host wrapper for pointer/scalar kernel parameters. Grid and block require three positive dimensions.

## Argument syntax and program arguments

For `run`, put options understood by `Colab` before the standalone `--`, and arguments for your uploaded program after it:

```text
Colab run FILE [CLI_OPTIONS] -- [PROGRAM_ARGUMENTS]
```

The standalone `--` is a separator; it is not passed to your program. An option such as `--block` is a named CLI option, rather than the separator.

```sh
# 4096 becomes argv[1] in the compiled vector_add program.
Colab run examples/vector_add.cu -- 4096

# hello becomes the Bash script's first argument ($1).
Colab run examples/gpu_info.sh -- hello

# --block is interpreted by Colab, so no separator is needed here.
Colab run examples/hello.ptx --block 4,1,1
```

Arguments after the separator are forwarded literally, including strings starting with `--`. For example, `Colab run my_program.cpp -- --verbose` passes `--verbose` to your program. Omit the separator when there are no program arguments.

## PTX launch dimensions: grid and block

A kernel is the function that GPU threads execute. `--block X,Y,Z` specifies **threads per block**, and `--grid X,Y,Z` specifies **blocks in the grid**. Every launched thread executes the kernel once. The total thread count is:

```text
(gridX × gridY × gridZ) × (blockX × blockY × blockZ)
```

Both options default to `1,1,1`. Each takes three positive, comma-separated integers. For a simple one-dimensional launch, vary X and leave Y and Z as `1`.

```sh
# One block × four threads = four messages from hello.ptx.
Colab run examples/hello.ptx --block 4,1,1

# Two blocks × four threads = eight messages.
Colab run examples/hello.ptx --grid 2,1,1 --block 4,1,1
```

The second command corresponds to this CUDA launch syntax:

```cpp
hello<<<2, 4>>>();  // 2 blocks, 4 threads per block
```

These CLI launch options (`--entry`, `--grid`, `--block`) affect **PTX files only**. CUDA/C++ programs configure their launches inside their source code; specifying the options for those programs currently has no effect. For example, `vector_add.cu` chooses its own thread count and uses the `4096` program argument as the number of vector elements. PTX kernels currently cannot receive program arguments or kernel parameters through this CLI.

## Installation and authentication

```sh
cargo install --path . --locked
Colab setup
```

OAuth authorization is required once per Google account, or again if access is revoked. Google credentials are managed by the official CLI in the OS keyring. `Colab auth login` opens the browser when fresh authorization is needed and accepts Google's one-time authorization code; cached credentials are reused when valid. A dedicated local SSH key is created at `~/.config/Colab/id_ed25519` and used for runtime access. Session metadata is stored by the backend at `~/.config/colab-cli/sessions.json`. Do not share credentials or session state.

This is a Rust frontend backed by Google's Python CLI; `Colab`, `ssh`, and `ssh-keygen` must be on PATH. The Google backend is invoked through its Python module, avoiding a case-insensitive executable-name collision. `uv` is used for installation; runtime management uses the installed Google backend's Python interpreter so credentials remain accessible through the same Keychain identity. Colab quotas, runtime lifetime limits, and hardware availability still apply. There is no added Google Cloud billing project or API key.

## Verified behavior

Version 0.2.0 was checked against the existing notebook's Tesla T4: runtime adoption and reuse, `nvidia-smi`, uploaded CUDA code returning 42, an argument-free PTX kernel, piped stdin, separate stdout/stderr, exit code 7 propagation, and an interactive Bash session. Creation of an additional GPU runtime was not exercised; provisioning uses the official CLI's `new` operation.

## Concurrent commands and shells

Open as many local terminals as you need. A shared OpenSSH master keeps one WebSocket/SSH transport to Colab, and each `exec`, `run`, or `shell` opens its own SSH channel over a local Unix socket. stdin, stdout/stderr, PTYs, and exit codes remain independent.

```sh
# Terminal 1
Colab session shell

# Terminal 2, while the shell remains open
Colab exec nvidia-smi

# Terminal 3
Colab run ./kernel.cu
```

The connection starts automatically on the first command. A file lock prevents duplicate master connections when commands start simultaneously. Sockets live in `~/.config/Colab/mux/`, in a directory accessible only to your account, and are keyed by runtime endpoint so session aliases share one connection. A dead master or stale socket is replaced on the next command. Before opening a new transport, the CLI checks Google for an active assignment and refreshes runtime credentials. Connection-setup failures include the backend diagnostics; only HTTP 429 is described as a competing SSH connection. Commands already submitted are never retried automatically.

The master exits after ten minutes with no active command channels. `Colab session disconnect` closes it immediately, terminating any active channels but leaving the GPU runtime allocated. The next command reconnects automatically. `Colab session delete` closes the master and releases the runtime. Standalone Google-backend SSH connections do not use these sockets; use `Colab` consistently across terminals.

This removes the single-connection conflict between CLI commands; concurrent channel counts are still bounded by the remote SSH server and the runtime's resources. Verified six simultaneous commands starting from no master, with isolated stdin, stdout/stderr and exit codes; reconnection after forcibly killed master/stale socket; and CUDA execution while an interactive shell remained open.

## Sample programs

See [examples/README.md](examples/README.md) for runnable CUDA, C, C++, PTX, and Bash examples, including GPU computation, device-memory transfers, and stdin/stdout/stderr forwarding.

## Runtime recovery

If Colab terminates a runtime, its local session record can become stale or be removed by `status`. Use `Colab session shell -s NAME`, `Colab exec -s NAME COMMAND`, or `Colab run -s NAME FILE` to recover that named session. Unqualified commands select the first currently active session. With none active, run `Colab session create` or `Colab session start`. Provisioning still depends on Google account quota and GPU availability; failures are reported before your command is submitted.

A replacement runtime has a fresh filesystem. `run` uploads the specified local source again; other remote files and installed packages must be restored separately. Recovery never retries a user command that may already have started.

Regression checks: `python3 -m unittest discover -s tests -v` and `cargo clippy -- -D warnings`.

## Google Drive storage

```sh
Colab drive mount
Colab exec 'ls /content/drive/MyDrive'
```

`mount-drive` recovers the runtime if needed, then uses Colab's official `drive.mount` flow at `/content/drive`. An existing mount is reused rather than forcibly remounted. The CLI verifies that the mount and My Drive root are accessible before returning success. Your personal **My Drive** storage root is `/content/drive/MyDrive`; the enclosing mount can also expose Shared drives when available.

Google may request browser consent before the mount can complete. The standard Drive filesystem integration requests broad account permissions, including permission to modify and delete Drive files; it is not a read-only mount. The CLI does not create or delete Drive files as part of mounting.

Drive files persist when a Colab runtime is replaced, but the mount does not. Every create/start, shell, execution, and transfer operation checks/restores the mount and the configured Drive workspace before running. Separate mounting is no longer an optional setup requirement. Google may require renewed browser consent on a replacement runtime; if so, the operation stops until consent is completed. Preferences are stored in `~/.config/Colab/drive/`.

## Recursive copy and sync

The executable is named `Colab`. All commands use the selected account, session, shared connection sockets, and settings.

Prefix the remote endpoint with `colab:` and use an absolute runtime path. An unprefixed path is local. Exactly one endpoint must be remote.

```sh
# Recursive upload and download; no -r flag needed.
Colab files copy ./data colab:/content/drive/MyDrive/data
Colab files copy colab:/content/drive/MyDrive/results ./results

# Preview without modifying either data tree.
Colab files copy ./data colab:/content/drive/MyDrive/data --dry-run

# Sync local → remote.
Colab files sync ./data '>' colab:/content/drive/MyDrive/data

# Sync remote → local (the right endpoint is the source).
Colab files sync ./data '<' colab:/content/drive/MyDrive/data

# Sync both directions.
Colab files sync ./data '<>' colab:/content/drive/MyDrive/data

# Preview the bidirectional plan.
Colab files sync ./data '<>' colab:/content/drive/MyDrive/data --dry-run
```

**Quote the direction symbols.** Without quotes, your shell treats `>`, `<`, and `<>` as redirection operators instead of passing them to the CLI. Keep normal filesystem paths after the `colab:` prefix; `~` expansion is only supported for local paths. A session can be selected with `--session NAME`.

`cp` accepts a single file or a directory and always recurses through directories. Directory **contents merge directly into the specified destination**; an extra source-directory level is not added. A file copied to an existing directory keeps its basename. Otherwise, the destination is the exact output filename. Existing files at matching paths are replaced, but unrelated destination files are retained.

`sync` operates on directory trees. One-way sync copies new or changed source files and replaces destination files at matching paths. Bidirectional sync uses a saved content-hash baseline to determine which side changed. On the first run, unique files from both sides are merged, identical files are skipped, and differing files at the same path require explicit resolution. If both sides later edit the same file differently, the entire plan is rejected before copying anything. Resolve the edits manually or deliberately choose one-way sync.

**Neither copy nor sync deletes extra files.** In bidirectional sync, a file missing on one side is restored from the other side. Deletion propagation and destructive mirroring are not implemented. Files are compared using SHA-256, not timestamps. Empty directories and file executable permissions are supported; symlinks and non-regular files are rejected before copying. Owners, timestamps, ACLs, and extended attributes are not preserved.

### Transfer recovery and limitations

The CLI checks the Drive mount before transferring to or from `/content/drive`. If Drive is not authorized or cannot be mounted, the operation stops before transfer rather than creating files in the runtime's temporary mount directory.

Each file is checksummed and written to a temporary file alongside its destination, then installed with an atomic rename. An interrupted or corrupt file never replaces an existing destination file. Optimistic checks also reject destination edits detected between planning and installation. A copy is atomic per file, not across an entire directory tree. Names beginning with `.Colab-` are reserved for staging and excluded from recursive inventories, so a partial staging file left by a forcibly killed process is never synced as user data. Simultaneous external edits can still require reconciliation; stop writers for a stable dataset snapshot.

Transfers spool one file at a time through temporary storage on your PC, keeping memory bounded. Allow enough free local disk space for the largest file. This first implementation hashes complete trees and does not provide block-delta transfers or byte-level resume. After a disconnect, rerun the same sync command; completed identical files are skipped. Previously submitted shell commands are never automatically replayed.

Bidirectional sync baselines and pair locks live in `~/.config/Colab/sync/`. Keep this directory to retain change history. If it is removed, the next bidirectional run applies the first-run rules. A baseline advances only after both sides have been rescanned and confirmed to match; a failed transfer does not advance it.

### List recorded sync targets

```sh
Colab files targets                  # all recorded pairs, locally (no Google connection)
Colab files targets --all-sessions   # every session
Colab files targets --json           # machine-readable output
Colab --session other files targets # a particular session
```

This command is local and works when Colab is disconnected. It shows each pair, the last successful direction, and the last successful sync time in UTC. Successful syncs (including one-way syncs and unchanged runs) register/update their pair automatically. Failed attempts, dry runs, and plain copies do not register successful sync targets. These are remembered one-shot sync pairs, not background synchronization jobs.

Target metadata is stored next to baselines in `~/.config/Colab/sync/*.target.json`. Version 0.4.0 and earlier saved only hashed baseline filenames and content hashes, without endpoint paths, so their target names cannot be reconstructed. Rerun each older sync command once to register it for listing. Existing content baselines are retained.

## Create independent named sessions

```sh
Colab session create trainer --runtime t4
Colab session create preprocessing --runtime cpu
Colab session create experiments --runtime a100 --high-mem

# Select the desired session on every operation (before or after the command).
Colab session shell -s trainer
Colab exec -s preprocessing 'uname -a'
Colab run -s trainer examples/vector_add.cu -- 4096
Colab files copy -s trainer ./data colab:/content/data
Colab files sync -s trainer ./data '>' colab:/content/data
Colab drive mount -s trainer
Colab session list
Colab session disconnect -s trainer
Colab session delete -s trainer
```

`session create [NAME]` always requests a **separate runtime**, even when another runtime of the same type exists. Omit NAME for an unused two-word generated name (e.g. `SunnyRiver`); supply NAME or `-s NAME` for an explicit name. Duplicate local names are rejected; use `session start -s NAME` to reuse or recover an existing session. Names may contain 1–64 ASCII letters, digits, dots, underscores, or hyphens. There is no hardcoded default session name. Operations without `-s` use the first active session.

`--runtime` accepts `cpu`, `t4`, `l4`, `g4`, `h100`, `a100`, `v5e1`, and `v6e1` (case-insensitive). `v5e-1` and `v6e-1` are accepted TPU aliases. New sessions default to `t4`. `--high-mem` requests high-RAM hardware when supported; Google's backend may ignore it for hardware with a fixed memory shape. Accelerator and high-memory availability, plus the number of concurrent sessions, depend on Google's account entitlements, quota, and capacity. This CLI cannot raise those limits.

Runtime choices are saved per name in `~/.config/Colab/runtimes.json`, separately from Google's expiring assignment metadata. `session start -s NAME` and automatic recovery retain the selected accelerator and memory setting even if `status` prunes an expired session. Specifying a different runtime for an active session is rejected; create a new name to use different hardware. Allocation and registry changes are serialized locally so concurrent create/recovery calls do not overwrite each other's session metadata.

Drive preferences and sync histories are scoped by session name. Each independent endpoint gets its own shared SSH transport. `attach --endpoint ENDPOINT -s NAME` intentionally reuses an existing runtime; use `create` for independent resources.

## Project identity

The repository directory, Cargo package, and executable are named `Colab`. App-owned settings and the SSH key live under `~/.config/Colab/`. Google-owned technical identifiers (`google-colab-cli`, `colab_cli`, `~/.config/colab-cli`) and the `colab:` remote-path protocol retain their upstream names. Setup installs the backend launcher privately under `~/.config/Colab/backend/bin/` and invokes the backend through its Python module, so it does not shadow the `Colab` executable on case-insensitive filesystems.

## Drive workspaces and automatic PC-to-Colab sync

```sh
# Generated session name, Drive ~/Code workspace, T4 by default.
Colab session create

# Explicit name and another folder within My Drive.
Colab session create trainer --runtime t4 --drive-path '~/Code/Trainer'

# Push this PC directory into the Drive workspace before operations.
Colab session create trainer --runtime t4 --drive-path '~/Code/Trainer' --local-dir ~/Code/my-project

Colab exec pwd               # first active session; mount/check workspace, then run
Colab session shell -s trainer       # sync PC folder first, then enter Drive workspace
Colab exec -s trainer 'ls'   # sync PC folder again before executing

# Deliberately skip the automatic PC push for one operation (still mount Drive).
Colab --no-auto-sync exec -s trainer 'ls'
Colab --no-auto-sync files copy -s trainer colab:/content/drive/MyDrive/Code/Trainer/results ./results
```

`--drive-path` is interpreted in Google Drive, not the PC filesystem: `~/Code`, `Code`, `MyDrive/Code`, and `/content/drive/MyDrive/Code` refer to the same place. Missing folders are created. Absolute paths must be under `/content/drive`; parent traversal (`..`) is rejected. Configuration is per named session in `~/.config/Colab/workspaces/`. Existing sessions without saved workspace settings default to Google Drive `~/Code`.

`--local-dir` enables a one-way **PC → Colab** sync into that workspace. It runs before create completes, before `exec`/`run`, before opening a shell, and before explicit copy/sync operations. It is an operation-boundary sync, not a continuous filesystem mount or watcher. Matching remote files are replaced by PC changes; extra remote files are preserved. If local files disappear or a transfer fails, the remote command/shell does not start. Use `--no-auto-sync` when retrieving remote edits that should not first be overwritten by the PC version. To keep independent projects apart, give their sessions different Drive working folders.

All workspace and sync steps complete before the requested user command is submitted. Google may still require renewed browser consent after a runtime replacement. If workspace setup fails after a runtime was allocated, the error names that session and explains how to finish with `Colab drive mount -s NAME`; it does not silently allocate another session or execute in the wrong directory.

## Readable failures

Normal runtime commands never start an unexpected OAuth prompt or consume program stdin for login. They say `Run Colab auth login` when credentials are missing or expired. Fresh local state directories are created before Google's session/lock code runs. Backend failures are translated to short errors for missing login, Internet/connectivity problems, denied access, and session/quota/capacity limits. A quota/precondition rejection does not necessarily mean multiple sessions are universally prohibited: eligibility and capacity are controlled by Google. Delete an unused session, choose CPU, or retry later as the message suggests.

Python and Typer exceptions are handled at the subprocess boundary; chained backend tracebacks are not printed in normal operation. Explicit `Colab auth login`/`setup` still guide Google's consent flow. Interrupted user commands are never automatically replayed. The tests cover a fresh HOME with the installed Google backend, missing login without prompts, offline errors, quota errors, server-order default selection, generated names, and workspace/pre-execution sync.

## Compatibility with earlier commands

The previous flat spellings remain accepted as hidden compatibility aliases, but help and examples use the grouped tree:

| Earlier spelling | Current command |
| --- | --- |
| `Colab login` | `Colab auth login` |
| `Colab create` / `start` / `sessions` / `status` | `Colab session create` / `start` / `list` / `status` |
| `Colab shell` | `Colab session shell` |
| `Colab session connect` | `Colab session shell` |
| `Colab disconnect` / `stop` / `attach` / `url` | `Colab session disconnect` / `delete` / `attach` / `url` |
| `Colab cp` | `Colab files copy` (`files cp` is also accepted) |
| `Colab sync` | `Colab files sync` |
| `Colab sync-targets` | `Colab files targets` |
| `Colab mount-drive` | `Colab drive mount` |

`exec`, `run`, and `setup` retain their direct spellings because they are the primary execution and bootstrap actions.

## Interactive shell prompt

`Colab session shell` shows the selected session name and the last two folders of the current path:

```text
(SandyFinch) MyDrive/Code $
```

For example, `/content/drive/MyDrive/Code` becomes `MyDrive/Code`; after entering `/content/drive/MyDrive/Code/src`, the prompt becomes `(SandyFinch) Code/src $`. It updates as you change directories and always uses a literal `$`, even though the runtime account is root. The shell-specific prompt does not modify the runtime's global Bash configuration or affect `Colab exec` output.

The interactive prompt colors the session name **cyan**, the last two path components **blue**, and `$` **green**. After a failed command, `$` turns **red**. `NO_COLOR=1` or `TERM=dumb` selects a plain prompt. Color sequences are marked as nonprinting so long command lines wrap correctly; the colors apply only to the interactive shell.

## List runtime types

```sh
Colab runtime list           # supported CPU/GPU/TPU choices; no login needed
Colab runtime list --json    # machine-readable catalog
Colab session list          # active sessions in your Google account
```

The runtime catalog lists the same `--runtime` choices accepted by `session create`: `cpu`, `t4`, `l4`, `g4`, `h100`, `a100`, `v5e1`, and `v6e1`. It works offline and does not allocate anything. It is a catalog of CLI-supported types, not a live account entitlement or available-capacity check; Google determines which ones your account can allocate.

`Colab session delete` terminates the selected runtime and releases its resources. It preserves files stored in Google Drive. `Colab session stop` remains accepted as a hidden compatibility alias.
