# GitHub Ready

This project is prepared for Git LFS so the repository can keep all files while staying under the 24 MB per-file limit.

Tracked with LFS:

- `Elite55.exe`
- `elite_trade.db`
- `elite_trade.db-shm`
- `elite_trade.db-wal`
- `.venv/**`
- `build/**`
- `dist/**`

The local software is unchanged. `elite_trade.db` is recreated automatically if missing.

Before pushing to GitHub:

1. Make sure Git LFS is installed.
2. Run `git lfs install` once in the repo.
3. Add and commit normally.
