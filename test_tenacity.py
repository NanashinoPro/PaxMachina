import os
import time
from tenacity import retry, stop_after_attempt, wait_exponential

class Foo:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=3))
    def do_something(self):
        print("Trying...")
        raise ValueError("Oops")

f = Foo()
try:
    f.do_something()
except Exception as e:
    print(e)
