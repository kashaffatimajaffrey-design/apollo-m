"""
CEREBRO Supervised Classifier Trainer
Trains a fake news detector on the labeled fake_news_corpus.csv dataset.
Model: TF-IDF + Logistic Regression (fast, accurate, interpretable)
Output: models/cerebro_classifier.pkl
"""

import logging
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.pipeline import Pipeline

log = logging.getLogger("APOLLO-M.CEREBRO.Trainer")


def train_cerebro_classifier(
        corpus_path: str = "data/fake_news_corpus.csv",
        model_path: str = "models/cerebro_classifier.pkl") -> dict:
    """
    Train supervised fake news classifier on labeled corpus.
    Returns evaluation metrics.
    """
    log.info("Loading fake news corpus...")
    df = pd.read_csv(corpus_path)
    print(f"Loaded {len(df)} articles — columns: {df.columns.tolist()}")

    # Clean and prepare
    df = df.dropna(subset=["content", "is_fake"])
    df["content"] = df["content"].astype(str).str.strip()
    df = df[df["content"].str.len() > 20]

    X = df["content"].values
    y = df["is_fake"].astype(int).values

    print(f"Training data: {len(X)} articles")
    print(f"Fake: {y.sum()} | Real: {(y==0).sum()}")

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Build pipeline: TF-IDF + Logistic Regression
    log.info("Training TF-IDF + Logistic Regression pipeline...")
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(
            max_features=50000,
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.95,
            sublinear_tf=True
        )),
        ("clf", LogisticRegression(
            max_iter=1000,
            C=1.0,
            class_weight="balanced",
            random_state=42
        ))
    ])

    pipeline.fit(X_train, y_train)

    # Evaluate
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]
    accuracy = accuracy_score(y_test, y_pred)

    print(f"\n✅ CEREBRO Classifier trained!")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"\nClassification Report:")
    print(classification_report(y_test, y_pred,
                                target_names=["Real News", "Fake News"]))

    # Save model
    Path(model_path).parent.mkdir(exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump(pipeline, f)
    print(f"Model saved → {model_path}")

    return {
        "accuracy": accuracy,
        "model_path": model_path,
        "train_size": len(X_train),
        "test_size": len(X_test)
    }


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    train_cerebro_classifier()