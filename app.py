from flask import Flask, render_template, send_from_directory, request, redirect, url_for, flash, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import shutil
import logging
from logging.handlers import RotatingFileHandler

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configure secret key and debug mode from environment variables
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')  # Fallback to a default value
app.debug = os.getenv('DEBUG', 'False').lower() == 'true'

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Path to the images folder
IMAGE_FOLDER = os.path.join('static', 'images')
DEFAULT_IMAGES_FOLDER = os.path.join('static', 'defaultimages')
app.config['UPLOAD_FOLDER'] = IMAGE_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB limit

# Ensure images folder exists
os.makedirs(IMAGE_FOLDER, exist_ok=True)
os.makedirs(DEFAULT_IMAGES_FOLDER, exist_ok=True)

# Configure logging
handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=3)
handler.setLevel(logging.INFO)
app.logger.addHandler(handler)



from urllib.parse import urlparse
import os
import subprocess
from flask import Response, request, jsonify
from io import BytesIO
import tempfile
import shutil

# Debug directory to save the LaTeX file
DEBUG_DIR = os.path.join(os.getcwd(), 'debug')
os.makedirs(DEBUG_DIR, exist_ok=True)


def extract_filename_from_url(url):
    """
    Extracts the filename from a URL.
    Example: 'http://localhost:5000/static/images/Blank.JPG' -> 'Blank.JPG'
    """
    parsed_url = urlparse(url)
    return os.path.basename(parsed_url.path)


def generate_latex(label_data):
    latex_content = """
\\documentclass{article}
\\usepackage[utf8]{inputenc}
\\usepackage{graphicx}
\\usepackage[a4paper,landscape,margin=10mm]{geometry}
\\usepackage{array}
\\newcolumntype{P}[1]{@{}>{\\raggedright\\arraybackslash}p{#1}@{}}
\\renewcommand{\\arraystretch}{1.0}

\\begin{document}
\\begin{figure}[ht!]
\\centering
"""
    rows = [[None for i in range(13)] for j in range(3)]
    for label in label_data: # row position width image
        image_filename = extract_filename_from_url(label['image'])
        rows[int(label['row'])-1][int(label['position'])-1] = (image_filename, int(label['width']), label['caption'])


    for irow in rows:
        latex_content += """\\begin{tabular}{|"""
        for ilabel in irow:
            if ilabel is None:
                break
            latex_content += "P{" + str(ilabel[1]) + "mm}|"
        latex_content += """}
\\hline"""
        for ilabel in irow:
            if ilabel is None:
                break
            latex_content += """\\parbox[c][30mm][c]{""" + str(ilabel[1]) +  """mm}{\\centering
\\vspace{2mm} 
\\includegraphics[height=10mm,width=10mm,keepaspectratio]{""" + ilabel[0] + """} \\\\
\\vspace{2mm} 
\\small """ + ilabel[2] + """}  &"""
        latex_content = latex_content[:-1]
        latex_content += """\\\\
\\hline
\\end{tabular}

\\vspace{10mm}

"""
    latex_content += """
\\end{figure}
\\end{document}
"""
    return latex_content

@app.route('/compile-pdf', methods=['POST'])
def compile_pdf():
    try:
        label_data = request.json

        # Debugging: Print the received label data
        print("Received label data:", label_data)

        # Ensure label_data is a list
        if not isinstance(label_data, list):
            return jsonify({'success': False, 'error': 'Invalid label data format. Expected a list.'})

        # Ensure each label is a dictionary with the required keys
        for label in label_data:
            if not isinstance(label, dict):
                return jsonify({'success': False, 'error': 'Invalid label format. Expected a dictionary.'})
            if 'image' not in label or 'caption' not in label or 'width' not in label:
                return jsonify({'success': False, 'error': 'Missing required keys in label data.'})

        # Generate LaTeX content
        latex_content = generate_latex(label_data)

        # Save the LaTeX file to the debug directory
        tex_file_path = os.path.join(DEBUG_DIR, 'labels.tex')
        with open(tex_file_path, 'w') as tex_file:
            tex_file.write(latex_content)

        # Create a temporary directory to store LaTeX files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write the LaTeX content to a .tex file
            tex_file_path = os.path.join(temp_dir, 'labels.tex')
            with open(tex_file_path, 'w') as tex_file:
                tex_file.write(latex_content)

            # Copy images to the temporary directory
            for label in label_data:
                # Extract the filename from the image URL
                image_url = label['image']
                image_filename = extract_filename_from_url(image_url)
                src_image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
                dest_image_path = os.path.join(temp_dir, image_filename)
                os.makedirs(os.path.dirname(dest_image_path), exist_ok=True)
                shutil.copy(src_image_path, dest_image_path)

            # Debugging: Print the contents of the temporary directory
            print("Contents of temporary directory:", os.listdir(temp_dir))

            # Debugging: Print the LaTeX content
            print("Generated LaTeX content:")
            print(latex_content)

            # Compile the LaTeX file using pdflatex
            result = subprocess.run(
                ['pdflatex', '-interaction=nonstopmode', 'labels.tex'],
                cwd=temp_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Log the output of pdflatex
            print("pdflatex stdout:", result.stdout.decode('utf-8'))
            print("pdflatex stderr:", result.stderr.decode('utf-8'))

            # Check if pdflatex succeeded
            if result.returncode != 0:
                error_message = result.stderr.decode('utf-8')
                print(f"LaTeX compilation error: {error_message}")
                print(f"pdflatex stdout: {result.stdout.decode('utf-8')}")
                return jsonify({'success': False, 'error': f'Failed to compile LaTeX: {error_message}'})

            # Read the compiled PDF
            pdf_path = os.path.join(temp_dir, 'labels.pdf')
            print(f"PDF path: {pdf_path}")

            # Verify that the PDF file exists
            if not os.path.exists(pdf_path):
                print(f"PDF file not found: {pdf_path}")
                return jsonify({'success': False, 'error': 'PDF file not found.'})

            # Debugging: Print the size of the PDF file
            pdf_size = os.path.getsize(pdf_path)
            print(f"PDF file size: {pdf_size} bytes")

            # Read the PDF file
            try:
                with open(pdf_path, 'rb') as pdf_file:
                    pdf_content = pdf_file.read()
                print("PDF file read successfully.")
            except Exception as e:
                print(f"Error reading PDF file: {e}")
                return jsonify({'success': False, 'error': f'Error reading PDF file: {e}'})

            # Stream the PDF directly to the user's browser
            try:
                pdf_stream = BytesIO(pdf_content)
                response = Response(
                    pdf_stream,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': 'attachment; filename=labels.pdf'
                    }
                )
                print("Response created successfully.")
                return response
            except Exception as e:
                print(f"Error creating response: {e}")
                return jsonify({'success': False, 'error': f'Error creating response: {e}'})

    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({'success': False, 'error': str(e)})


# Function to copy default images to the images folder
def copy_default_images():
    if not os.path.exists(DEFAULT_IMAGES_FOLDER):
        app.logger.warning(f"Default images folder does not exist: {DEFAULT_IMAGES_FOLDER}")
        return

    for filename in os.listdir(DEFAULT_IMAGES_FOLDER):
        if filename.endswith(('.png', '.jpg', '.jpeg')):
            src_path = os.path.join(DEFAULT_IMAGES_FOLDER, filename)
            dest_path = os.path.join(IMAGE_FOLDER, filename)
            if not os.path.exists(dest_path):  # Avoid overwriting existing files
                shutil.copy(src_path, dest_path)
                app.logger.info(f"Copied default image: {filename}")

# Function to get images from the images folder
def get_default_images():
    images_folder = os.path.join(app.static_folder, 'images')
    images = [f for f in os.listdir(images_folder) if f.endswith(('.png', '.jpg', '.jpeg'))]
    return images

# Ensure images folder is empty at startup and copy default images
def initialize_images_folder():
    if os.path.exists(IMAGE_FOLDER):
        shutil.rmtree(IMAGE_FOLDER)
    os.makedirs(IMAGE_FOLDER, exist_ok=True)
    copy_default_images()

initialize_images_folder()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_safe_text(text):
    return text.isalnum() and len(text) <= 25

@app.route('/')
def index():
    images = get_default_images()
    return render_template('index.html', images=images)

@app.route('/get-images')
def get_images():
    images = get_default_images()
    return jsonify(images)

@app.route('/images/<filename>')
def get_image(filename):
    return send_from_directory(IMAGE_FOLDER, filename)

@app.route('/upload', methods=['POST'])
@limiter.limit("10 per minute")  # Rate limit for uploads
def upload_image():
    try:
        if 'file' not in request.files:
            flash('No file part')
            return redirect(url_for('index'))

        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(url_for('index'))

        if file and allowed_file(file.filename):
            if file.content_length and file.content_length > MAX_FILE_SIZE:
                flash('File size exceeds limit (1MB)')
                return redirect(url_for('index'))

            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            app.logger.info(f"File uploaded successfully: {filename}")
            flash('File uploaded successfully')
            return redirect(url_for('index'))
        else:
            flash('Invalid file type. Only PNG and JPG allowed.')
            return redirect(url_for('index'))
    except Exception as e:
        app.logger.error(f"Error uploading file: {e}")
        flash('An error occurred while uploading the file.')
        return redirect(url_for('index'))

# Error handlers
@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(error):
    app.logger.error(f"500 Error: {error}")
    return render_template('500.html'), 500

# Secure session cookies
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

if __name__ == '__main__':
    # Run the app with Gunicorn in production
    if os.getenv('FLASK_ENV') == 'production':
        from gunicorn.app.base import BaseApplication

        class FlaskApplication(BaseApplication):
            def __init__(self, app, options=None):
                self.application = app
                self.options = options or {}
                super().__init__()

            def load_config(self):
                for key, value in self.options.items():
                    self.cfg.set(key, value)

            def load(self):
                return self.application

        options = {
            'bind': '0.0.0.0:5000',
            'workers': 4,
        }
        FlaskApplication(app, options).run()
    else:
        app.run(debug=True)
