# train_model.py

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
import joblib
import os

print("--- Starting Model Training ---")

# --- 1. Load and Prepare Data ---
RISKLOG_PATH = 'static/data/risklog.csv'
MODEL_DIR = 'ml_model'
MODEL_PATH = os.path.join(MODEL_DIR, 'safety_model.joblib')
COLUMNS_PATH = os.path.join(MODEL_DIR, 'model_columns.joblib')

# Create directory if it doesn't exist
os.makedirs(MODEL_DIR, exist_ok=True)

df = pd.read_csv(RISKLOG_PATH)

# Drop rows where our target is missing
df.dropna(subset=['risk_level'], inplace=True)

# --- 2. Feature Engineering ---
# Convert date to useful features (e.g., month)
df['date'] = pd.to_datetime(df['date'])
df['month'] = df['date'].dt.month

# Define features (X) and target (y)
features = [
    'temperature_c', 'rainfall_mm', 'humidity_percent', 'disease_cases',
    'month', 'district', 'place', 'disaster_event'
]
target = 'risk_level'

X = df[features]
y = df[target]

# One-Hot Encode categorical features
# This converts text like 'Idukki' or 'Landslide' into numerical format
X = pd.get_dummies(X, columns=['district', 'place', 'disaster_event'], dummy_na=False)

# Save the column order and names! This is CRITICAL for prediction.
model_columns = X.columns
joblib.dump(model_columns, COLUMNS_PATH)
print(f"Model columns saved to {COLUMNS_PATH}")

# --- 3. Split Data for Training and Testing ---
# We use stratify=y to ensure the test set has the same proportion of risk levels as the training set
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
print(f"Data split: {len(X_train)} training samples, {len(X_test)} testing samples.")

# --- 4. Train the Random Forest Model ---
# We use class_weight='balanced' to handle cases where you have more 'Low Risk' data than 'High Risk'
model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced', oob_score=True)
print("Training RandomForestClassifier...")
model.fit(X_train, y_train)

# --- 5. Evaluate the Model ---
print("\n--- Model Evaluation ---")
print(f"Out-of-Bag Score: {model.oob_score_:.4f}") # A good measure of accuracy on unseen data
y_pred = model.predict(X_test)
print(f"Test Accuracy: {accuracy_score(y_test, y_pred):.4f}")
print("\nClassification Report:")
print(classification_report(y_test, y_pred))

# --- 6. Save the Trained Model ---
joblib.dump(model, MODEL_PATH)
print(f"\nModel trained and saved successfully to {MODEL_PATH}")
print("--- Training Complete ---")