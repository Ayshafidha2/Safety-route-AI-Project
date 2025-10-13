# models.py
from db import db
import datetime
import json

# Association table for the many-to-many relationship between users and favorites
user_favorites = db.Table('user_favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('User_table.User_id'), primary_key=True),
    db.Column('destination_id', db.Integer, db.ForeignKey('Destination.Destination_id'), primary_key=True)
)


class User(db.Model):
    __tablename__ = 'User_table'
    User_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Username = db.Column(db.String(45), nullable=False)
    name = db.Column(db.String(45), nullable=False)
    Email = db.Column(db.String(45), unique=True, nullable=False)
    Password = db.Column(db.String(45), nullable=False)
    Create_id = db.Column(db.DateTime, nullable=False, default=datetime.datetime.now)
    role = db.Column(db.String(45), nullable=False)

    favorites = db.relationship('Destination', secondary=user_favorites, lazy='subquery',
                                backref=db.backref('favorited_by', lazy=True))

    route_histories = db.relationship('RouteHistory', backref='user', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<User {self.Username}>'

class Destination(db.Model):
    __tablename__ = 'Destination'
    Destination_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Place = db.Column(db.String(100), nullable=False) 
    Name = db.Column(db.String(20), nullable=False) # This is the District Name
    Type = db.Column(db.Enum('beach', 'hill', 'wildlife'), nullable=False)
    Description = db.Column(db.Text, nullable=True)
    Create_id = db.Column(db.DateTime, nullable=False, default=datetime.datetime.now) 
    budget = db.Column(db.Integer, nullable=True)
    search_count = db.Column(db.Integer, nullable=False, default=0)
    image_url = db.Column(db.String(255), nullable=True)

    @property
    def safety_info(self):
        """
        Dynamic property that returns a dictionary with safety rating data,
        calculated using the centralized safety function for consistency.
        """
        try:
            from backend.aiservice import calculate_safety
            return calculate_safety(self.Name, self.Place)
        except Exception as e:
            print(f"Error calculating safety for {self.Name}, {self.Place}: {e}")
            # Return a consistent default safety object if calculation fails
            return {
                'text': "Moderate",
                'class': "caution",
                'score': 50
            }

    def __repr__(self):
        return f'<Destination {self.Name}>'


# Model to store generated route history
class RouteHistory(db.Model):
    __tablename__ = 'route_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('User_table.User_id'), nullable=False)
    source = db.Column(db.String(100), nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    interest = db.Column(db.String(50), nullable=True)
    budget = db.Column(db.String(50), nullable=True)
    stops_data = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    @property
    def stops(self):
        """Returns the stops data from JSON string."""
        return json.loads(self.stops_data) if self.stops_data else []

    def __repr__(self):
        return f'<RouteHistory {self.id} for User {self.user_id}>'