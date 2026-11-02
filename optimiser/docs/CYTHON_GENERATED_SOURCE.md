# Cython-generated native source

`native/_nv14_native.pyx` is the maintained wrapper source.
`native/_nv14_native.c` is generated locally and **is not tracked in Git**.
All other `native/*.c` files, including `nv14_render_native.c`, are handwritten.

## Building

Install a C compiler, Python development headers, and Cython:

```sh
python -m pip install 'Cython>=3.2.4,<4'
python build_native.py
```

`build_native.py` regenerates the C wrapper if it is missing or older than the
`.pyx` file, then compiles only outdated native extensions by default. It also supports:

- `--force`: force a full native rebuild, even if objects are up to date.
- `--force-cython`: regenerate the C wrapper even if its timestamps are current.
- `--no-force`: legacy alias for the default incremental behavior.
- `--check`: inspect existing native extensions without regenerating or compiling.

PEP 517 / setuptools builds also run Cython automatically, using the build
requirement specified in `pyproject.toml`. Source distributions include the
`.pyx`, not generated C, so a build requires Cython at build time but execution
of already-compiled extensions does not.

## Removing the old tracked generated file

After applying the build-system patch, run this once in the repository:

```sh
git rm --cached native/_nv14_native.c
```

This removes generated C from Git while leaving your local file available for
incremental builds. The new `.gitignore` prevents it being added again.
