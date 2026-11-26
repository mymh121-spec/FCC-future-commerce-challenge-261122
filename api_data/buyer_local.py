"""Linux 고객 기기에서 배송 프로필을 저장하고 읽는 CLI."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from getpass import getpass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import gi

gi.require_version("Secret", "1")
from gi.repository import GLib, Secret

FIELDS = {"recipient": "수령인", "phone": "연락처", "address": "배송지"}
SCHEMA = Secret.Schema.new("org.fcc.BuyerProfile", Secret.SchemaFlags.NONE,
                           {"account": Secret.SchemaAttributeType.STRING})


@contextmanager
def locked_profile(account):
    if not account.strip():
        raise ValueError("로컬 계정 이름을 입력하세요.")
    namespace = hashlib.sha256(account.strip().encode()).hexdigest()
    root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    folder = root / "fcc-buyer" / namespace
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield folder / "buyer_profile.enc", {"account": namespace}
    finally:
        os.close(fd)


def profile(action, account, values=None):
    if action not in ("save", "read", "delete"):
        raise ValueError("지원하지 않는 작업입니다.")
    if action == "save":
        if not isinstance(values, dict) or set(values) != set(FIELDS):
            raise ValueError("수령인, 연락처, 배송지가 필요합니다.")
        if not all(isinstance(v, str) and 0 < len(v.strip()) <= 512 for v in values.values()):
            raise ValueError("각 필드에 1~512자 사이의 값을 입력하세요.")
    with locked_profile(account) as (path, attrs):
        key = Secret.password_lookup_sync(SCHEMA, attrs, None)
        if action == "delete":
            path.unlink(missing_ok=True)
            if key and not Secret.password_clear_sync(SCHEMA, attrs, None):
                raise ValueError("키링 삭제를 완료하지 못했습니다. 삭제를 다시 실행하세요.")
            return
        if not key:
            if action != "save" or path.exists():
                raise ValueError("프로필 또는 이 계정의 암호화 키를 찾을 수 없습니다.")
            key = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()
            if not Secret.password_store_sync(SCHEMA, attrs, Secret.COLLECTION_DEFAULT,
                                              "FCC 배송 프로필", key, None):
                raise ValueError("기기 키링에 저장하지 못했습니다.")
        cipher = AESGCM(base64.b64decode(key, validate=True))
        aad = ("fcc-profile-v1:" + attrs["account"]).encode()
        if action == "read":
            payload = path.read_bytes()
            return json.loads(cipher.decrypt(payload[:12], payload[12:], aad))
        nonce = os.urandom(12)
        payload = nonce + cipher.encrypt(nonce, json.dumps(values, ensure_ascii=False).encode(), aad)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            tmp = Path(output.name)
            try:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("save", "read", "delete"))
    parser.add_argument("--account", default="local-owner", help="현재 OS 사용자 안에서 구분할 로컬 프로필 이름")
    parser.add_argument("--field", choices=FIELDS, help="터미널에 표시할 프로필 필드")
    args = parser.parse_args()
    if (args.action == "read") != bool(args.field):
        parser.error("read 명령에는 표시할 --field 하나가 필요합니다.")
    try:
        values = {k: getpass(label + " 입력: ") for k, label in FIELDS.items()} if args.action == "save" else None
        result = profile(args.action, args.account, values)
        if args.field:
            print(result[args.field])
        else:
            print("저장했습니다." if args.action == "save" else "삭제했습니다.")
    except (OSError, ValueError, GLib.Error, InvalidTag):
        parser.exit(1, "프로필을 처리할 수 없습니다. 계정, 파일 및 잠금 해제된 기기 키링을 확인하세요.\n")
