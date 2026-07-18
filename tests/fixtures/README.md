# Test Fixtures

6 CSV pairs (5–20 rows each) covering the layer specs' edge cases and success scenarios.
All have an `id` column for row-matching against `KEY_COLUMNS = ["id"]` in config.

| Pair | Left | Right | Tests | Expected outcome |
|---|---|---|---|---|
| **identical** | 5 rows: id 1–5, names & values | Identical to left | Layer success path | All layers: success |
| **column_drift** | id, name, value, `status` | id, name, value, `department` | Column set mismatch; common = {id, name, value} | Layer 2: completed-with-differences; Layer 3–4 continue with common columns |
| **row_drift_dupes** | id 1 (dup), 2–4 | id 2–6 | Duplicate key in left; left-only (1), inner (2–4), right-only (5–6) | Layer 3: completed-with-differences; duplicates excluded from Layer 4 |
| **value_drift** | 5 rows identical shape | id 2 (Bob→Robert, 200→205), id 4 (Diana, 400→410) | Value mismatches in common columns | Layer 4: completed-with-differences |
| **encoding_conflict** | UTF-8 content with accented chars (Alíce, Böb) | ISO-8859-1; plain ASCII | Encoding detection; D4 normalization | Layer 1: hard-failure if encodings are incompatible |
| **empty_common** | col_a, col_b, col_c | col_d, col_e, col_f | Zero overlapping columns | Layer 2: hard-failure (D5); no common set to proceed with |

## Usage in tests

```python
import pandas as pd
from pathlib import Path

fixtures_dir = Path(__file__).parent / "fixtures"

# Load a pair:
df_left = pd.read_csv(fixtures_dir / "identical_left.csv")
df_right = pd.read_csv(fixtures_dir / "identical_right.csv")

# Or parametrize:
PAIRS = [
    ("identical", "success"),
    ("column_drift", "soft_gate"),
    ("row_drift_dupes", "soft_gate"),
    ("value_drift", "soft_gate"),
    ("encoding_conflict", "hard_gate"),
    ("empty_common", "hard_gate"),
]

@pytest.mark.parametrize("pair,expected", PAIRS)
def test_layer(pair, expected):
    left_path = fixtures_dir / f"{pair}_left.csv"
    right_path = fixtures_dir / f"{pair}_right.csv"
    ...
```
