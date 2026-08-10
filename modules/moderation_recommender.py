"""
APOLLO-M Supervised Moderation Recommendation System
Maps community health features to actionable moderation recommendations.

Input:  CHI score, toxicity rate, polarization, churn rate, echo chamber index
Output: Recommended moderation action + confidence score + reasoning

Model: Random Forest Classifier (interpretable, handles non-linear patterns)
Training: Auto-generated from CHI thresholds + synthetic augmentation
"""

import logging
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

log = logging.getLogger("APOLLO-M.ModerationRecommender")

# ── Action labels ──────────────────────────────────────────────
ACTIONS = {
    0: "NO_ACTION",
    1: "MONITOR",
    2: "WARN",
    3: "INCREASE_MODERATION",
    4: "EMERGENCY_INTERVENTION"
}

ACTION_DESCRIPTIONS = {
    "NO_ACTION":               "Community is healthy. No moderation changes needed.",
    "MONITOR":                 "Minor concerns detected. Increase monitoring frequency.",
    "WARN":                    "Issue community guidelines reminder to users.",
    "INCREASE_MODERATION":     "Enable stricter moderation and fact-checking.",
    "EMERGENCY_INTERVENTION":  "Immediate moderator intervention required. Consider temporary restrictions."
}


def generate_training_data(n_samples: int = 10000) -> pd.DataFrame:
    """
    Generate labeled training data based on CHI thresholds.
    Uses the same calibrated thresholds from the alert system.
    Adds realistic noise to prevent overfitting.
    """
    np.random.seed(42)
    records = []

    for _ in range(n_samples):
        # Generate realistic community feature distributions
        chi            = np.random.uniform(0, 100)
        toxicity_rate  = np.random.beta(2, 10)      # skewed low (most communities aren't very toxic)
        polarization   = np.random.beta(1.5, 8)     # skewed low
        churn_rate     = np.random.beta(3, 5)       # moderate churn is normal
        echo_chamber   = np.random.beta(2, 3)       # moderate echo chamber

        # Label based on CHI + feature thresholds
        if chi < 65 or toxicity_rate > 0.35 or polarization > 0.4:
            action = 4  # EMERGENCY_INTERVENTION
        elif chi < 72 or toxicity_rate > 0.25 or polarization > 0.25:
            action = 3  # INCREASE_MODERATION
        elif chi < 78 or toxicity_rate > 0.18 or churn_rate > 0.7:
            action = 2  # WARN
        elif chi < 85 or toxicity_rate > 0.12 or echo_chamber > 0.6:
            action = 1  # MONITOR
        else:
            action = 0  # NO_ACTION

        records.append({
            "chi":            chi,
            "toxicity_rate":  toxicity_rate,
            "polarization":   polarization,
            "churn_rate":     churn_rate,
            "echo_chamber":   echo_chamber,
            "action":         action
        })

    return pd.DataFrame(records)


def train_moderation_recommender(
        model_path: str = "models/moderation_recommender.pkl") -> dict:
    """Train and save the moderation recommendation model."""

    log.info("Generating training data...")
    df = generate_training_data(n_samples=15000)

    print(f"Training data: {len(df)} samples")
    print(f"Action distribution:")
    for action_id, action_name in ACTIONS.items():
        count = (df["action"] == action_id).sum()
        print(f"  {action_name}: {count} ({count/len(df)*100:.1f}%)")

    # Features and labels
    feature_cols = ["chi", "toxicity_rate", "polarization",
                    "churn_rate", "echo_chamber"]
    X = df[feature_cols].values
    y = df["action"].values

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Build pipeline
    log.info("Training Random Forest classifier...")
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1
        ))
    ])

    pipeline.fit(X_train, y_train)

    # Evaluate
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    print(f"\n✅ Moderation Recommender trained!")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"\nClassification Report:")
    action_names = [ACTIONS[i] for i in range(5)]
    print(classification_report(y_test, y_pred, target_names=action_names))

    # Feature importance
    rf = pipeline.named_steps["clf"]
    importances = rf.feature_importances_
    print("Feature importances:")
    for feat, imp in zip(["chi", "toxicity_rate", "polarization",
                           "churn_rate", "echo_chamber"], importances):
        print(f"  {feat}: {imp:.4f}")

    # Save
    Path(model_path).parent.mkdir(exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump(pipeline, f)
    print(f"\nModel saved → {model_path}")

    return {"accuracy": accuracy, "model_path": model_path}


class ModerationRecommender:
    """
    Generates moderation recommendations for Reddit communities
    based on their health metrics.
    """

    def __init__(self, model_path: str = "models/moderation_recommender.pkl"):
        self.model = None
        self.model_path = model_path
        self._load_model()

    def _load_model(self):
        if Path(self.model_path).exists():
            with open(self.model_path, "rb") as f:
                self.model = pickle.load(f)
            log.info("Moderation recommender loaded successfully.")
        else:
            log.warning("No moderation model found — run train_moderation_recommender() first.")

    def recommend(self, chi: float, toxicity_rate: float,
                  polarization: float, churn_rate: float,
                  echo_chamber: float) -> dict:
        """
        Generate moderation recommendation for a single community.
        Returns action, confidence, and reasoning.
        """
        if self.model is None:
            return {
                "action": "MONITOR",
                "confidence": 0.0,
                "description": "Model not loaded — defaulting to MONITOR.",
                "reasoning": []
            }

        features = np.array([[chi, toxicity_rate, polarization,
                               churn_rate, echo_chamber]])
        action_id = self.model.predict(features)[0]
        probabilities = self.model.predict_proba(features)[0]
        confidence = float(probabilities[action_id])
        action = ACTIONS[action_id]

        # Build reasoning
        reasoning = []
        if chi < 65:
            reasoning.append(f"Critical CHI score ({chi:.1f}) indicates community collapse risk")
        elif chi < 75:
            reasoning.append(f"Low CHI score ({chi:.1f}) indicates poor community health")
        elif chi < 85:
            reasoning.append(f"Moderate CHI score ({chi:.1f}) warrants monitoring")

        if toxicity_rate > 0.25:
            reasoning.append(f"High toxicity rate ({toxicity_rate:.1%}) exceeds safe threshold")
        elif toxicity_rate > 0.15:
            reasoning.append(f"Elevated toxicity rate ({toxicity_rate:.1%}) detected")

        if polarization > 0.25:
            reasoning.append(f"Severe polarization ({polarization:.1%}) indicates community splitting")
        elif polarization > 0.12:
            reasoning.append(f"Moderate polarization ({polarization:.1%}) detected")

        if churn_rate > 0.7:
            reasoning.append(f"High user churn ({churn_rate:.1%}) suggests community exodus")

        if echo_chamber > 0.6:
            reasoning.append(f"Strong echo chamber effect ({echo_chamber:.1%}) detected")

        if not reasoning:
            reasoning.append("Community metrics within healthy range")

        return {
            "action":       action,
            "confidence":   round(confidence, 4),
            "description":  ACTION_DESCRIPTIONS[action],
            "reasoning":    reasoning,
            "probabilities": {
                ACTIONS[i]: round(float(p), 4)
                for i, p in enumerate(probabilities)
            }
        }

    def recommend_batch(self, chm_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate recommendations for all communities in a DataFrame.
        Input: community_health_report.csv style DataFrame
        """
        results = []
        for _, row in chm_df.iterrows():
            rec = self.recommend(
                chi           = row.get("community_health_index", 50),
                toxicity_rate = row.get("toxicity_rate", 0),
                polarization  = row.get("polarization", 0),
                churn_rate    = row.get("churn_rate", 0),
                echo_chamber  = row.get("echo_chamber_index", 0)
            )
            results.append({
                "subreddit":   row.get("subreddit", "unknown"),
                "action":      rec["action"],
                "confidence":  rec["confidence"],
                "description": rec["description"],
                "reasoning":   " | ".join(rec["reasoning"])
            })

        return pd.DataFrame(results)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    train_moderation_recommender()