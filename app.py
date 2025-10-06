from flask import Flask, render_template, redirect, url_for, flash, request, session, abort, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from dotenv import load_dotenv
from forms import RegistrationForm, LoginForm, BlogPostForm
import uuid
import cohere

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key-for-development')

# MongoDB connection
client = MongoClient(os.getenv('MONGO_URI', 'mongodb+srv://shaikabdulrahiman:BITTU@abdul.phqgiob.mongodb.net/?retryWrites=true&w=majority&appName=abdul'))
db = client['blogging_platform']
users_collection = db['users']
blogs_collection = db['blogs']
categories_collection = db['categories']

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']
        self.email = user_data['email']
        self.role = user_data['role']
    
    def get_id(self):
        return self.id

@login_manager.user_loader
def load_user(user_id):
    user_data = users_collection.find_one({'_id': ObjectId(user_id)})
    if user_data:
        return User(user_data)
    return None

# Routes
@app.route('/')
def home():
    # Get approved blogs for homepage
    approved_blogs = list(blogs_collection.find({'status': 'approved'}).sort('created_at', -1))
    return render_template('index.html', blogs=approved_blogs)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        # Check if username or email already exists
        existing_user = users_collection.find_one({
            '$or': [
                {'username': form.username.data},
                {'email': form.email.data}
            ]
        })
        
        if existing_user:
            flash('Username or email already exists. Please choose different credentials.', 'danger')
            return render_template('register.html', form=form)
        
        # Create new user
        hashed_password = generate_password_hash(form.password.data)
        new_user = {
            'username': form.username.data,
            'email': form.email.data,
            'password': hashed_password,
            'role': 'user',  # Default role is user
            'created_at': datetime.now()
        }
        
        users_collection.insert_one(new_user)
        flash('Your account has been created! You can now log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user_data = users_collection.find_one({'email': form.email.data})
        
        if user_data and check_password_hash(user_data['password'], form.password.data):
            user = User(user_data)
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:
            flash('Login unsuccessful. Please check email and password.', 'danger')
    
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/create-blog', methods=['GET', 'POST'])
@login_required
def create_blog():
    form = BlogPostForm()
    # Get categories for the dropdown
    categories = list(categories_collection.find())
    form.category.choices = [(str(cat['_id']), cat['name']) for cat in categories]
    
    if form.validate_on_submit():
        # Create new blog post
        new_blog = {
            'title': form.title.data,
            'content': form.content.data,
            'category_id': ObjectId(form.category.data),
            'author_id': ObjectId(current_user.id),
            'author_name': current_user.username,
            'status': 'pending',  # Default status is pending
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        blogs_collection.insert_one(new_blog)
        flash('Your blog post has been submitted for review!', 'success')
        return redirect(url_for('my_blogs'))
    
    return render_template('create_blog.html', form=form)

@app.route('/my-blogs')
@login_required
def my_blogs():
    # Get all blogs by current user
    user_blogs = list(blogs_collection.find({'author_id': ObjectId(current_user.id)}).sort('created_at', -1))
    return render_template('my_blogs.html', blogs=user_blogs)

@app.route('/blog/<blog_id>')
def view_blog(blog_id):
    blog = blogs_collection.find_one({'_id': ObjectId(blog_id)})
    if not blog:
        abort(404)
    
    # Only show approved blogs to non-authors
    if blog['status'] != 'approved' and (not current_user.is_authenticated or str(blog['author_id']) != current_user.id):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
    
    category = categories_collection.find_one({'_id': blog['category_id']})
    return render_template('view_blog.html', blog=blog, category=category)

# Admin routes
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.role == 'admin':
        abort(403)
    
    # Get pending blogs for review
    pending_blogs = list(blogs_collection.find({'status': 'pending'}).sort('created_at', -1))
    
    # Count blogs by status
    pending_count = len(pending_blogs)
    approved_count = blogs_collection.count_documents({'status': 'approved'})
    rejected_count = blogs_collection.count_documents({'status': 'rejected'})
    
    return render_template('admin/dashboard.html', 
                         blogs=pending_blogs,
                         pending_count=pending_count,
                         approved_count=approved_count,
                         rejected_count=rejected_count)
@app.route('/admin/review/<blog_id>/<action>')
@login_required
def review_blog(blog_id, action):
    if not current_user.role == 'admin':
        abort(403)
    
    if action not in ['approve', 'reject']:
        abort(400)
    
    status = 'approved' if action == 'approve' else 'rejected'
    blogs_collection.update_one(
        {'_id': ObjectId(blog_id)},
        {'$set': {'status': status, 'reviewed_at': datetime.now()}}
    )
    
    flash(f'Blog has been {status}!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/categories', methods=['GET', 'POST'])
@login_required
def manage_categories():
    if not current_user.role == 'admin':
        abort(403)
    
    if request.method == 'POST':
        category_name = request.form.get('category_name')
        if category_name:
            categories_collection.insert_one({
                'name': category_name,
                'created_at': datetime.now()
            })
            flash('Category added successfully!', 'success')
    
    categories = list(categories_collection.find().sort('name', 1))
    return render_template('admin/categories.html', categories=categories)


# Chat / Assistant helpers and routes
def build_site_context(max_chars=15000, category=None, title=None, limit_blogs=10):
    """Collect approved site content filtered by category or title to use as context for the assistant.

    - If title provided, include that blog's full content (if approved or any).
    - If category provided, include recent approved blogs in that category.
    - Otherwise include recent approved blogs across the site.
    This is a simple retrieval strategy; for production use embeddings + nearest-neighbor is recommended.
    """
    parts = []

    # include categories list for context
    categories = [cat.get('name', '') for cat in categories_collection.find().sort('name', 1)]
    if categories:
        parts.append('Categories: ' + ', '.join(categories) + '\n')

    query = {'status': 'approved'}
    # If title specified, try to find that specific blog (include even if not approved)
    if title:
        blog = blogs_collection.find_one({'title': {'$regex': f'^{title}$', '$options': 'i'}}) or blogs_collection.find_one({'_id': title})
        if blog:
            try:
                cat = categories_collection.find_one({'_id': blog.get('category_id')})
                catname = cat.get('name') if cat else ''
            except Exception:
                catname = ''
            parts.append(f"Title: {blog.get('title','')}\nCategory: {catname}\nAuthor: {blog.get('author_name','')}\nContent: {blog.get('content','')}\n---\n")
            site_text = "\n".join(parts)
            return site_text[:max_chars]

    if category:
        # find category id by name
        cat_doc = categories_collection.find_one({'name': {'$regex': f'^{category}$', '$options': 'i'}})
        if cat_doc:
            query['category_id'] = cat_doc['_id']

    blogs = list(blogs_collection.find(query).sort('created_at', -1).limit(limit_blogs))
    for b in blogs:
        try:
            cat = categories_collection.find_one({'_id': b.get('category_id')})
            catname = cat.get('name') if cat else ''
        except Exception:
            catname = ''
        parts.append(f"Title: {b.get('title','')}\nCategory: {catname}\nAuthor: {b.get('author_name','')}\nContent: {b.get('content','')}\n---\n")

    site_text = "\n".join(parts)
    return site_text[:max_chars]


@app.route('/chat')
def chat():
    # Pass categories to the template for the action UI
    categories = list(categories_collection.find().sort('name', 1))
    return render_template('chat.html', categories=categories)


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json() or {}
    action = data.get('action', 'ask')
    question = data.get('question', '').strip()
    category = data.get('category')
    title = data.get('title')
    content = data.get('content')

    if action in ['ask', 'suggest_titles', 'generate_blog', 'summarize', 'expand', 'edit'] and not (question or title or content):
        # For many actions we allow question/title/content; if none provided, error
        if action == 'ask':
            return jsonify({'error': 'Question is required for ask action'}), 400

    # Build context based on filters
    context = build_site_context(category=category, title=title)

    # Base instruction to restrict answers to site content
    base_instr = (
        "You are a helpful assistant that should use ONLY the provided website content to answer user requests. "
        "If the information is not available in the site content, respond: 'I don\'t know based on the site content.' Do not invent facts."
    )

    try:
        cohere_api_key = os.getenv('COHERE_API_KEY', 'FPU8pDfsre9OYF0uk7JYi7stsPIAhUNS7zhXydJF')
        co = cohere.Client(cohere_api_key)

        if action == 'suggest_titles':
            # Suggest titles for a given category or seed question
            prompt = f"{base_instr}\nWebsite content:\n{context}\n\nUser request: Suggest 10 blog post titles" + (f" about {category}" if category else '') + ". Keep titles short and catchy."
            chat_resp = co.chat(message=prompt, model='command-xlarge-nightly', max_tokens=200, temperature=0.6)

        elif action == 'generate_blog':
            # Generate a full blog draft from a given title
            if not title:
                return jsonify({'error': 'Title is required for generate_blog action'}), 400
            prompt = (
                f"{base_instr}\nWebsite content:\n{context}\n\nUser request: Write a full blog post draft for the title: {title}. "
                "Use the website's tone, include an intro, headings, and a conclusion. Keep it ~600-1000 words."
            )
            chat_resp = co.chat(message=prompt, model='command-xlarge-nightly', max_tokens=1200, temperature=0.3)

        elif action == 'summarize':
            # Summarize provided content or a site blog
            source_text = content
            if not source_text and title:
                # fetch by title
                b = blogs_collection.find_one({'title': {'$regex': f'^{title}$', '$options': 'i'}})
                source_text = b.get('content') if b else ''
            if not source_text:
                return jsonify({'error': 'No content found to summarize'}), 400
            prompt = f"{base_instr}\nContent to summarize:\n{source_text}\n\nPlease provide a concise summary (3-4 sentences)."
            chat_resp = co.chat(message=prompt, model='command-xlarge-nightly', max_tokens=200, temperature=0.2)

        elif action == 'expand':
            # Expand provided content
            source_text = content
            if not source_text and title:
                b = blogs_collection.find_one({'title': {'$regex': f'^{title}$', '$options': 'i'}})
                source_text = b.get('content') if b else ''
            if not source_text:
                return jsonify({'error': 'No content found to expand'}), 400
            prompt = f"{base_instr}\nContent to expand:\n{source_text}\n\nPlease expand this content, adding details, examples, and headings where relevant."
            chat_resp = co.chat(message=prompt, model='command-xlarge-nightly', max_tokens=800, temperature=0.3)

        elif action == 'edit':
            # Edit provided content with instructions in question
            if not content:
                return jsonify({'error': 'Content is required to edit'}), 400
            instr = question or 'Improve clarity and flow; correct grammar.'
            prompt = f"{base_instr}\nContent to edit:\n{content}\n\nEdit instructions: {instr}\n\nEdited version:" 
            chat_resp = co.chat(message=prompt, model='command-xlarge-nightly', max_tokens=800, temperature=0.2)

        else:
            # default 'ask' - answer a user question using site context
            if not question:
                return jsonify({'error': 'Question is required'}), 400
            prompt = f"{base_instr}\nWebsite content:\n{context}\n\nQuestion: {question}\n\nAnswer:" 
            chat_resp = co.chat(message=prompt, model='command-xlarge-nightly', max_tokens=300, temperature=0.2)

        # parse chat response
        answer = ''
        if getattr(chat_resp, 'text', None):
            answer = chat_resp.text.strip()
        else:
            try:
                answer = chat_resp.model_dump().get('text', '') or ''
                answer = answer.strip()
            except Exception:
                answer = ''

        if not answer:
            answer = "I don't know based on the site content."

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'answer': answer})

# Initialize categories if none exist
def init_categories():
    if categories_collection.count_documents({}) == 0:
        default_categories = [
            {'name': 'Technology', 'created_at': datetime.now()},
            {'name': 'Travel', 'created_at': datetime.now()},
            {'name': 'Food', 'created_at': datetime.now()},
            {'name': 'Health', 'created_at': datetime.now()},
            {'name': 'Business', 'created_at': datetime.now()}
        ]
        categories_collection.insert_many(default_categories)

# Initialize admin user if none exists
def init_admin():
    admin = users_collection.find_one({'role': 'admin'})
    if not admin:
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        hashed_password = generate_password_hash(admin_password)
        admin_user = {
            'username': 'admin',
            'email': 'admin@example.com',
            'password': hashed_password,
            'role': 'admin',
            'created_at': datetime.now()
        }
        users_collection.insert_one(admin_user)

if __name__ == '__main__':
    init_categories()
    init_admin()
    app.run(debug=True)