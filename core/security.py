import hashlib, hmac, secrets

def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters.")
    salt=secrets.token_bytes(16)
    rounds=310_000
    digest=hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"

def verify_password(password: str, saved: str) -> bool:
    try:
        alg, rounds, salt, digest=saved.split("$",3)
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),int(rounds)).hex()
        return alg=="pbkdf2_sha256" and hmac.compare_digest(actual,digest)
    except Exception:
        return False
