import random
import time
from typing import Callable, Any, TypeVar

T = TypeVar("T")


def calculate_exponential_backoff(attempt: int, base_delay: float = 0.5, max_delay: float = 30.0) -> float:
    """
    Implements AWS Exponential Backoff with Full Jitter.
    delay = Uniform(0, min(max_delay, base_delay * 2^attempt))
    """
    temp_delay = min(max_delay, base_delay * (2 ** attempt))
    sleep_time = random.uniform(0, temp_delay)
    return sleep_time


def execute_with_retry(
    operation: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,)
) -> T:
    """
    Executes a callable with exponential backoff and jitter.
    """
    attempt = 0
    while True:
        try:
            return operation()
        except retryable_exceptions as e:
            attempt += 1
            if attempt > max_retries:
                raise e
            sleep_duration = calculate_exponential_backoff(attempt, base_delay, max_delay)
            time.sleep(sleep_duration)

