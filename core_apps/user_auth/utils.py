import random
import string

def generate_otp(length=6) -> str:
    """
        Generate 6 digits OTP code
    """
    return "".join(random.choices(string.digits, k=length))
