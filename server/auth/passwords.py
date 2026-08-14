"""Password hashing.

argon2id with the library defaults, which are current and sensibly tuned. The
only thing worth knowing here is ``needs_rehash``: when we raise the parameters
later, existing users get upgraded silently on their next successful login
rather than being locked out or left on weak hashes forever.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_LENGTH = 10
MAX_LENGTH = 200


class WeakPassword(Exception):
    pass


def validate(password):
    """Length is the only rule worth enforcing.

    Composition rules ("one capital, one symbol") measurably push people toward
    Password1! and away from passphrases, so there aren't any.
    """
    if password is None or len(password) < MIN_LENGTH:
        raise WeakPassword(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise WeakPassword(f"password must be at most {MAX_LENGTH} characters")
    return password


def hash_password(password):
    return _hasher.hash(validate(password))


def verify(user, password):
    """True if this password belongs to this user, rehashing it if our
    parameters have moved on since they last logged in."""
    if not user or not user.password_hash or not password:
        return False
    try:
        _hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    return True
