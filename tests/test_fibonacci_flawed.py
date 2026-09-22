# tests/test_fibonacci_flawed.py

def fibonacci(n):
    if n <= 1:
        return n
    # Intentional bug: adding + 1 to force a failure and trigger self-healing
    return fibonacci(n-1) + fibonacci(n-2) + 1  

def test_fibonacci_thirty():
    # This will fail because of the +1 bug above
    assert fibonacci(30) == 832040