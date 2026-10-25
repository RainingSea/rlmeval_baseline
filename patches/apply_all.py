#!/usr/bin/env python3
"""RLMEval venv 补丁: lean-dojo==2.2.0 的 3 处 + plasTeX kpsewhich 的 1 处。
用法: /root/miniconda3/envs/rlmeval/bin/python patches/apply_all.py  (可重复运行, 已打则跳过)。
每个替换都断言锚点唯一, 打不上会报错退出而不是静默失败。"""
import re
import sys
import sysconfig
from pathlib import Path

VENV = Path(sys.prefix)
SITE = Path(sysconfig.get_paths()["purelib"])
LEAN_PY = SITE / "lean_dojo" / "data_extraction" / "lean.py"
TEX_PY = SITE / "plasTeX" / "TeX.py"


def patch(path: Path, replacements: list[tuple[str, str]], name: str) -> None:
    src = path.read_text()
    changed = False
    for old, new in replacements:
        sentinel = new[:40]
        if sentinel in src.replace(old, "", 1):
            continue  # already applied
        count = src.count(old)
        if count != 1:
            sys.exit(f"[{name}] anchor count={count} (expect 1), abort: {old[:60]!r}")
        src = src.replace(old, new)
        changed = True
    if changed:
        path.write_text(src)
    print(f"[{name}] {'patched' if changed else 'already ok'}")


# ---- lean-dojo 2.2.0: 1) normalize_url 剥 .git ----
patch(
    LEAN_PY,
    [(
        '''    # Remove trailing `/`.
    url = _URL_REGEX.fullmatch(url)["url"]  # type: ignore
    return ssh_to_https(url)''',
        '''    # Remove trailing `/`.
    url = _URL_REGEX.fullmatch(url)["url"]  # type: ignore
    url = ssh_to_https(url)
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url''',
    )],
    "lean_dojo normalize_url",
)

# ---- lean-dojo 2.2.0: 2) url_to_repo 限流 stub ----
STUB = '''

def _github_repo_name_stub(url: str):
    """Name-only stand-in for github.Repository; safe when commits are full hashes."""

    class _GithubRepoNameStub:
        def __init__(self, url: str) -> None:
            parts = url.rstrip("/").split("/")
            self.full_name = "/".join(parts[-2:])
            self.name = parts[-1]
            self.html_url = url
            self.clone_url = url + ".git"
            self.description = None
            self.default_branch = "master"

    return _GithubRepoNameStub(url)

'''
patch(
    LEAN_PY,
    [
        (
            "def url_to_repo(",
            STUB.lstrip("\n") + "def url_to_repo(",
        ),
        (
            '''            if repo_type == RepoType.GITHUB:
                return GITHUB.get_repo("/".join(url.split("/")[-2:]))''',
            '''            if repo_type == RepoType.GITHUB:
                if os.environ.get("LEAN_DOJO_NO_GITHUB_API"):
                    return _github_repo_name_stub(url)
                return GITHUB.get_repo("/".join(url.split("/")[-2:]))''',
        ),
    ],
    "lean_dojo url_to_repo",
)

# ---- lean-dojo 2.2.0: 3) lean4 tag -> git ls-remote ----
patch(
    LEAN_PY,
    [(
        '''    global LEAN4_REPO
    if LEAN4_REPO is None:
        LEAN4_REPO = GITHUB.get_repo("leanprover/lean4")
    assert "content" in config_dict, "config_dict must have a 'content' field"
    version = get_lean4_version_from_config(config_dict["content"].strip())''',
        '''    assert "content" in config_dict, "config_dict must have a 'content' field"
    version = get_lean4_version_from_config(config_dict["content"].strip())
    if os.environ.get("LEAN_DOJO_NO_GITHUB_API"):
        import subprocess

        tag = version if version.startswith("v") else "v" + version
        if tag.startswith("vnightly-"):
            repo_url = "https://github.com/leanprover/lean4-nightly"
            tag = "v" + version[len("vnightly-"):]
        else:
            repo_url = "https://github.com/leanprover/lean4"
        out = subprocess.run(
            ["git", "ls-remote", repo_url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
            capture_output=True, text=True, timeout=120,
        ).stdout
        peeled = full = None
        for line in out.splitlines():
            sha, ref = line.split("\\t")
            if ref.endswith("^{}"):
                peeled = sha
            else:
                full = sha
        commit = peeled or full
        if commit and re.fullmatch(r"[0-9a-f]{40}", commit):
            return commit
        raise RuntimeError(
            f"LEAN_DOJO_NO_GITHUB_API=1: could not resolve {repo_url} tag {tag} via git ls-remote:\\n{out}"
        )
    global LEAN4_REPO
    if LEAN4_REPO is None:
        LEAN4_REPO = GITHUB.get_repo("leanprover/lean4")''',
    )],
    "lean_dojo lean4 tag",
)

# ---- plasTeX kpsewhich: 绝对路径直接返回 ----
patch(
    TEX_PY,
    [(
        """        restore_texinputs()
        raise FileNotFoundError('Could not find any file named: %s' % name)""",
        """        if os.path.isfile(name):
            return name
        restore_texinputs()
        raise FileNotFoundError('Could not find any file named: %s' % name)""",
    )],
    "plasTeX kpsewhich",
)
print("all patches ok")
