import os
import sys
import traceback
import mariadb
import shutil
import logging
from pathlib import Path
from datetime import datetime

from flask import (
    Flask, render_template, request, jsonify,
    url_for, send_from_directory, abort, current_app
)
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.exceptions import NotFound, BadRequest, InternalServerError

# --- Configuration ---
# (Keep your existing BASE_DIR, UPLOAD_FOLDER, ALLOWED_EXTENSIONS, DB_CONFIG)
BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True, parents=True)
ALLOWED_EXTENSIONS = {".xml", ".tsv"}
DB_CONFIG = {

}


# --- App & DB Initialization ---
# (Keep your existing Flask app setup, CORS, logging, global conn, connect_db)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
CORS(app)
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)
conn = None
# (Include connect_db function here)
def connect_db():
    global conn
    try:
        if conn and not getattr(conn, '_closed', True):
             try: conn.close()
             except mariadb.Error: pass # Ignore error closing already closed/bad conn
        app.logger.info("Attempting to connect to MariaDB...")
        conn = mariadb.connect(**DB_CONFIG)
        conn.autocommit = False
        app.logger.info("Successfully connected to MariaDB.")
    except mariadb.Error as e:
        app.logger.error(f"FATAL: Could not connect/reconnect to MariaDB: {e}", exc_info=True)
        conn = None
connect_db() # Initial connect attempt


# --- Database Helper Functions ---
# (Keep your existing get_db_cursor, dict_rows, insert_gapfill_row functions)
def get_db_cursor():
    global conn
    MAX_RETRIES = 2
    for attempt in range(MAX_RETRIES):
        try:
            is_closed = getattr(conn, '_closed', True)
            if conn is None or is_closed:
                app.logger.warning(f"DB connection is None or closed (Attempt {attempt + 1}/{MAX_RETRIES}). Reconnecting.")
                connect_db()
                if conn is None: raise mariadb.OperationalError("Database reconnection failed.")
            conn.ping()
            app.logger.debug("DB connection ping successful.")
            return conn.cursor()
        except (mariadb.Error, mariadb.InterfaceError, mariadb.OperationalError) as e:
            app.logger.error(f"DB Error in get_db_cursor (Attempt {attempt + 1}/{MAX_RETRIES}): {e}", exc_info=False)
            if attempt < MAX_RETRIES - 1:
                 app.logger.warning("Retrying DB connection...")
                 conn = None; connect_db()
            else:
                app.logger.error("Max DB connection retries reached. Raising error.")
                raise
        except AttributeError as ae:
             app.logger.error(f"AttributeError getting DB cursor: {ae}", exc_info=True)
             raise mariadb.InterfaceError("Internal error checking DB connection state.") from ae
        except Exception as e:
             app.logger.error(f"Unexpected error in get_db_cursor: {e}", exc_info=True)
             raise
    raise mariadb.OperationalError("Failed to get DB cursor after multiple retries.")

def dict_rows(cur):
    if not cur.description: return []
    try:
        cols = [d[0] for d in cur.description]
        results = []
        for row in cur.fetchall():
            if len(row) == len(cols): results.append(dict(zip(cols, row)))
            else: app.logger.warning(f"Row length mismatch. Cols: {len(cols)}, Row: {len(row)}. Skipping.")
        return results
    except Exception as e:
        app.logger.error(f"Error processing results in dict_rows: {e}", exc_info=True)
        return []

def insert_gapfill_row(cur, meta):
    sql = """
    INSERT INTO gapfill_models
      (Species_Name, growth_media, gapfill_algorithm, annotation_tool, file_name, file_link,
       growth_data, growth_file, biomass_file_5mM, biomass_file_20mM)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    values_tuple = (
        meta.get("Species_Name", "P.simiae"),
        meta.get("growth_media"),
        meta.get("gapfill_algorithm"),
        meta.get("annotation_tool"),
        meta.get("file_name"),
        meta.get("file_link"),
        meta.get("growth_data"),
        meta.get("growth_file"),
        meta.get("biomass_file_5mM"),
        meta.get("biomass_file_20mM"),
    )
    app.logger.debug(f"Executing SQL: {sql} with values: {values_tuple}")
    try:
        cur.execute(sql, values_tuple)
        app.logger.info(f"Insert successful, last row ID: {cur.lastrowid}")
        return cur.lastrowid
    except mariadb.Error as e:
         current_app.logger.error(f"Error inserting data: {e} with meta keys: {list(meta.keys())}", exc_info=True)
         if e.errno == 1048:
              try: column_name = str(e).split("'")[1]
              except IndexError: column_name = "a required field"
              raise mariadb.IntegrityError(f"Database Constraint Error: '{column_name}' cannot be empty.")
         elif e.errno == 1062: raise mariadb.IntegrityError(f"Database Constraint Error: Duplicate entry detected.")
         else: raise


# --- Teardown Function ---
# (Keep existing teardown)
@app.teardown_appcontext
def close_db_connection(exception=None):
    if exception: app.logger.error(f"App teardown with exception: {exception}", exc_info=True)
    pass

# --- Health check ---
# (Keep existing ping)
@app.route("/ping")
def ping(): return "pong", 200

# --- Web UI Routes ---

# --- SQL Demo page ---
@app.route("/demo")
def demo_queries():
    cur = None
    metabolic_reactions, gapfill_reactions, experiments = [], [], []
    try:
        cur = get_db_cursor()

        # Metabolic Reactions
        cur.execute("SELECT reaction_id, reaction_name, metabolites, flux_value FROM metabolic_reactions WHERE organism_id = 'Ecoli_K12'")
        metabolic_reactions = dict_rows(cur)

        # Gap-Filling Reactions
        cur.execute("SELECT model_id, reaction_id, reaction_name, source_database FROM gap_filling_results WHERE model_id = 'Model_123'")
        gapfill_reactions = dict_rows(cur)

        # Experimental Conditions
        cur.execute("SELECT experiment_id, media_composition, temperature, growth_outcome FROM experimental_conditions WHERE experiment_id = 'Exp_20250321'")
        experiments = dict_rows(cur)

    except Exception as e:
        app.logger.error(f"Error executing demo queries: {e}", exc_info=True)
    finally:
        if cur:
            try: cur.close()
            except: pass

    return render_template(
        "demo_queries.html",
        metabolic_reactions=metabolic_reactions,
        gapfill_reactions=gapfill_reactions,
        experiments=experiments,
        current_year=datetime.now().year
    )



#Linked Databases such as KEGG 
@app.route('/linked_databases')
def linked_databases():
    """Renders the Linked Databases page."""
    app.logger.info("Rendering Linked Databases page")
    return render_template('linked_databases.html', current_year=datetime.now().year)

#Intro page, brand spanking new
@app.route('/intro')
def intro():
    """Renders the Introduction page."""
    app.logger.info("Rendering Introduction page")
    return render_template('intro.html', current_year=datetime.now().year)

# KEEP Existing route for main page (index/search/upload)
@app.route("/")
def index():
    """ Renders the main page, showing the latest 5 models. """
    # (Keep existing code for this function)
    models = []
    error_message = None
    cur = None
    try:
        app.logger.info(f"Request received for index route '/'")
        cur = get_db_cursor()
        cur.execute("SELECT * FROM gapfill_models ORDER BY id DESC LIMIT 5")
        models = dict_rows(cur)
        app.logger.info(f"Retrieved {len(models)} models for index display.")
    except (mariadb.Error, mariadb.InterfaceError, mariadb.OperationalError) as db_e:
        app.logger.error(f"Database error retrieving models for index: {db_e}", exc_info=True)
        error_message = "Database connection or query error retrieving models. Please try again later."
    except Exception as e:
        app.logger.error(f"Unexpected error in index(): {e}", exc_info=True)
        error_message = "An unexpected server error occurred while retrieving models."
    finally:
        if cur:
            try: cur.close()
            except mariadb.Error as e: app.logger.error(f"Error closing cursor in index(): {e}", exc_info=True)

    return render_template(
        "index.html",
        search_results=models,
        media_search=None, # Indicate no search was performed
        current_year=datetime.now().year,
        error_message=error_message
    )


# KEEP Existing search route
@app.route("/search", methods=["POST"])
def search():
    """ Handles searching models by growth media and renders the results using index.html. """
    models = []
    term = request.form.get("media_search", "").strip()
    growth_filter = request.form.get("growth_filter", "all")
    error_message = None
    cur = None
    app.logger.info(f"Handling search request for term: '{term}'")
    try:
        cur = get_db_cursor()
        # Build dynamic query based on growth_filter
        query = "SELECT * FROM gapfill_models WHERE growth_media LIKE ?"
        params = [f"%{term}%"]
        if growth_filter == "growth":
            query += " AND growth_data = ?"
            params.append("Growth")
        elif growth_filter == "no_growth":
            query += " AND (growth_data != ? OR growth_data IS NULL)"
            params.append("Growth")
        query += " ORDER BY id DESC"
        cur.execute(query, tuple(params))
        models = dict_rows(cur)
        app.logger.info(f"Found {len(models)} models matching search term '{term}' and filter '{growth_filter}'.")
    except (mariadb.Error, mariadb.InterfaceError, mariadb.OperationalError) as db_e:
        app.logger.error(f"Database error during search for '{term}': {db_e}", exc_info=True)
        error_message = f"Database error during search for '{term}'. Please try again later."
    except Exception as e:
        app.logger.error(f"Unexpected error in search(): {e}", exc_info=True)
        error_message = f"Search failed for '{term}' due to a server error."
    finally:
        if cur:
             try: cur.close()
             except mariadb.Error as e: app.logger.error(f"Error closing cursor in search(): {e}", exc_info=True)

    return render_template(
        "index.html", # Still render index.html for search results
        search_results=models,
        media_search=term, # Pass the search term back
        growth_filter=growth_filter,
        current_year=datetime.now().year,
        error_message=error_message
    )

# --- ADD New Routes ---

@app.route('/about')
def about():
    """Renders the About page."""
    app.logger.info("Rendering About page")
    # Can add logic here to fetch data if needed for the about page
    return render_template('about.html', current_year=datetime.now().year)

@app.route('/help')
def help_page():
    """Renders the Help page."""
    app.logger.info("Rendering Help page")
    # Can add logic here if needed
    return render_template('help.html', current_year=datetime.now().year)

# Optional: Add a /files route similar to teammate's, but maybe query DB?
# @app.route('/files')
# def files():
#     """Lists all available models from database (example)."""
#     all_models = []
#     error_message = None
#     cur = None
#     try:
#         app.logger.info("Fetching all models for /files page")
#         cur = get_db_cursor()
#         # Fetch necessary columns, including paths/filenames
#         cur.execute("SELECT id, file_name, file_link, growth_file, biomass_file_5mM, biomass_file_20mM FROM gapfill_models ORDER BY id DESC")
#         all_models = dict_rows(cur)
#     except Exception as e:
#         app.logger.error(f"Error fetching models for /files page: {e}", exc_info=True)
#         error_message = "Could not retrieve file list."
#     finally:
#         if cur:
#              try: cur.close()
#              except mariadb.Error as e: app.logger.error(f"Error closing cursor in files(): {e}", exc_info=True)
#     # You would need a 'files.html' template similar to the table in index.html
#     # return render_template('files.html', models=all_models, error_message=error_message, current_year=datetime.now().year)
#     pass # Placeholder if not implementing now

# --- KEEP Existing File Download Route ---
@app.route("/download/<path:filepath>")
def download(filepath):
    """ Serves files from UPLOAD_FOLDER, handling subdirectories securely. """
    # (Keep existing download function code)
    app.logger.info(f"Download request received for path: '{filepath}'")
    normalized_path = os.path.normpath(filepath)
    if '..' in normalized_path.split(os.sep) or normalized_path.startswith((os.sep, '/')):
         app.logger.warning(f"Download rejected for potentially unsafe path: {filepath} (normalized: {normalized_path})")
         abort(400, "Invalid file path.")
    app.logger.info(f"Attempting download via send_from_directory for path: '{filepath}' relative to '{UPLOAD_FOLDER}'")
    try:
        return send_from_directory( directory=str(UPLOAD_FOLDER), path=filepath, as_attachment=True )
    except (FileNotFoundError, NotFound) as e:
         app.logger.warning(f"File not found via send_from_directory for path: '{filepath}' within {UPLOAD_FOLDER}. Error: {e}")
         abort(404, "File not found.")
    except BadRequest as e:
        app.logger.error(f"Bad Request during file download attempt for '{filepath}': {e}", exc_info=True)
        abort(400, "Invalid request.")
    except Exception as e:
         app.logger.error(f"Error sending file for path '{filepath}': {e}", exc_info=True)
         if isinstance(e, PermissionError): error_msg, http_status = "Could not send file due to server permission error.", 500
         elif isinstance(e, IsADirectoryError): error_msg, http_status = "The requested path points to a directory, not a downloadable file.", 400
         else: error_msg, http_status = "Could not send file due to an internal server error.", 500
         abort(http_status, description=error_msg)


# --- KEEP Existing JSON API Routes ---
@app.route("/api/models", methods=["GET"])
def api_list_models():
    """ API endpoint to list all models in JSON format. """
    # (Keep existing api_list_models function code)
    models = []
    cur = None
    try:
        cur = get_db_cursor()
        cur.execute("SELECT * FROM gapfill_models ORDER BY id DESC")
        models = dict_rows(cur)
        return jsonify(models)
    except (mariadb.Error, mariadb.InterfaceError, mariadb.OperationalError) as db_e:
        app.logger.error(f"API DB error in api_list_models(): {db_e}", exc_info=True)
        return jsonify(error=f"Database error: Failed to retrieve models."), 500
    except Exception as e:
        app.logger.error(f"API Exception in api_list_models(): {e}", exc_info=True)
        return jsonify(error="Internal server error listing models"), 500
    finally:
        if cur:
            try: cur.close()
            except mariadb.Error as e: app.logger.error(f"Error closing cursor in api_list_models(): {e}", exc_info=True)

@app.route("/api/models", methods=["POST"])
def api_create_model():
    """ API endpoint to upload model file (XML/TSV) and optional associated TSV files. """
    # (Keep existing api_create_model function code from previous step)
    saved_files_paths = [] # Track Path objects of saved files for cleanup
    main_file_dest = None
    try:
        if "modelUpload" not in request.files: return jsonify(error="No main model file part ('modelUpload') provided."), 400
        main_file = request.files["modelUpload"]
        if not main_file or not main_file.filename: return jsonify(error="No main model file selected or filename missing."), 400
        main_filename = secure_filename(main_file.filename)
        if not main_filename: return jsonify(error="Invalid main model filename (became empty after securing)."), 400
        main_ext = Path(main_filename).suffix.lower()
        if main_ext not in ALLOWED_EXTENSIONS: return jsonify(error=f"Invalid main file type '{main_ext}'. Only {', '.join(ALLOWED_EXTENSIONS)} allowed."), 400

        if main_ext == ".xml": main_file_subdir = 'xml_files'
        elif main_ext == ".tsv": main_file_subdir = 'main_tsv_files'
        else: main_file_subdir = None

        if main_file_subdir:
            main_file_relative_path = (Path(main_file_subdir) / main_filename).as_posix()
            main_file_dest = UPLOAD_FOLDER / main_file_subdir / main_filename
            (UPLOAD_FOLDER / main_file_subdir).mkdir(parents=True, exist_ok=True)
            app.logger.info(f"Determined subdirectory for main file: {main_file_subdir}")
        else:
            main_file_relative_path = main_filename
            main_file_dest = UPLOAD_FOLDER / main_filename
            app.logger.info("Saving main file to uploads root.")
        app.logger.info(f"Main file destination: {main_file_dest}, Relative path for DB: {main_file_relative_path}")

        if main_file_dest.exists(): return jsonify(error=f"Main file '{main_filename}' already exists at '{main_file_relative_path}'. Upload cancelled."), 409

        try:
            main_file.save(str(main_file_dest))
            saved_files_paths.append(main_file_dest)
            app.logger.info(f"Main file '{main_filename}' saved successfully to {main_file_dest}")
        except Exception as save_e: raise IOError(f"Failed to save main model file: {save_e}")

        optional_files_config = { 'growth_file_upload': {'subdir': 'growth_file', 'db_column': 'growth_file'}, 'biomass_5mM_upload': {'subdir': '5mM', 'db_column': 'biomass_file_5mM'}, 'biomass_20mM_upload':{'subdir': '20mM', 'db_column': 'biomass_file_20mM'} }
        optional_file_paths_for_db = { v['db_column']: None for v in optional_files_config.values() }
        app.logger.debug(f"Processing optional files. Initial paths: {optional_file_paths_for_db}")
        for input_name, config in optional_files_config.items():
             if input_name in request.files and request.files[input_name].filename:
                 opt_file = request.files[input_name]; opt_filename = secure_filename(opt_file.filename)
                 app.logger.debug(f"Found optional file for {input_name}: '{opt_filename}'")
                 if not opt_filename: continue
                 if not opt_filename.lower().endswith('.tsv'): app.logger.warning(f"Optional file '{opt_filename}' for {input_name} is not .tsv. Skipping."); continue
                 subdir_name = config['subdir']; subdir_path = UPLOAD_FOLDER / subdir_name; opt_dest = subdir_path / opt_filename
                 app.logger.debug(f"Optional file destination target: {opt_dest}")
                 if opt_dest.exists():
                     app.logger.warning(f"Optional file '{opt_filename}' already exists in {subdir_name}. Using existing path.")
                     relative_path = (Path(subdir_name) / opt_filename).as_posix()
                     optional_file_paths_for_db[config['db_column']] = relative_path
                     app.logger.debug(f"Set DB path for {config['db_column']} to existing: {relative_path}")
                     continue
                 try:
                     app.logger.debug(f"Ensuring subdirectory exists: {subdir_path}")
                     subdir_path.mkdir(parents=True, exist_ok=True)
                     app.logger.debug(f"Attempting to save optional file to: {opt_dest}")
                     opt_file.save(str(opt_dest)); saved_files_paths.append(opt_dest)
                     app.logger.info(f"Optional file '{opt_filename}' saved to {opt_dest}")
                     relative_path = (Path(subdir_name) / opt_filename).as_posix()
                     optional_file_paths_for_db[config['db_column']] = relative_path
                     app.logger.debug(f"Set DB path for {config['db_column']} to new: {relative_path}")
                 except Exception as save_e: app.logger.error(f"Error saving optional file {opt_filename} to {opt_dest}: {save_e}", exc_info=True)
             else: app.logger.debug(f"No file provided or empty filename for optional input: {input_name}")

        form_field_keys = [ "growth_media", "gapfill_algorithm", "annotation_tool", "growth_data" ]
        form_data = {fld: request.form.get(fld) for fld in form_field_keys}
        app.logger.debug(f"Collected form metadata: {form_data}")

        meta = {
            "Species_Name": "P.simiae",
            "growth_media": form_data.get("growth_media"),
            "gapfill_algorithm": form_data.get("gapfill_algorithm"),
            "annotation_tool": form_data.get("annotation_tool"),
            "file_name": main_filename,
            "file_link": main_file_relative_path,
            "growth_data": form_data.get("growth_data"),
            "growth_file": optional_file_paths_for_db.get('growth_file'),
            "biomass_file_5mM": optional_file_paths_for_db.get('biomass_file_5mM'),
            "biomass_file_20mM": optional_file_paths_for_db.get('biomass_file_20mM'),
            "Biomass_RCH1": None,
        }
        app.logger.debug(f"Complete meta dictionary prepared for DB insert: {meta}")

        cur = None; conn_local = None
        try:
            app.logger.info("Attempting to insert record into database.")
            cur = get_db_cursor(); conn_local = conn
            new_id = insert_gapfill_row(cur, meta)
            conn_local.commit()
            app.logger.info(f"Successfully inserted DB record ID {new_id} referencing file '{main_filename}'.")
            response_meta = { "id": new_id, "file_name": meta.get("file_name"), "message": "Upload successful." }
            return jsonify(response_meta), 201
        except (mariadb.Error, mariadb.IntegrityError) as db_e:
            app.logger.error(f"DB error on insert/commit: {db_e}", exc_info=True)
            if conn_local:
                 try: conn_local.rollback()
                 except mariadb.Error as rb_e: app.logger.error(f"Rollback failed: {rb_e}")
            raise db_e

    except Exception as e:
        app.logger.error(f"Error processing upload request in outer try-except: {e}", exc_info=True)
        if conn:
            try:
                if not getattr(conn, '_closed', True): conn.rollback()
            except mariadb.Error as rb_e: app.logger.error(f"Outer rollback failed: {rb_e}")
        app.logger.warning(f"Initiating file cleanup due to error: {e}")
        app.logger.debug(f"Files to potentially clean up: {saved_files_paths}")
        for file_path_obj in saved_files_paths:
            try:
                file_path = Path(file_path_obj)
                if file_path.is_file(): file_path.unlink(); app.logger.info(f"Cleaned up file: {file_path}")
                elif file_path.exists(): app.logger.warning(f"Cleanup skipped: Path exists but is not a file: {file_path}")
            except Exception as del_e: app.logger.error(f"Could not delete file '{file_path_obj}' during cleanup: {del_e}", exc_info=True)

        status_code = 500; error_message = "An unexpected internal server error occurred during upload."
        if isinstance(e, mariadb.IntegrityError): error_message, status_code = str(e), 400
        elif isinstance(e, mariadb.Error): error_message = f"Database operation failed: {e}"
        elif isinstance(e, IOError): error_message = str(e)
        elif isinstance(e, FileExistsError): error_message, status_code = str(e), 409
        elif isinstance(e, mariadb.OperationalError): error_message, status_code = f"Database connection error: {e}", 503
        return jsonify(error=error_message), status_code
    finally:
        if 'cur' in locals() and cur and not getattr(cur, 'closed', True):
             try: cur.close()
             except mariadb.Error as e: app.logger.error(f"Error closing cursor: {e}", exc_info=True)

@app.route('/visualization')
def functionality():
    return render_template('functionality.html', current_year=datetime.now().year)

# --- Run the App ---
if __name__ == "__main__":
    # Example: python app2.py (if file saved as app2.py)
    app.run(host="0.0.0.0", port=5001, debug=True) # Set debug=False for production