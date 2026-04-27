"""
Train RandomForestClassifier using the exact production feature pipeline.
Reads raw HR/GSR from ml/data/training_data.csv, simulating a 1Hz time series
through the backend DataPipeline and BaselineTracker.
"""
from __future__ import annotations

import csv
import os
import pickle
import time
from typing import List, Tuple

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

# Ensure we can import from the backend directory
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import backend.pipeline
from backend.config import BaselineConfig, PipelineConfig
from backend.features import BaselineTracker, compute_features
from backend.pipeline import DataPipeline

# Class mapping required by prompt
LABEL_MAP = {
    0: "CALM",
    1: "ANXIETY",
}


def process_dataset(
    data_rows: List[dict],
    cfg_pipe: PipelineConfig,
    cfg_base: BaselineConfig,
) -> Tuple[List[List[float]], List[str]]:
    """Runs a dedicated pipeline and baseline tracker on a sequence of raw data."""
    pipeline = DataPipeline(cfg_pipe)
    baseline = BaselineTracker(
        calibration_seconds=0,
        fixed_hr=75,
        fixed_gsr=500,
    )

    X: List[List[float]] = []
    y: List[str] = []

    current_time = 1000.0

    for row in data_rows:
        try:
            hr = float(row["hr"])
            gsr = float(row["gsr"])
            raw_label = int(row["label"])
        except (ValueError, KeyError, TypeError):
            continue

        if raw_label not in LABEL_MAP:
            continue
            
        label = LABEL_MAP[raw_label]

        current_time += 1.0

        # Monkey-patch time
        # Lambda default arg `ct=current_time` accurately captures current value 
        # avoiding late binding inside loop during time calls
        backend.pipeline.time.time = lambda ct=current_time: ct

        # 1. Feed into Pipeline
        out = pipeline.push(hr, gsr)
        if out is None:
            continue

        sm_hr, sm_gsr = out

        # 2. Feed BaselineTracker
        baseline.update_with_sample(current_time, sm_hr, sm_gsr)

        window = pipeline.window_points()

        # 3. Request FeatureVector using exact production logic
        fv = compute_features(
            window,
            baseline,
            current_time,
            stress_w_hr=cfg_base.stress_w_hr,
            stress_w_gsr=cfg_base.stress_w_gsr,
        )

        # 4. Save vectors
        if fv is not None:
            X.append(fv.as_list())
            y.append(label)

    return X, y


def train() -> None:
    data_path = os.path.join("ml", "data", "training_data.csv")
    if not os.path.isfile(data_path):
        print(f"Error: Training data not found at {data_path}")
        return

    # Initialize production configurations
    cfg_pipe = PipelineConfig()
    cfg_base = BaselineConfig()

    print(f"Loading {data_path} ...")
    raw_data = []
    with open(data_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {str(k).lower().strip(): v for k, v in row.items()}
            raw_data.append(row_lower)

    if not raw_data:
        print("Error: No data loaded.")
        return

    original_time_fn = time.time
    try:
        # 1. Process dataset chronologically first to ensure sliding window is accurate
        print("Processing chronological raw data into feature vectors...")
        X, y = process_dataset(raw_data, cfg_pipe, cfg_base)
    finally:
        # Restore standard time function
        backend.pipeline.time.time = original_time_fn

    if not X or not y:
        print("Error: Not enough FeatureVectors generated to train.")
        return

    # 2. Split FEATURE DATA
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        shuffle=True,
        random_state=42
    )
    # Class distribution
    train_counts = {"CALM": y_train.count("CALM"), "ANXIETY": y_train.count("ANXIETY")}
    test_counts = {"CALM": y_test.count("CALM"), "ANXIETY": y_test.count("ANXIETY")}
    print(f"Successfully generated FeatureVectors.")
    print(f"Train distribution: {train_counts} ({len(X_train)} samples)")
    print(f"Test distribution:  {test_counts} ({len(X_test)} samples)")

    # Train Model
    print("Training RandomForestClassifier...")
    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=5,
        min_samples_split=10,
        min_samples_leaf=5,
        random_state=42,
        class_weight="balanced"
    )
    clf.fit(X_train, y_train)

    # Evaluate
    train_acc = clf.score(X_train, y_train)
    test_acc = clf.score(X_test, y_test)
    
    print(f"Training Accuracy: {train_acc * 100:.2f}%")
    print(f"Test Accuracy: {test_acc * 100:.2f}%")

    # Save artifacts
    os.makedirs("ml", exist_ok=True)
    model_output_path = os.path.join("ml", "model.pkl")
    
    with open(model_output_path, "wb") as f:
        pickle.dump(clf, f)

    print(f"Model successfully saved to {model_output_path}")


if __name__ == "__main__":
    train()
