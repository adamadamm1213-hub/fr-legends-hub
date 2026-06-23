import os
import secrets
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fr_legends.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')

ALLOWED_EXTENSIONS = {'png'}
CAR_MODELS = [
    'Ferrari F40',
    'Ferrari Testarossa',
    'Ferrari 288 GTO',
    'Ferrari F50',
    'Ferrari Enzo',
    'Ferrari LaFerrari',
    'Lamborghini Countach',
    'Lamborghini Diablo',
    'Lamborghini Murcielago',
    'Lamborghini Reventon',
    'Lamborghini Aventador',
    'Porsche 911 Turbo',
    'Porsche Carrera GT',
    'Bugatti Veyron',
    'McLaren F1',
    'Custom'
]

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = None

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    liveries = db.relationship('Livery', backref='author', lazy=True, cascade='all, delete-orphan')
    ratings = db.relationship('Rating', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Livery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    car_model = db.Column(db.String(100), nullable=False)
    body_code = db.Column(db.Text, nullable=True)
    window_code = db.Column(db.Text, nullable=True)
    image_file = db.Column(db.String(255), nullable=True)
    views = db.Column(db.Integer, default=0)
    rating_sum = db.Column(db.Integer, default=0)
    rating_count = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ratings = db.relationship('Rating', backref='livery', lazy=True, cascade='all, delete-orphan')

    def get_average_rating(self):
        if self.rating_count == 0:
            return 0
        return self.rating_sum / self.rating_count

class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    livery_id = db.Column(db.Integer, db.ForeignKey('livery.id'), nullable=False)
    stars = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    with app.app_context():
        db.create_all()

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    liveries_query = Livery.query.order_by(
        Livery.rating_sum.desc(),
        Livery.views.desc(),
        Livery.timestamp.desc()
    )
    
    paginated = liveries_query.paginate(page=page, per_page=per_page, error_out=False)
    liveries = paginated.items
    total_pages = paginated.pages
    
    return render_template('feed.html', liveries=liveries, page=page, total_pages=total_pages)

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    if query:
        liveries_query = Livery.query.filter(
            db.or_(
                Livery.title.ilike(f'%{query}%'),
                Livery.description.ilike(f'%{query}%'),
                Livery.car_model.ilike(f'%{query}%')
            )
        ).order_by(Livery.rating_sum.desc(), Livery.views.desc())
    else:
        liveries_query = Livery.query.order_by(
            Livery.rating_sum.desc(),
            Livery.views.desc()
        )
    
    paginated = liveries_query.paginate(page=page, per_page=per_page, error_out=False)
    liveries = paginated.items
    total_pages = paginated.pages
    
    return render_template('feed.html', liveries=liveries, page=page, total_pages=total_pages, search_query=query)

@app.route('/livery/<int:livery_id>')
def livery_detail(livery_id):
    livery = Livery.query.get_or_404(livery_id)
    livery.views += 1
    db.session.commit()
    
    user_rating = None
    if current_user.is_authenticated:
        user_rating = Rating.query.filter_by(user_id=current_user.id, livery_id=livery_id).first()
        if user_rating:
            user_rating = user_rating.stars
    
    return render_template('livery_detail.html', livery=livery, user_rating=user_rating)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        car_model = request.form.get('car_model', '').strip()
        body_code = request.form.get('body_code', '').strip()
        window_code = request.form.get('window_code', '').strip()
        
        if not title or not car_model:
            flash('Title and Car Model are required', 'error')
            return redirect(url_for('upload'))
        
        image_file = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_file = filename
        
        livery = Livery(
            title=title,
            description=description,
            car_model=car_model,
            body_code=body_code,
            window_code=window_code,
            image_file=image_file,
            user_id=current_user.id
        )
        
        db.session.add(livery)
        db.session.commit()
        
        flash(f'Livery "{title}" uploaded successfully!', 'success')
        return redirect(url_for('livery_detail', livery_id=livery.id))
    
    return render_template('upload.html', car_models=CAR_MODELS)

@app.route('/rate/<int:livery_id>/<int:stars>', methods=['POST'])
@login_required
def rate_livery(livery_id, stars):
    if stars < 1 or stars > 5:
        return jsonify({'error': 'Invalid rating'}), 400
    
    livery = Livery.query.get_or_404(livery_id)
    
    existing_rating = Rating.query.filter_by(user_id=current_user.id, livery_id=livery_id).first()
    
    if existing_rating:
        livery.rating_sum -= existing_rating.stars
        existing_rating.stars = stars
        livery.rating_sum += stars
    else:
        rating = Rating(user_id=current_user.id, livery_id=livery_id, stars=stars)
        db.session.add(rating)
        livery.rating_count += 1
        livery.rating_sum += stars
    
    db.session.commit()
    
    avg_rating = livery.get_average_rating()
    return jsonify({
        'success': True,
        'average_rating': round(avg_rating, 1),
        'rating_count': livery.rating_count
    })

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Username and password are required', 'error')
            return redirect(url_for('index'))
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user, remember=request.form.get('remember') == 'on')
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
            return redirect(url_for('index'))
    
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if not username or not password or not confirm_password:
            flash('All fields are required', 'error')
            return redirect(url_for('index'))
        
        if len(username) < 3:
            flash('Username must be at least 3 characters', 'error')
            return redirect(url_for('index'))
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('index'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('index'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('index'))
        
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        flash(f'Account created successfully, {username}!', 'success')
        return redirect(url_for('index'))
    
    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('index'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.errorhandler(404)
def not_found(error):
    return render_template('feed.html', liveries=[], page=1, total_pages=1, error='Page not found'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('feed.html', liveries=[], page=1, total_pages=1, error='Server error'), 500
@app.route('/static/<path:filename>')
def serve_static(filename):
    from flask import send_from_directory
    import os
    return send_from_directory(os.path.join(app.root_path, 'static'), filename)
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
