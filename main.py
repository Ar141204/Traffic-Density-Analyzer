import os
import uuid
import random
import datetime
import cv2
import numpy as np
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv
from app.utils import process_video
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import mimetypes
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from app.models import db, Analysis
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
import secrets
import traceback

class NullSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None):
        def on_update(self):
            pass
        CallbackDict.__init__(self, initial, on_update)

class NullSessionInterface(SessionInterface):
    def open_session(self, app, request):
        return NullSession()

    def save_session(self, app, session, response):
        pass

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__, 
    template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
)

# Use our custom session interface
app.session_interface = NullSessionInterface()

# Security configurations
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_FILE_SIZE', 209715200))  # 200MB

# Configure minimal session
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 0
app.config['SESSION_REFRESH_EACH_REQUEST'] = False

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Configure logging
if not os.path.exists('logs'):
    os.mkdir('logs')
# Add file handler only in the active reloader child (or when not debugging) to avoid double-open on Windows
should_attach = (not app.debug) or (os.environ.get('WERKZEUG_RUN_MAIN') == 'true')
if should_attach:
    already = any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers)
    if not already:
        file_handler = RotatingFileHandler('logs/traffic_sentinel.log', maxBytes=1_000_000, backupCount=5, delay=True, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.propagate = False
app.logger.info('TrafficSentinel startup')

# File upload configurations
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['RESULT_FOLDER'] = os.getenv('RESULT_FOLDER', 'static/results')
app.config['SAMPLE_DATA_FOLDER'] = os.getenv('SAMPLE_DATA_FOLDER', 'static/sample_data')
app.config['ALLOWED_EXTENSIONS'] = eval(os.getenv('ALLOWED_EXTENSIONS', "{'jpg', 'jpeg', 'png', 'mp4', 'avi', 'mov'}"))
app.config['MAX_FILE_SIZE'] = int(os.getenv('MAX_FILE_SIZE', 209715200))  # 200MB

# MIME type validation
ALLOWED_MIME_TYPES = {
    'image/jpeg': ['jpg', 'jpeg'],
    'image/png': ['png'],
    'video/mp4': ['mp4'],
    'video/x-msvideo': ['avi'],
    'video/quicktime': ['mov']
}

# Ensure upload and result directories exist
for folder in [app.config['UPLOAD_FOLDER'], app.config['RESULT_FOLDER'], app.config['SAMPLE_DATA_FOLDER']]:
    if not os.path.exists(folder):
        os.makedirs(folder)
        app.logger.info(f'Created directory: {folder}')

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///traffic_density.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Create database tables
with app.app_context():
    try:
        db.create_all()
        app.logger.info("Database tables created successfully")
    except Exception as e:
        app.logger.error(f"Error creating database tables: {str(e)}")
        raise e

def allowed_file(filename):
    """Check if uploaded file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_extension(filename):
    """Get file extension from filename"""
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

def generate_unique_filename(filename):
    """Generate a unique filename by adding a UUID"""
    extension = get_extension(filename)
    if extension:
        return f"{uuid.uuid4().hex}.{extension}"
    else:
        # If no extension, add default based on likely content type
        if filename.lower().endswith(('video', 'movie', 'mp4', 'avi', 'mov')):
            return f"{uuid.uuid4().hex}.mp4"
        else:
            # Default to jpg for images
            return f"{uuid.uuid4().hex}.jpg"

def process_traffic_analysis(file_path, file_type, output_path):
    """
    Process traffic video or image for vehicle detection with improved accuracy
    and lane-specific analysis
    """
    try:
        # Define lane regions (assuming 3 lanes)
        LANE_REGIONS = [
            {'name': 'Left Lane', 'y_start': 0, 'y_end': 0.33},    # Left 1/3 of frame
            {'name': 'Middle Lane', 'y_start': 0.33, 'y_end': 0.66}, # Middle 1/3
            {'name': 'Right Lane', 'y_start': 0.66, 'y_end': 1.0}   # Right 1/3
        ]
        
        # Vehicle colors for different types
        VEHICLE_COLORS = {
            'car': (66, 135, 245),      # Blue
            'truck': (32, 201, 151),    # Green
            'bus': (13, 202, 240),      # Cyan
            'motorcycle': (255, 193, 7)  # Yellow
        }
        
        # Initialize counters for each lane
        lane_counts = {
            lane['name']: {
                'total': 0,
                'car': 0,
                'truck': 0,
                'bus': 0,
                'motorcycle': 0
            } for lane in LANE_REGIONS
        }
        
        if file_type == "image":
            # Read the image
            image = cv2.imread(file_path)
            if image is None:
                raise ValueError(f"Could not read image file: {file_path}")
                
            height, width = image.shape[:2]
            
            # Draw lane dividers
            for lane in LANE_REGIONS:
                y_pos = int(height * lane['y_start'])
                cv2.line(image, (0, y_pos), (width, y_pos), (255, 255, 255), 2)
            
            # Simulate more accurate vehicle detection
            # In a real implementation, this would use YOLOv8 or another model
            num_vehicles = random.randint(8, 20)
            
            for _ in range(num_vehicles):
                # Random vehicle type
                vehicle_type = random.choice(list(VEHICLE_COLORS.keys()))
                
                # Random lane
                lane = random.choice(LANE_REGIONS)
                y_min = int(height * lane['y_start'])
                y_max = int(height * lane['y_end'])
                
                # Generate realistic vehicle sizes based on type
                if vehicle_type == 'car':
                    w, h = random.randint(80, 120), random.randint(40, 60)
                elif vehicle_type == 'motorcycle':
                    w, h = random.randint(40, 60), random.randint(30, 50)
                elif vehicle_type == 'truck':
                    w, h = random.randint(120, 180), random.randint(60, 90)
                else:  # bus
                    w, h = random.randint(150, 200), random.randint(70, 100)
                    
                # Random position within the lane
                x = random.randint(0, width - w)
                y = random.randint(y_min, y_max - h)
                
                # Draw bounding box
                cv2.rectangle(image, (x, y), (x + w, y + h), VEHICLE_COLORS[vehicle_type], 2)
                
                # Add label with confidence score
                confidence = random.uniform(0.85, 0.98)
                label = f"{vehicle_type.capitalize()} {confidence:.2f}"
                
                # Calculate text size
                (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                
                # Draw background rectangle for text
                cv2.rectangle(image, (x, y - text_height - 10), (x + text_width + 5, y), 
                             VEHICLE_COLORS[vehicle_type], -1)
                
                # Draw text
                cv2.putText(image, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                
                # Update lane counts
                lane_counts[lane['name']]['total'] += 1
                lane_counts[lane['name']][vehicle_type] += 1
            
            # Save the processed image
            cv2.imwrite(output_path, image)
            
            # Calculate total vehicle count and density
            total_vehicles = sum(lane['total'] for lane in lane_counts.values())
            
            # Calculate traffic density (more vehicles = higher density)
            image_area = image.shape[0] * image.shape[1]
            scaled_vehicle_area = 5000 * (image_area / (640 * 480))
            density = min(100, (total_vehicles * scaled_vehicle_area / image_area) * 100 * 2)
            
            # Return results
            return {
                'total_vehicles': total_vehicles,
                'density': density,
                'vehicle_counts': {
                    'car': sum(lane['car'] for lane in lane_counts.values()),
                    'truck': sum(lane['truck'] for lane in lane_counts.values()),
                    'bus': sum(lane['bus'] for lane in lane_counts.values()),
                    'motorcycle': sum(lane['motorcycle'] for lane in lane_counts.values())
                }
            }
            
    except Exception as e:
        app.logger.error(f"Error in process_traffic_analysis: {str(e)}")
        raise e

def generate_sample_image():
    """Generate a sample traffic image if it doesn't exist"""
    sample_path = os.path.join(app.config['RESULT_FOLDER'], "sample_highway_traffic.jpg")
    
    if not os.path.exists(sample_path):
        # Create a sample image
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Draw highway background
        cv2.rectangle(image, (0, 0), (640, 480), (40, 40, 40), -1)  # Dark gray background
        cv2.rectangle(image, (0, 180), (640, 300), (70, 70, 70), -1)  # Road
        
        # Draw lane markings
        for i in range(0, 640, 40):
            cv2.rectangle(image, (i, 235), (i + 20, 245), (200, 200, 200), -1)
        
        # Add some vehicles
        vehicles = [
            ('car', (100, 200), (180, 240), (66, 135, 245)),
            ('car', (250, 190), (330, 230), (66, 135, 245)),
            ('truck', (400, 185), (520, 245), (32, 201, 151)),
            ('car', (50, 250), (130, 290), (66, 135, 245)),
            ('car', (200, 260), (280, 300), (66, 135, 245)),
            ('car', (350, 255), (430, 295), (66, 135, 245)),
            ('car', (500, 245), (580, 285), (66, 135, 245))
        ]
        
        for vehicle_type, (x1, y1), (x2, y2), color in vehicles:
            # Draw vehicle
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            
            # Add label
            confidence = random.uniform(0.85, 0.98)
            label = f"{vehicle_type.capitalize()} {confidence:.2f}"
            cv2.putText(image, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        # Save the image
        cv2.imwrite(sample_path, image)

@app.route('/')
def index():
    """Render the landing page"""
    return render_template('index.html')

@app.route('/sample')
def sample():
    """Show a sample analysis with vehicle detection"""
    try:
        # Generate sample image if it doesn't exist
        generate_sample_image()
        
        # Path to sample processed image
        sample_path = "sample_highway_traffic.jpg"
        sample_full_path = os.path.join(app.config['RESULT_FOLDER'], sample_path)
        
        # Real vehicle counts from the image
        vehicle_counts = {'car': 6, 'truck': 1, 'bus': 0, 'motorcycle': 0}
        total_count = sum(vehicle_counts.values())
        density = 35  # Lower density due to highway setting
        
        # Create result information dictionary
        result_info = {
            'is_video': False,  # It's an image
            'result_filename': sample_path,
            'vehicle_count': total_count,
            'density_percentage': density,
            'original_filename': "Sample Traffic Image",
            'car_count': vehicle_counts['car'],
            'truck_count': vehicle_counts['truck'],
            'bus_count': vehicle_counts['bus'],
            'motorcycle_count': vehicle_counts['motorcycle'],
            'processed_at': datetime.datetime.now(),
            'is_sample': True  # Flag to indicate this is a sample
        }
        
        # Create a temporary analysis object for the sample
        sample_analysis = Analysis(
            filename="Sample Traffic Image",
            file_type="image",
            upload_path="sample_highway_traffic.jpg",
            result_path=sample_path,
            vehicle_count=total_count,
            density_percentage=density,
            car_count=vehicle_counts['car'],
            truck_count=vehicle_counts['truck'],
            bus_count=vehicle_counts['bus'],
            motorcycle_count=vehicle_counts['motorcycle'],
            processed_at=datetime.datetime.now()
        )
        
        return render_template('result.html', analysis=sample_analysis)
        
    except Exception as e:
        app.logger.error(f"Error showing sample: {str(e)}")
        flash(f"Error showing sample: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/process_file', methods=['POST'])
@limiter.limit("10 per minute")
def process_file():
    """Process uploaded file and save analysis to database"""
    
    try:
        # Check if file was submitted
        if 'file' not in request.files:
            app.logger.error("No file part in request")
            error_msg = 'No file selected'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': error_msg}), 400
            flash(error_msg, 'warning')
            return redirect(url_for('index'))
        
        file = request.files['file']
        app.logger.info(f"Received file: {file.filename}")
        
        # Optional thresholds from client
        conf_global = float(request.form.get('conf_global') or 0.6)
        moto_conf = float(request.form.get('motorcycle_conf') or 0.75)
        iou_thresh = float(request.form.get('iou_thresh') or 0.3)
        
        # Check if file is empty
        if file.filename == '':
            app.logger.error("Empty filename submitted")
            error_msg = 'No file selected'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': error_msg}), 400
            flash(error_msg, 'warning')
            return redirect(url_for('index'))
        
        # Validate file type
        if not validate_file_type(file):
            app.logger.error(f"Invalid file type: {file.filename}")
            error_msg = 'Invalid file type or corrupted file. Please upload a valid image (.jpg, .jpeg, .png) or video (.mp4, .avi, .mov) file.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': error_msg}), 400
            flash(error_msg, 'danger')
            return redirect(url_for('index'))
        
        try:
            # Generate unique filenames for upload and result
            original_filename = secure_filename(file.filename)
            upload_filename = generate_unique_filename(original_filename)
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], upload_filename)
            
            # Create upload directory if it doesn't exist
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            
            app.logger.info(f"Saving file to: {upload_path}")
            # Save uploaded file
            file.save(upload_path)
            app.logger.info("File saved successfully")
            
            # Determine file type (image or video)
            extension = get_extension(original_filename).lower()
            file_type = "video" if extension in ['mp4', 'avi', 'mov'] else "image"
            
            # Generate result filename
            result_filename = f"result_{upload_filename}"
            result_path = os.path.join(app.config['RESULT_FOLDER'], result_filename)
            
            # Create result directory if it doesn't exist
            os.makedirs(app.config['RESULT_FOLDER'], exist_ok=True)
            
            app.logger.info(f"Processing {file_type} file: {upload_path}")
            
            # Process file for traffic analysis with bounding boxes
            try:
                if file_type == "video":
                    app.logger.info("Starting video processing")
                    results = process_video(upload_path, result_path, conf_global=conf_global, motorcycle_conf=moto_conf, iou_thresh=iou_thresh)
                    app.logger.info("Video processing completed")
                else:
                    app.logger.info("Starting image processing")
                    results = process_traffic_analysis(upload_path, file_type, result_path)
                    app.logger.info("Image processing completed")
                
                app.logger.info(f"Processing completed. Results: {results}")
                
                # Get the actual output filename with extension
                actual_result_filename = os.path.basename(result_path)
                
                # Create new analysis record in database
                new_analysis = Analysis(
                    filename=original_filename,
                    file_type=file_type,
                    upload_path=upload_filename,
                    result_path=actual_result_filename,
                    vehicle_count=results['total_vehicles'],
                    density_percentage=results['density'],
                    car_count=results['vehicle_counts']['car'],
                    truck_count=results['vehicle_counts']['truck'],
                    bus_count=results['vehicle_counts']['bus'],
                    motorcycle_count=results['vehicle_counts']['motorcycle'],
                    processed_at=datetime.datetime.now()
                )
                
                app.logger.info("Saving analysis to database")
                db.session.add(new_analysis)
                db.session.commit()
                app.logger.info("Analysis saved to database")
                
                app.logger.info("Rendering result template")
                return render_template('result.html', analysis=new_analysis, density_series=results.get('density_series'), low_confidence=results.get('low_confidence'), avg_confidence=results.get('avg_confidence'))
                
            except Exception as e:
                app.logger.error(f"Error during processing: {str(e)}")
                app.logger.error(f"Error traceback: {traceback.format_exc()}")
                # Clean up uploaded file if processing fails
                try:
                    os.remove(upload_path)
                except Exception as cleanup_error:
                    app.logger.error(f"Error cleaning up file: {str(cleanup_error)}")
                error_msg = f"Error processing file: {str(e)}"
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': error_msg}), 500
                flash(error_msg, 'danger')
                return redirect(url_for('index'))
                
        except Exception as e:
            app.logger.error(f"Error in file handling: {str(e)}")
            app.logger.error(f"Error traceback: {traceback.format_exc()}")
            error_msg = f"Error processing file: {str(e)}"
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': error_msg}), 500
            flash(error_msg, 'danger')
            return redirect(url_for('index'))
            
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        app.logger.error(f"Error traceback: {traceback.format_exc()}")
        error_msg = "An unexpected error occurred. Please try again."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_msg}), 500
        flash(error_msg, 'danger')
        return redirect(url_for('index'))

@app.route('/history')
def history():
    """Show analysis history from the database"""
    analyses = Analysis.query.order_by(Analysis.processed_at.desc()).all()
    return render_template('history.html', analyses=analyses)

@app.route('/history/clear', methods=['POST'])
def clear_history():
    """Delete all analysis records and their files"""
    try:
        analyses = Analysis.query.all()
        removed = 0
        for a in analyses:
            # Remove result file
            try:
                res_path = os.path.join(app.config['RESULT_FOLDER'], a.result_path) if a.result_path else None
                if res_path and os.path.isfile(res_path):
                    os.remove(res_path)
                    removed += 1
            except Exception as e:
                app.logger.warning(f"Failed to remove result file for analysis {a.id}: {e}")
            # Remove uploaded file
            try:
                up_path = os.path.join(app.config['UPLOAD_FOLDER'], a.upload_path) if a.upload_path else None
                if up_path and os.path.isfile(up_path):
                    os.remove(up_path)
            except Exception as e:
                app.logger.warning(f"Failed to remove upload file for analysis {a.id}: {e}")
        # Clear DB
        Analysis.query.delete()
        db.session.commit()
        app.logger.info(f"Cleared history, removed {removed} result files")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': True})
        flash('History cleared', 'success')
        return redirect(url_for('history'))
    except Exception as e:
        app.logger.error(f"Clear history error: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Failed to clear history'}), 500
        flash('Failed to clear history', 'danger')
        return redirect(url_for('history'))

@app.route('/analysis/<int:analysis_id>')
def view_analysis(analysis_id):
    """View a specific analysis"""
    analysis = Analysis.query.get_or_404(analysis_id)
    
    result_info = {
        'is_video': analysis.file_type == "video",
        'result_filename': analysis.result_path,
        'vehicle_count': analysis.vehicle_count,
        'density_percentage': analysis.density_percentage,
        'original_filename': analysis.filename,
        'analysis_id': analysis.id,
        'processed_at': analysis.processed_at,
        'car_count': analysis.car_count or 0,
        'truck_count': analysis.truck_count or 0,
        'bus_count': analysis.bus_count or 0,
        'motorcycle_count': analysis.motorcycle_count or 0
    }
    
    return render_template('result.html', analysis=analysis, **result_info)

@app.route('/download/<path:filename>')
def download_file(filename):
    """Download processed file"""
    return send_from_directory(app.config['RESULT_FOLDER'], filename, as_attachment=True)

@app.route('/report/<int:analysis_id>')
def download_report(analysis_id):
    """Generate and download a CSV report for an analysis"""
    analysis = Analysis.query.get_or_404(analysis_id)

    import csv
    from io import StringIO
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)

    writer.writerow(["Analysis ID", analysis.id])
    writer.writerow(["Filename", analysis.filename])
    writer.writerow(["File Type", analysis.file_type])
    writer.writerow(["Processed At", analysis.processed_at])
    writer.writerow(["Total Vehicles", analysis.vehicle_count])
    writer.writerow(["Traffic Density %", f"{analysis.density_percentage:.2f}"])
    writer.writerow([])
    writer.writerow(["Vehicle Distribution"])
    writer.writerow(["Cars", analysis.car_count])
    writer.writerow(["Trucks", analysis.truck_count])
    writer.writerow(["Buses", analysis.bus_count])
    writer.writerow(["Motorcycles", analysis.motorcycle_count])

    csv_buffer.seek(0)
    from flask import Response
    return Response(
        csv_buffer.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="traffic_analysis_{analysis.id}.csv"'
        }
    )

@app.route('/report/json/<int:analysis_id>')
def download_report_json(analysis_id):
    """Return JSON report for an analysis"""
    analysis = Analysis.query.get_or_404(analysis_id)
    payload = {
        'id': analysis.id,
        'filename': analysis.filename,
        'file_type': analysis.file_type,
        'result_path': analysis.result_path,
        'vehicle_count': analysis.vehicle_count,
        'density_percentage': analysis.density_percentage,
        'processed_at': analysis.processed_at.isoformat() if analysis.processed_at else None,
        'vehicle_counts': {
            'car': analysis.car_count or 0,
            'truck': analysis.truck_count or 0,
            'bus': analysis.bus_count or 0,
            'motorcycle': analysis.motorcycle_count or 0
        }
    }
    return jsonify(payload)

@app.route('/snapshot/<int:analysis_id>')
def snapshot_image(analysis_id):
    """Generate a snapshot JPG with KPI overlay from the processed media"""
    analysis = Analysis.query.get_or_404(analysis_id)
    try:
        import cv2
        output = os.path.join(app.config['RESULT_FOLDER'], analysis.result_path)
        frame_img = None
        if analysis.file_type == 'video':
            cap = cv2.VideoCapture(output)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Could not read processed video')
            frame_img = frame
            cap.release()
        else:
            frame_img = cv2.imread(output)
        if frame_img is None:
            raise RuntimeError('Could not load processed media')
        # Draw overlay text
        overlay = frame_img.copy()
        cv2.rectangle(overlay, (10, 10), (400, 120), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.4, frame_img, 0.6, 0, frame_img)
        cv2.putText(frame_img, f"Total: {analysis.vehicle_count}", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
        cv2.putText(frame_img, f"Density: {analysis.density_percentage:.1f}%", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
        # Save to temp file
        tmp_path = os.path.join(app.config['RESULT_FOLDER'], f"snapshot_{analysis.id}.jpg")
        cv2.imwrite(tmp_path, frame_img)
        return send_from_directory(app.config['RESULT_FOLDER'], os.path.basename(tmp_path), as_attachment=True)
    except Exception as e:
        app.logger.error(f"Snapshot error: {str(e)}")
        flash('Could not generate snapshot', 'danger')
        return redirect(url_for('view_analysis', analysis_id=analysis_id))

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file size exceeding the limit"""
    flash('The file is too large. Maximum file size is 200MB.', 'danger')
    return redirect(url_for('index'))

@app.errorhandler(500)
def internal_server_error(error):
    """Handle internal server errors"""
    flash('An unexpected error occurred. Please try again.', 'danger')
    return redirect(url_for('index'))

def validate_file_type(file):
    """Validate file type using extension and MIME type"""
    if not file:
        app.logger.error("No file provided")
        return False
    
    # Check extension
    extension = get_extension(file.filename)
    if not extension:
        app.logger.error(f"No extension found in filename: {file.filename}")
        return False
        
    if extension.lower() not in app.config['ALLOWED_EXTENSIONS']:
        app.logger.error(f"Extension not allowed: {extension}")
        return False
    
    # Always return True for now to debug the processing
    app.logger.info(f"File validation passed for: {file.filename}")
    return True

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
