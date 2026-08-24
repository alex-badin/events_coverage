# The Neo box

"Neo" is a Windows machine on the local network that holds the two large files this
project does not copy to the Mac:

| Path on Neo | Size (bytes, measured 2026-08-03) | What |
|---|---|---|
| `C:\emb_test\ec\data\processed\qwen3emb_8b\vectors.f16` | 31,524,814,848 | one 4096-number embedding per post, 16-bit |
| `C:\emb_test\ec\data\processed\qwen3emb_8b\index.tsv` | 168,222,824 | message id, source, date — one line per embedding, sorted by date |
| `C:\emb_test\ec\news_slim.db` | 2,607,493,120 | trimmed copy of the news database |

Retrieval runs there rather than here: the Mac sends a handful of query vectors, Neo
multiplies them against the window and sends back one score per post.
`src/events_coverage/matching.py` → `qwen_retrieve_remote()` drives it over SSH, running
`scripts/remote/neo_qwen_retrieve.py` (the copy on Neo lives at `C:\emb_test\ec\`).

The SSH target is `NEO_HOST` in `.env`, as `user@host` — not in the repo, since this one is
public and that is a machine address. `matching.get_neo_host()` reads it and fails with a
clear message if it is missing.

## Which Python to run there, and why it matters

`matching.py` sets `NEO_PYTHON` to `C:\emb_test\numpy_env\Scripts\python.exe`. Override with
the `NEO_PYTHON` environment variable if that ever moves.

The older path, `C:\emb_test\venv\Scripts\python.exe`, no longer works. Running it prints:

```
'C:\emb_test\venv\Scripts\python.exe' was blocked by your organization's Device Guard policy.
```

Windows is enforcing Smart App Control on that machine, which refuses to run programs it
cannot recognise as signed and widely used. Two readings from the box confirm the state:
`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState` is `0x1`,
and `Win32_DeviceGuard.CodeIntegrityPolicyEnforcementStatus` is `2`. The active policy files
under `C:\Windows\System32\CodeIntegrity\CIPolicies\Active` are dated 2026-07-14 — after the
embeddings were built at the end of June 2026, which is why this worked before and stopped.

The block is not blanket. What was measured on 2026-08-03:

- `C:\emb_test\pythons\cpython-3.12-windows-x86_64-none\python.exe` (downloaded by uv) **runs**.
- Inside it, `import ctypes` **fails**: `DLL load failed while importing _ctypes: An
  Application Control policy has blocked this file.` So Python's own bundled `_ctypes.pyd`
  is refused even though `python.exe` is allowed.
- `import numpy` **works** and matrix multiplication gives correct answers, so numpy's
  compiled files are accepted where `_ctypes.pyd` is not.

`neo_qwen_retrieve.py` needs only `sys` and `numpy`, so it is unaffected.

## How numpy got installed without pip

pip cannot be used on that machine at the moment, for two separate reasons:

1. The uv-downloaded Python refuses installs into itself — `This environment is managed by uv
   and should not be modified` (PEP 668).
2. pip's own code imports `ctypes`, which is blocked, so it crashes partway through.

So the environment was made by hand:

```
C:\emb_test\pythons\cpython-3.12-windows-x86_64-none\python.exe -m venv C:\emb_test\numpy_env
```

A plain `python -m venv` copies the original signed `python.exe`, and the copy is allowed to
run. `ensurepip` inside it still fails, so the numpy wheel was downloaded on the Mac from
PyPI (`numpy-2.5.1-cp312-cp312-win_amd64.whl`), copied over with `scp`, and unpacked straight
into `C:\emb_test\numpy_env\Lib\site-packages` with Python's own `zipfile`. numpy reports
version 2.5.1 there.

Adding another package later means repeating that: fetch the matching
`cp312-cp312-win_amd64` wheel, copy it over, unpack it with `zipfile`. Anything that needs
`ctypes` will not work regardless.

## Checking it still works

```sh
ssh "$NEO_HOST" "C:\emb_test\numpy_env\Scripts\python.exe -c \"import numpy;print(numpy.__version__)\""
```

If that prints a version, the retrieval path is fine. If it prints a Device Guard or
Application Control message, the policy has changed again and the environment has to be
rebuilt the same way.
