# backend/aiservice.py

from flask import Blueprint, jsonify, request, current_app, session
from models import db, Destination, User, RouteHistory
import pandas as pd
import datetime
import google.generativeai as genai
import json
import joblib

ai_bp = Blueprint('ai_service', __name__)

# --- Load the ML Model and Columns on App Start (Used for other AI features) ---
try:
    safety_model = joblib.load('ml_model/safety_model.joblib')
    model_columns = joblib.load('ml_model/model_columns.joblib')
    print("AI Service: Random Forest safety model loaded successfully.")
except Exception as e:
    safety_model = None
    model_columns = None
    print(f"AI Service WARNING: Could not load ML model: {e}. Some features may be limited.")


# --- Centralized AI Model Configuration ---
_gemini_model = None
GEMINI_MODEL_NAME = 'gemini-flash-lite-latest'

def _get_gemini_model():
    """Initializes and returns a singleton instance of the Gemini generative model."""
    global _gemini_model
    if _gemini_model:
        return _gemini_model
    api_key = current_app.config.get('GEMINI_API_KEY')
    if not api_key:
        print("AI Service WARNING: GEMINI_API_KEY not configured.")
        return None
    try:
        genai.configure(api_key=api_key)
        _gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        return _gemini_model
    except Exception as e:
        print(f"AI Service ERROR: Failed to initialize Gemini model: {e}")
        return None

# --- Helper Functions ---
def _build_travel_tip(stop_names: list[str] | None) -> str:
    """Return a short travel tip string for the given stop names."""
    tip_locations = ", ".join(stop_names) if stop_names else "your destinations"
    return f"Enjoy your journey! When travelling through {tip_locations}, always check local news for the latest updates on weather and road conditions."

def _generate_ai_prediction(destination_district: str, model):
    """
    Uses the AI model to predict future risks based on historical data.
    """
    if risk_log_df.empty:
        return {'disaster_alert': 'Historical data is unavailable for analysis.', 'disease_alert': 'Historical data is unavailable for analysis.', 'overall_safety_level': 'Moderate Risk'}

    two_years_ago = datetime.datetime.now() - datetime.timedelta(days=730)
    district_data = risk_log_df[
        (risk_log_df['district'].str.lower() == destination_district.lower()) &
        (risk_log_df['date'] > two_years_ago)
    ]

    if district_data.empty:
        return {'disaster_alert': f'No significant events recorded for {destination_district} in the last two years. General caution is advised.', 'disease_alert': 'No specific disease outbreaks reported recently.', 'overall_safety_level': 'Low Risk'}

    disaster_counts = district_data[district_data['disaster_event'].str.lower() != 'none']['disaster_event'].value_counts().to_dict()
    disease_total = district_data['disease_cases'].sum()
    recent_event_date = district_data['date'].max().strftime('%B %Y') if not district_data.empty else "N/A"
    
    summary = (
        f"Historical data for {destination_district}, Kerala:\n"
        f"- Recent disaster events: {str(disaster_counts) if disaster_counts else 'None significant'}.\n"
        f"- Total disease cases in 2 years: {disease_total}.\n"
        f"- Most recent event was in: {recent_event_date}.\n"
        f"- Current month is {datetime.datetime.now().strftime('%B')}.\n"
    )

    prompt = f"""
    You are a travel risk assessment AI for Kerala, India. Analyze the provided historical data summary and consider common seasonal patterns (e.g., monsoon is June-September).
    Based on this data: "{summary}"
    Generate a short, helpful, predictive alert for a traveler visiting {destination_district}.
    Your response MUST be a simple JSON object with three keys: "disaster_alert", "disease_alert", and "overall_safety_level".
    - "disaster_alert": A 1-2 sentence prediction about potential environmental or weather risks.
    - "disease_alert": A 1-2 sentence prediction about potential health risks.
    - "overall_safety_level": A single string classification from ["Low Risk", "Moderate Risk", "High Risk"] based on your analysis.
    If risk is low, state that clearly. Provide a forward-looking advisory, not just a summary of the past.
    Example: {{"disaster_alert": "Given the history of landslides and the current monsoon season, travelers should monitor weather forecasts.", "disease_alert": "A slight increase in water-borne diseases is possible. Drink bottled water.", "overall_safety_level": "Moderate Risk"}}
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
        prediction = json.loads(cleaned_response)
        if 'overall_safety_level' not in prediction:
            prediction['overall_safety_level'] = 'Moderate Risk'
        return prediction
    except Exception as e:
        print(f"AI Prediction ERROR: {e}")
        return {
            'disaster_alert': 'Could not generate a prediction. Always check local news and weather reports.', 
            'disease_alert': 'General health precautions are recommended.',
            'overall_safety_level': 'Moderate Risk'
        }

# --- Data Loading ---
KERALA_DISTRICTS_ORDER = [
    "Thiruvananthapuram", "Kollam", "Pathanamthitta", "Alappuzha", "Kottayam",
    "Idukki", "Ernakulam", "Thrissur", "Palakkad", "Malappuram",
    "Kozhikode", "Wayanad", "Kannur", "Kasaragod"
]
try:
    csv_path = 'static/data/risklog.csv'
    risk_log_df = pd.read_csv(csv_path, skipinitialspace=True, on_bad_lines='skip')
    risk_log_df.columns = [c.strip().lower().replace(' ', '_') for c in risk_log_df.columns]
    if 'date' in risk_log_df.columns:
        risk_log_df['date'] = pd.to_datetime(risk_log_df['date'], errors='coerce')
    print("AI Service: Risk log CSV loaded successfully.")
except Exception as e:
    print(f"AI Service WARNING: Could not read {csv_path}: {e}. Risk analysis will be limited.")
    risk_log_df = pd.DataFrame()

# --- UNIFIED SAFETY CALCULATION (from safety.html logic) ---
MAX_RISK_SCORE = 75.0  # Use float for division

def calculate_safety_rule_based(district_name, place_name=None):
    """
    Calculates a safety score and level based on historical data,
    replicating the logic from the admin safety analysis page for consistency.
    """
    status_map = {'High Risk': 'unsafe', 'Moderate Risk': 'caution', 'Low Risk': 'safe'}
    
    if risk_log_df.empty:
        return {'text': 'Moderate Risk', 'class': 'caution', 'score': 50}

    two_years_ago = datetime.datetime.now() - datetime.timedelta(days=730)
    mask = (risk_log_df['district'].str.lower() == district_name.lower()) & (risk_log_df['date'] > two_years_ago)
    if place_name:
        mask &= (risk_log_df['place'].str.lower() == place_name.lower())
    
    relevant_events = risk_log_df[mask]

    if relevant_events.empty:
        return {'text': 'Low Risk', 'class': 'safe', 'score': 0}

    raw_score = 0
    raw_score += (relevant_events['disaster_event'].str.lower() != 'none').sum() * 5
    raw_score += (relevant_events['disease_cases'] > 0).sum() * 3
    raw_score += (relevant_events['temperature_c'] > 34).sum() * 1
    raw_score += (relevant_events['rainfall_mm'] > 60).sum() * 2

    if raw_score > MAX_RISK_SCORE * 0.60:
        safety_text = "High Risk"
    elif raw_score > MAX_RISK_SCORE * 0.25:
        safety_text = "Moderate Risk"
    else:
        safety_text = "Low Risk"

    normalized_score = min(round((raw_score / MAX_RISK_SCORE) * 100), 100)

    return {
        'text': safety_text,
        'class': status_map.get(safety_text, 'caution'),
        'score': normalized_score
    }


# --- Main Safety Calculation Wrapper ---
def calculate_safety(district_name, place_name):
    """
    Calculates safety using the single, unified rule-based method
    to ensure consistency across the entire application.
    """
    return calculate_safety_rule_based(district_name, place_name)


# --- API Endpoints ---
@ai_bp.route('/api/generate-route', methods=['POST'])
def generate_ai_route():
    data = request.get_json()
    source_district, dest_district = data.get('source'), data.get('destination')
    interest = data.get('interest')
    budget_str = data.get('budget')
    model = _get_gemini_model()

    try:
        source_index = KERALA_DISTRICTS_ORDER.index(source_district)
        dest_index = KERALA_DISTRICTS_ORDER.index(dest_district)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid source or destination provided.'}), 400

    travel_path_districts = KERALA_DISTRICTS_ORDER[source_index : dest_index + 1] if source_index < dest_index else list(reversed(KERALA_DISTRICTS_ORDER[dest_index : source_index + 1]))
    districts_for_stops = travel_path_districts[1:]

    query = Destination.query.filter(Destination.Name.in_(districts_for_stops))
    if interest: query = query.filter(Destination.Type == interest)
    if budget_str:
        try:
            user_budget = int(budget_str)
            query = query.filter(Destination.budget <= user_budget)
        except (ValueError, TypeError): pass

    potential_stops = query.all()
    if not potential_stops:
        return jsonify({'success': False, 'message': 'No stops found matching your criteria.'})

    analyzed_stops = []
    for stop in potential_stops:
        safety_info = calculate_safety(stop.Name, stop.Place)
        analyzed_stops.append({
            'id': stop.Destination_id, 'name': stop.Place, 'district': stop.Name,
            'type': stop.Type.capitalize(), 'budget': stop.budget,
            'safety_text': safety_info['text'], 'safety_class': safety_info['class']
        })
    
    safety_order = {'Low Risk': 0, 'Moderate Risk': 1, 'High Risk': 2}
    sorted_stops = sorted(analyzed_stops, key=lambda x: safety_order.get(x['safety_text'], 99))
    best_stops = sorted_stops[:3]

    alerts, stop_names_for_tip = [], []
    if not risk_log_df.empty:
        two_years_ago = datetime.datetime.now() - datetime.timedelta(days=730)
        severity_map = {'landslide': 'alert-high', 'flood': 'alert-high', 'cyclone': 'alert-high', 'heatwave': 'alert-medium', 'drought': 'alert-medium'}
        for stop in best_stops:
            stop_names_for_tip.append(stop['name'])
            mask = ((risk_log_df['place'].str.lower() == stop['name'].lower()) & (risk_log_df['district'].str.lower() == stop['district'].lower()) & (risk_log_df['date'] > two_years_ago))
            for _, alert_row in risk_log_df[mask].iterrows():
                event_type = alert_row.get('disaster_event', 'Alert')
                if str(event_type).lower() == 'none': continue
                severity = severity_map.get(str(event_type).lower(), 'alert-low')
                alerts.append({
                    'type': f"{str(event_type).capitalize()} in {stop['name']}",
                    'description': alert_row.get('description', 'No details available.'),
                    'date': alert_row['date'].strftime('%d %B %Y') if pd.notna(alert_row.get('date')) else 'N/A',
                    'severity_class': severity 
                })

    tip = _build_travel_tip(stop_names_for_tip)
    
    overall_safety_text = "Low Risk"
    if any(s['safety_class'] == 'unsafe' for s in best_stops): overall_safety_text = "High Risk"
    elif any(s['safety_class'] == 'caution' for s in best_stops): overall_safety_text = "Moderate Risk"
    status_map = {'Low Risk': 'safe', 'Moderate Risk': 'caution', 'High Risk': 'unsafe'}

    prediction_alerts = {'disaster_alert': 'AI analysis not available.', 'disease_alert': 'AI analysis not available.', 'overall_safety_level': 'Moderate Risk'}
    if model:
        prediction_alerts = _generate_ai_prediction(dest_district, model)

    final_route = {
        'source': source_district, 'destination': dest_district, 'interest': interest.capitalize() if interest else 'Any',
        'overall_safety_text': overall_safety_text, 'overall_safety_class': status_map.get(overall_safety_text, 'caution'),
        'stops': best_stops, 'alerts': alerts, 'tip': tip,
        'prediction': prediction_alerts
    }
    
    if 'user_id' in session:
        try:
            new_history = RouteHistory(
                user_id=session['user_id'],
                source=source_district, destination=dest_district,
                interest=(interest or 'Any'), budget=(budget_str or 'Any'),
                stops_data=json.dumps(best_stops)
            )
            db.session.add(new_history)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"ERROR: Could not save route history. {e}")
    
    return jsonify({'success': True, 'route': final_route})

@ai_bp.route('/api/chat', methods=['POST'])
def chat_with_gemini():
    user_message = (request.get_json() or {}).get('message')
    if not user_message: return jsonify({'success': False, 'error': 'No message provided.'}), 400
    model = _get_gemini_model()
    if not model: return jsonify({'success': False, 'error': 'AI assistant is not configured.'}), 500
    try:
        prompt = f"""
        You are a friendly travel assistant for Kerala, India. Provide safe and useful advice.
        Format answers using Markdown (lists, bold text, etc.).
        User question: "{user_message}"
        """
        response = model.generate_content(prompt)
        return jsonify({'success': True, 'reply': response.text})
    except Exception as e:
        return jsonify({'success': False, 'error': "AI assistant connection error."}), 500

@ai_bp.route('/api/tip', methods=['POST', 'GET'])
def get_travel_tip():
    stops = (request.get_json(silent=True) or {}).get('stops') if request.method == 'POST' else None
    model = _get_gemini_model()
    if not model:
        return jsonify({'success': True, 'tip': _build_travel_tip(stops), 'source': 'fallback'})
    try:
        locations_text = ", ".join(str(x) for x in stops) if stops else "your destinations"
        prompt = f"""
        Create a short, friendly, practical travel safety tip for a trip in Kerala through {locations_text}.
        Include a 1-2 sentence summary, up to 3 short bullet points, and a packing/precaution sentence.
        Return plain text only, no markdown.
        """
        response = model.generate_content(prompt)
        generated_tip = response.text.strip() if response.text else _build_travel_tip(stops)
        return jsonify({'success': True, 'tip': generated_tip, 'source': 'gemini'})
    except Exception as e:
        return jsonify({'success': True, 'tip': _build_travel_tip(stops), 'source': 'fallback', 'warning': 'AI generation failed.'})