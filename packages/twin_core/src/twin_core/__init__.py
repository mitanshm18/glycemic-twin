"""twin_core: rules shared by the offline pipeline and (later) the API.

No database, web or file-system side effects live here except reading configs.
Every function takes plain pandas/numpy data and returns new data; inputs are never mutated.
"""

__version__ = "0.1.0"
