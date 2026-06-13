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

Use local-shell-mcp. On remote machine `npu-4card`, run `pwd`, `hostname`, `python3 --version`, `git log -1 --oneline`, and `npu-smi info` from `/home/cyh/FrameDiff`. Use `remote_run_shell_tool`.

## Remote code edit and test

Use local-shell-mcp. On remote machine `hpc-a`, inspect `/home/cyh/project`, search for the requested symbol with `remote_grep_search`, edit the file with `remote_edit_file` or `remote_apply_patch`, run the relevant test with `remote_run_shell_tool`, then show `remote_git_diff_tool`.


## Remote host-to-host file transfer

Use local-shell-mcp. Copy `/data/run-42/result.tar.zst` from remote machine `hpc-a` to `/scratch/imports/result.tar.zst` on remote machine `hpc-b` using `remote_copy_file`, then verify the destination size and checksum with `remote_run_shell_tool`.

## Remote directory transfer through the controller

Use local-shell-mcp. Copy directory `/data/run-42` from remote machine `hpc-a` to `/scratch/run-42` on remote machine `hpc-b` using `remote_copy_dir`. The remote machines cannot SSH to each other, so use the control-server-mediated transfer tools rather than `scp` or `rsync`.
