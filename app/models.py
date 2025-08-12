from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Analysis(db.Model):
    """Model for traffic analysis results"""
    __tablename__ = 'analysis'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(10), nullable=False)  # 'image' or 'video'
    upload_path = db.Column(db.String(255), nullable=False)
    result_path = db.Column(db.String(255), nullable=False)
    vehicle_count = db.Column(db.Integer, nullable=False)
    density_percentage = db.Column(db.Float, nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Vehicle type counts
    car_count = db.Column(db.Integer, default=0)
    truck_count = db.Column(db.Integer, default=0)
    bus_count = db.Column(db.Integer, default=0)
    motorcycle_count = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f"<Analysis {self.id} - {self.filename}>" 