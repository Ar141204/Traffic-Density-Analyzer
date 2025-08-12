from main import app, db

def init_database():
    """Initialize the database and create tables"""
    with app.app_context():
        # Create all tables
        db.create_all()
        
        print("Database initialized successfully!")

if __name__ == "__main__":
    init_database() 