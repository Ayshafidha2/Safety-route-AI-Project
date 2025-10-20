# backend/views.py

from flask import render_template, flash, jsonify, request, session, redirect, url_for
from functools import wraps
from . import views_bp
from models import db, Destination, User, RouteHistory
from sqlalchemy import func, desc
from sqlalchemy.orm import joinedload
from backend.aiservice import calculate_safety 

# Centralized district data (no changes here)
KERALA_DISTRICTS_COORDS = {
    'Alappuzha': {'lat': 9.4981, 'lng': 76.3388}, 'Ernakulam': {'lat': 9.9816, 'lng': 76.2996},
    'Idukki': {'lat': 9.8392, 'lng': 76.9746}, 'Kannur': {'lat': 11.8745, 'lng': 75.3704},
    'Kasaragod': {'lat': 12.5002, 'lng': 74.9896}, 'Kollam': {'lat': 8.8932, 'lng': 76.6141},
    'Kottayam': {'lat': 9.5916, 'lng': 76.5222}, 'Kozhikode': {'lat': 11.2588, 'lng': 75.7804},
    'Malappuram': {'lat': 11.0736, 'lng': 76.0742}, 'Palakkad': {'lat': 10.7867, 'lng': 76.6548},
    'Pathanamthitta': {'lat': 9.2648, 'lng': 76.7870}, 'Thiruvananthapuram': {'lat': 8.5241, 'lng': 76.9366},
    'Thrissur': {'lat': 10.5276, 'lng': 76.2144}, 'Wayanad': {'lat': 11.6854, 'lng': 76.1320}
}

# Decorator (no changes here)
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("You must be logged in to view this page.", "danger")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Page Routes (Only /search is modified) ---

@views_bp.route('/')
def landing():
    return render_template('landing.html')

@views_bp.route('/dashboard')
@login_required
def dashboard():
    # No changes needed in this route
    try:
        districts = sorted(list(KERALA_DISTRICTS_COORDS.keys()))
        types_query = db.session.query(Destination.Type).distinct().all()
        interests = [t[0] for t in types_query if t[0] is not None]
        
        favorite_ids = set()
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user: favorite_ids = {dest.Destination_id for dest in user.favorites}
    except Exception as e:
        print(f"Error fetching dashboard data: {e}")
        districts, interests, favorite_ids = [], [], set()
        flash("Could not load dashboard data from the database.", "danger")
    
    return render_template('user/user_dashboard.html', 
                           districts=districts, interests=interests,
                           favorite_ids_json=list(favorite_ids),
                           districts_coords_json=KERALA_DISTRICTS_COORDS,
                           active_page='dashboard')

@views_bp.route('/search')
@login_required
def search():
    """Renders the destination search page."""
    try:
        destinations = Destination.query.order_by(Destination.Name, Destination.Place).all()
        
        favorite_ids = set()
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user: 
                favorite_ids = {dest.Destination_id for dest in user.favorites}
        
        # ### MODIFIED: Attach the 'is_favourite' flag to each destination object ###
        # This is CRITICAL for the template to know which hearts should be filled on page load.
        for dest in destinations:
            dest.is_favourite = dest.Destination_id in favorite_ids

    except Exception as e:
        print(f"Error fetching destinations for search page: {e}")
        destinations = []
        flash("Could not load destination data.", "danger")
    
    return render_template('user/search.html', 
                           destinations=destinations,
                           active_page='search')


@views_bp.route('/favorites')
@login_required
def favorites():
    # No changes needed in this route
    user = User.query.get(session['user_id'])
    return render_template('user/favorites.html', 
                           destinations=user.favorites, 
                           active_page='favorite')

@views_bp.route('/previous-routes')
@login_required
def previous_routes():
    # No changes needed in this route
    user = User.query.get(session['user_id'])
    histories = RouteHistory.query.filter_by(user_id=user.User_id).order_by(desc(RouteHistory.created_at)).all()
    return render_template('user/previous_routes.html', 
                           histories=histories, 
                           active_page='previous_routes')

# --- API Endpoints (One modified, one added) ---

@views_bp.route('/api/search-destinations')
def api_search_destinations():
    """API endpoint for live searching destinations."""
    query = request.args.get('q', '', type=str)

    # ### MODIFIED: Get the user's favorite IDs to include in the response ###
    favorite_ids = set()
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            favorite_ids = {dest.Destination_id for dest in user.favorites}
    
    base_query = Destination.query
    if query:
        search_term = f"%{query}%"
        search_results = base_query.filter(
            (Destination.Place.ilike(search_term)) | (Destination.Name.ilike(search_term))
        ).order_by(Destination.Name).all()
    else:
        search_results = base_query.order_by(Destination.Name).all()

    results_list = []
    for dest in search_results:
        safety_info = dest.safety_info
        results_list.append({
            'id': dest.Destination_id, 'place': dest.Place, 'name': dest.Name,
            'type': dest.Type.capitalize() if dest.Type else 'N/A',
            'description': dest.Description, 'budget': dest.budget, 'image_url': dest.image_url,
            'safety': {'text': safety_info['text'], 'class_name': safety_info['class']},
            'is_favourite': dest.Destination_id in favorite_ids  # ### ADDED THIS LINE ###
        })

    return jsonify(results_list)

@views_bp.route('/api/increment-search-count/<int:dest_id>', methods=['POST'])
def increment_search_count(dest_id):
    # No changes needed in this endpoint
    try:
        destination = Destination.query.get(dest_id)
        if destination:
            destination.search_count = (destination.search_count or 0) + 1
            db.session.commit()
            return jsonify({'success': True, 'message': 'Count incremented.'})
        return jsonify({'success': False, 'message': 'Destination not found.'}), 404
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Server error.'}), 500

# ### ADDED: A new unified endpoint to toggle favorite status ###
# This single endpoint handles both adding and removing, which is what the JavaScript expects.
@views_bp.route('/api/favorites/toggle/<int:dest_id>', methods=['POST'])
@login_required
def toggle_favorite(dest_id):
    """Adds a destination to favorites if it's not there, otherwise removes it."""
    try:
        user = User.query.get(session['user_id'])
        destination = Destination.query.get_or_404(dest_id)
        
        is_favourite_after_toggle = False
        if destination in user.favorites:
            # It's already a favorite, so remove it
            user.favorites.remove(destination)
            db.session.commit()
            is_favourite_after_toggle = False # It is no longer a favorite
        else:
            # It's not a favorite, so add it
            user.favorites.append(destination)
            db.session.commit()
            is_favourite_after_toggle = True # It is now a favorite

        return jsonify({'success': True, 'is_favourite': is_favourite_after_toggle})
    except Exception as e:
        db.session.rollback()
        print(f"Error in toggle_favorite: {e}")
        return jsonify({'success': False, 'message': 'Server error occurred.'}), 500

# The old add/remove endpoints are no longer used by the new search page, but can be kept for other purposes.
@views_bp.route('/api/favorites/add/<int:dest_id>', methods=['POST'])
@login_required
def add_favorite(dest_id):
    try:
        user = User.query.get(session['user_id'])
        destination = Destination.query.get_or_404(dest_id)
        if destination not in user.favorites:
            user.favorites.append(destination)
            db.session.commit()
        return jsonify({'success': True, 'message': 'Added to favorites.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@views_bp.route('/api/favorites/remove/<int:dest_id>', methods=['POST'])
@login_required
def remove_favorite(dest_id):
    # ... (this is still used by favorites.html, so it's important to keep)
    try:
        user = User.query.get(session['user_id'])
        destination = Destination.query.get_or_404(dest_id)
        if destination in user.favorites:
            user.favorites.remove(destination)
            db.session.commit()
        return jsonify({'success': True, 'message': 'Removed from favorites.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
    
# Delete route history endpoint (no changes here)
@views_bp.route('/api/delete-route-history/<int:history_id>', methods=['POST'])
@login_required
def delete_route_history(history_id):
    try:
        # Find the route history entry that matches the ID and belongs to the current user
        history_to_delete = RouteHistory.query.filter_by(id=history_id, user_id=session['user_id']).first()

        if history_to_delete:
            db.session.delete(history_to_delete)
            db.session.commit()
            # MODIFIED: A more specific success message
            return jsonify({'success': True, 'message': 'Route history was successfully deleted.'})
        else:
            # The entry either doesn't exist or doesn't belong to this user
            return jsonify({'success': False, 'message': 'Route history not found or access denied.'}), 404
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting route history: {e}")
        return jsonify({'success': False, 'message': 'A server error occurred while deleting the route.'}), 500