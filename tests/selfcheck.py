"""Verify ONLY this candidate's exact allowlist; no external state or network."""
import ast
import hashlib
import json
from pathlib import Path
import re

def check_candidate(root):
    paths = []

    def walk(directory):
        for p in directory.iterdir():
            assert not p.is_symlink(), 'candidate_symlink'
            if p == root / '.git' and (p.is_dir() or p.is_file()):
                continue
            assert p.name not in ('__pycache__', '.git', '.venv', 'venv'), 'candidate_runtime_garbage'
            paths.append(p)
            if p.is_dir():
                walk(p)

    walk(root)
    manifest = json.loads((root/'ALLOWLIST.json').read_text())
    actual = {str(p.relative_to(root)) for p in paths if p.is_file() and p.name != 'ALLOWLIST.json'}
    assert actual == set(manifest), 'candidate_inventory_mismatch'
    for name, digest in manifest.items():
        p = root/name
        data = p.read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, 'candidate_hash_mismatch'
        text = data.decode()
        assert not re.search(r'(?:cli_|ou_|oc_)[a-fA-F0-9]{16,}', text), 'identity_shape'
        assert not re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text), 'private_key'
        assert not re.search(r'(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})', text), 'credential_shape'
        if p.suffix == '.py':
            ast.parse(text,filename=name)
    return len(manifest)


if __name__ == '__main__':
    count = check_candidate(Path(__file__).resolve().parents[1])
    print('candidate-allowlist: PASS;',count,'files; SHA-256, static scan and Python AST: PASS')
    print('Only this candidate read; no legacy directory, credentials, services or git accessed')
