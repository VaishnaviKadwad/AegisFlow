try:
    import quantum_crypto_lib
except ModuleNotFoundError:
    import hashlib
    print("FALLBACK_SUCCESS")
