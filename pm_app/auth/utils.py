"""
Password hashing utilities for the PM/RCA system.
Uses scrypt as the default hashing method for security.
"""

from werkzeug.security import check_password_hash, generate_password_hash

# Default method: scrypt with recommended parameters for Flask/Werkzeug
# (cost=16, block_size=8, parallelism=1, key_length=64)
DEFAULT_HASH_METHOD = "scrypt:32768:8:1"


def hash_password(plain_text: str, method: str = DEFAULT_HASH_METHOD) -> str:
    """
    Hash a plain-text password using the specified method.

    Args:
        plain_text: The password to hash (plain string)
        method: The hashing method (default: scrypt with secure parameters)

    Returns:
        A hashed password string suitable for storage.
    """
    if not plain_text:
        raise ValueError("Password cannot be empty")
    return generate_password_hash(plain_text, method=method)


def verify_password(password_hash: str, plain_text: str) -> bool:
    """
    Verify a plain-text password against a stored hash.

    Args:
        password_hash: The stored hash (from the database)
        plain_text: The plain-text password to verify

    Returns:
        True if the password matches the hash, False otherwise.
    """
    if not password_hash or not plain_text:
        return False
    return check_password_hash(password_hash, plain_text)
