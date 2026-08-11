from __future__ import annotations

import getpass

from app.core.security import hash_password


def main() -> None:
    password = getpass.getpass("Nova senha administrativa (mínimo 12 caracteres): ")
    confirmation = getpass.getpass("Confirme a senha: ")
    if password != confirmation:
        raise SystemExit("As senhas não coincidem.")
    print(hash_password(password))


if __name__ == "__main__":
    main()
