from __future__ import annotations

import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from app import config

def get_mysql_key() -> bytes | None:
    key_str = config.MYSQL_AES_KEY
    if not key_str:
        return None
    try:
        return base64.urlsafe_b64decode(key_str)
    except Exception:
        try:
            return bytes.fromhex(key_str)
        except Exception:
            return key_str.encode('utf-8')

def decrypt_generic(ciphertext_val: str | bytes, key: bytes = None, mode: str = None) -> str:
    """Attempts to decrypt an AES encrypted string generically."""
    if not ciphertext_val:
        return ciphertext_val if isinstance(ciphertext_val, str) else ""
        
    key = key or get_mysql_key()
    if not key:
        return ciphertext_val if isinstance(ciphertext_val, str) else ciphertext_val.decode('utf-8', errors='ignore')
        
    mode = mode or config.MYSQL_AES_MODE
    
    # Try decoding ciphertext
    if isinstance(ciphertext_val, str):
        try:
            ct = base64.urlsafe_b64decode(ciphertext_val)
        except Exception:
            try:
                ct = base64.b64decode(ciphertext_val)
            except Exception:
                try:
                    ct = bytes.fromhex(ciphertext_val)
                except Exception:
                    ct = ciphertext_val.encode('utf-8')
    else:
        ct = ciphertext_val
        
    if len(key) not in [16, 24, 32]:
        # Invalid key length for AES
        return str(ciphertext_val)

    try:
        if mode == "GCM":
            if len(ct) < 28: return str(ciphertext_val) # 12 IV + 16 Tag
            iv = ct[:12]
            payload = ct[12:]
            tag = payload[-16:]
            actual_ct = payload[:-16]
            cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
            decryptor = cipher.decryptor()
            return (decryptor.update(actual_ct) + decryptor.finalize()).decode('utf-8')
            
        elif mode == "CBC":
            if len(ct) < 16: return str(ciphertext_val)
            iv = ct[:16]
            actual_ct = ct[16:]
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            pt = decryptor.update(actual_ct) + decryptor.finalize()
            pad_len = pt[-1]
            if 0 < pad_len <= 16:
                return pt[:-pad_len].decode('utf-8')
            return pt.decode('utf-8')
            
        elif mode == "ECB":
            cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
            decryptor = cipher.decryptor()
            pt = decryptor.update(ct) + decryptor.finalize()
            pad_len = pt[-1]
            if 0 < pad_len <= 16:
                return pt[:-pad_len].decode('utf-8')
            return pt.decode('utf-8')
    except Exception:
        return ciphertext_val if isinstance(ciphertext_val, str) else ciphertext_val.decode('utf-8', errors='ignore')
    
    return str(ciphertext_val)


def decrypt_series(series):
    return series.map(lambda v: decrypt_generic(v) if v is not None and str(v).strip() else v)
