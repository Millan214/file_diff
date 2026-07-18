"""Configuration for the compare-dataframes pipeline."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

KEY_COLUMNS = ["id"]

INPUT_LEFT = PROJECT_ROOT / "data" / "input" / "file1.csv"
INPUT_RIGHT = PROJECT_ROOT / "data" / "input" / "file2.csv"
# Execution folders (execution=<ts>/) and the rebuilt executions.json index
# live here, under data/executions/ (kept separate from data/input/).
DATA_OUTPUT_ROOT = PROJECT_ROOT / "data" / "executions"
ACCEPTED_DIFFERENCES_PATH = PROJECT_ROOT / "docs" / "layer_4_compare_values" / "accepted_differences.csv"

CSV_DELIMITER = ","
CSV_HEADER_ROW = 0

PER_COLUMN_NUMERIC_TOLERANCE = {}
