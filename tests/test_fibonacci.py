# tests/test_fibonacci.py
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

def test_fibonacci_thirty():
    # Verifying the core hackathon challenge requirement
    assert fibonacci(30) == 832040