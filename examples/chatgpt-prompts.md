# Example prompts

## Clone and inspect a repo

Use local-shell-mcp. Clone `https://github.com/fwerkor/FrameDiff.git` into `/workspace/FrameDiff`, inspect the tree, search for `fullnet`, and report the main entry points.

## Make a change safely

Use local-shell-mcp. In `/workspace/FrameDiff`, create a new branch `ai/example-change`, make the requested code edit with `edit_file` or `apply_patch`, run relevant tests, show `git diff --stat`, run `secret_scan`, commit, and push the branch.

## Playwright

Use local-shell-mcp. Open `https://example.com` with Playwright, save a screenshot to `screenshots/example.png`, and return the page title and visible text.

## One-command remote worker onboarding

Use local-shell-mcp. Create a remote worker invite named `npu-4card` with workdir `/home/cyh/FrameDiff`. Show me only the pasteable join command and then, after I say it has run, call `remote_list_machines` to confirm it is online.

## Remote machine diagnostics

Use local-shell-mcp. With `run_shell_tool` and `machine` set to `npu-4card`, run `pwd`, `hostname`, `python3 --version`, `git log -1 --oneline`, and `npu-smi info` from `/home/cyh/FrameDiff`.

## Remote code edit and test

Use local-shell-mcp. On remote machine `hpc-a`, inspect `/home/cyh/project` with `tree_view`, search with `grep_search`, edit with `edit_file` or `apply_patch`, and run the relevant test plus `git diff` with `run_shell_tool`. Set `machine` to `hpc-a` on every call.


## Remote host-to-host file transfer

Use local-shell-mcp. Copy `/data/run-42/result.tar.zst` from remote machine `hpc-a` to `/scratch/imports/result.tar.zst` on remote machine `hpc-b` using `transfer_path` with both machine endpoints, then verify the destination size and checksum with `run_shell_tool` on `hpc-b`.

## Remote directory transfer through the controller

Use local-shell-mcp. Copy directory `/data/run-42` from remote machine `hpc-a` to `/scratch/run-42` on remote machine `hpc-b` using `transfer_path` with both machine endpoints. The remote machines cannot SSH to each other, so use the controller-mediated transfer rather than `scp` or `rsync`.
