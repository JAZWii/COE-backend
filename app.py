from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import psycopg2
from psycopg2 import sql
import xml.etree.ElementTree as ET
import io
from flask import Flask
from flask_socketio import SocketIO
import os
from flask import Flask, Response
from flask_socketio import SocketIO
import requests
import subprocess
import traci
import time
import json
from flask import Flask
from flask_socketio import SocketIO
import subprocess
import random
from flask import g
import threading
from flask import Flask, request, jsonify, send_file
from flask import Flask, request, jsonify, g
import threading
import os
import subprocess
import requests


app = Flask(__name__)
active_simulations = {}
simulation_lock = threading.Lock()
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)

DB_HOST = "street-data-db.cl4g82mmcvc0.us-east-1.rds.amazonaws.com"
DB_USER = "admin_user"
DB_PASS = "AWS_Postgres_2025"
DB_NAME = "street_data_db"

LANE_MAPPING = {
    ("King Fahd Road - North of Makkah/Khurais Road", "original"): [0, 1, 2],
    ("King Fahd Road - North of Makkah/Khurais Road", "enhanced"): [0, 1, 2, 3],
    ("Eastern Ring Road - South of Oroubah Road", "original"): [0, 1, 2],
    ("Eastern Ring Road - South of Oroubah Road", "enhanced"): [0, 1, 2],
    ("Eastern Ring Road - South of Omar Ibn Abdulaziz Road", "original"): [0, 1, 2, 3],
    ("Eastern Ring Road - South of Omar Ibn Abdulaziz Road", "enhanced"): [0, 1, 2, 3],
    ("Makkah/Khurais- Um alhammam", "original"): [0, 1, 2],
    ("Makkah/Khurais- Um alhammam", "enhanced"): [0, 1, 2]
}



def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        dbname=DB_NAME
    )

def clear_trip_data(version):
    """Clear existing trip data for the specified version"""
    table_name = f"trip_data_{version}"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {table_name}")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error clearing {table_name}: {e}")
        return False

def clear_summary_data(version):
    """Clear existing summary data for the specified version"""
    table_name = f"summary_data_{version}"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {table_name}")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error clearing {table_name}: {e}")
        return False

def store_trip_data(version, trip_data):
    """Store trip data in the appropriate version table"""
    table_name = f"trip_data_{version}"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        insert_query = f"""
        INSERT INTO {table_name} (
            veh_id, departure, arrival, duration, route_id, street,
            depart_delay, depart_speed, arrival_speed, waiting_time,
            stop_time, time_loss, reroute_no, speed_factor
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.executemany(insert_query, trip_data)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error storing trip data in {table_name}: {e}")
        return False

def store_summary_data(version, summary_data):
    """Store summary data in the appropriate version table"""
    table_name = f"summary_data_{version}"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        insert_query = f"""
        INSERT INTO {table_name} (
            begin_time, end_time, loaded, inserted, running, ended, street,
            mean_waiting_time, mean_travel_time, mean_speed, 
            mean_speed_relative, collisions, teleports, halting, stopped
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.executemany(insert_query, summary_data)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error storing summary data in {table_name}: {e}")
        return False

#Helper functions
def load_network(street_name, version):
    """Load network file for given street and version"""
    try:
        street_dir = get_street_directory(street_name, version)
        network_file = os.path.join(street_dir, f"network_{sanitize_filename(street_name)}_{version}.xml")
        if not os.path.exists(network_file):
            raise FileNotFoundError(f"Network file not found: {network_file}")
        return network_file
    except Exception as e:
        print(f"Network loading error: {str(e)}")
        return None

def generate_trips(street_name, timestamp, version):
    """Generate trips and store in DB"""
    try:
        # Your existing trip generation logic
        trip_file = f"trips_{sanitize_filename(street_name)}_{version}.xml"
        # ... (implementation details)
        return trip_file
    except Exception as e:
        print(f"Trip generation error: {str(e)}")
        return None

def run_sumo_simulation(config_file):
    """Run SUMO simulation with given config"""
    try:
        result = subprocess.run(["sumo", "-c", config_file], check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"SUMO error: {str(e)}")
        return False

@app.route("/health")
def health_check():
    try:
        conn = get_db_connection()
        conn.close()
        return {"status": "Database Connected"}, 200
    except Exception as e:
        return {"status": "DB Connection Failed", "error": str(e)}, 500

@app.route("/data", methods=["GET"])
def get_data():
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))
        street_filter = request.args.get("street", None)
        date_filter = request.args.get("date", None)  # Single date filter
        offset = (page - 1) * per_page

        conn = get_db_connection()
        cursor = conn.cursor()

        # Base query
        base_query = "SELECT timestamp, street, vehicle_count, avg_speed, max_speed_limit FROM street_data"
        count_query = "SELECT COUNT(*) FROM street_data"
        
        filters = []
        params = []

        if street_filter:
            filters.append("street = %s")
            params.append(street_filter)

        if date_filter:
            filters.append("DATE(timestamp) = %s")  # Ensures filtering by date only
            params.append(date_filter)

        if filters:
            filter_query = " WHERE " + " AND ".join(filters)
            base_query += filter_query
            count_query += filter_query  # Apply same filter for count
        
        # Add sorting & pagination
        base_query += " ORDER BY timestamp ASC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cursor.execute(base_query, params)
        data = cursor.fetchall()

        cursor.execute(count_query, params[:-2])  # Remove pagination params for count query
        total_count = cursor.fetchone()[0]

        conn.close()

        result = [
            {
                "timestamp": row[0],
                "street": row[1],
                "vehicle_count": row[2],
                "avg_speed": row[3],
                "max_speed_limit": row[4],
            }
            for row in data
        ]

        return jsonify({"data": result, "total": total_count}), 200
    except Exception as e:
        import traceback
        print(f"Error in /data endpoint: {str(e)}")
        print("Traceback:")
        print(traceback.format_exc())
        return jsonify({
            "status": "Error fetching data", 
            "error": str(e),
            "query": query,
            "params": params
        }), 500

def sanitize_filename(street_name):
    """Sanitizes a street name to be a valid filename/directory name."""
    return street_name.replace(" ", "_").replace("/", "_").replace("-", "_")

def get_street_directory(street_name, version):
    """Creates and returns a directory for a specific street and version (original/enhanced)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))  # Get the script's directory
    street_safe = sanitize_filename(street_name)  # Sanitize street name
    street_dir = os.path.join(script_dir, "street_data", f"{street_safe}_{version}")  # Folder with version

    if not os.path.exists(street_dir):  
        os.makedirs(street_dir)  # ✅ Create directory if it doesn't exist
    
    return street_dir

# Function to generate trip file with time starting from 0
def generate_trip_file(data, street_name, version):
    """Generates a trip file for the specified street and version (original/enhanced)."""

    if not data:
        return None  

    # ✅ Get street directory (with version)
    street_dir = get_street_directory(street_name, version)

    # ✅ Define file path
    trip_file_path = os.path.join(street_dir, f"trips_{sanitize_filename(street_name)}_{version}.xml")

    # Set the base time
    earliest_timestamp = min(row[0] for row in data)
    base_time = earliest_timestamp.timestamp()

    street_to_junction_mapping = {
        "King Fahd Road - North of Makkah/Khurais Road": ("160652487#0", "160652487#2"),
        "Eastern Ring Road - South of Oroubah Road": ("592833059#0", "592833059#2"),
        "Eastern Ring Road - South of Omar Ibn Abdulaziz Road": ("265060215#0", "265060215#2"),
        "Makkah/Khurais- Um alhammam": ("92072651", "53859741#0-AddedOnRampEdge")
    }

    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="car", vClass="passenger", color="1,0,0")
    trip_id = 1

    for row in data:
        timestamp, street, vehicle_count, avg_speed, max_speed = row
        origin, destination = street_to_junction_mapping.get(street, (None, None))

        if origin is None or destination is None:
            continue  

        departure_time = int(timestamp.timestamp() - base_time)

        for i in range(vehicle_count):
            ET.SubElement(root, "trip", id=f"trip_{trip_id}", depart=str(departure_time), from_=origin, to=destination)
            trip_id += 1  

    tree = ET.ElementTree(root)
    tree.write(trip_file_path, encoding="utf-8", xml_declaration=True)

    print(f"✔ Trip file saved at: {trip_file_path}")
    return trip_file_path  

# New endpoint to generate trips with date and street filtering
@app.route("/generate_trips", methods=["GET"])
def generate_trips():
    try:
        date_filter = request.args.get("timestamp")
        street_filter = request.args.get("street")
        version = request.args.get("version", "original")  # Default to "original"

        if not date_filter or not street_filter:
            return jsonify({"status": "Error", "error": "Missing required parameters: date and street are mandatory"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        query = "SELECT timestamp, street, vehicle_count, avg_speed, max_speed_limit FROM street_data WHERE DATE(timestamp) = %s AND street = %s ORDER BY timestamp"
        cursor.execute(query, (date_filter, street_filter))
        result = cursor.fetchall()
        conn.close()

        if not result:
            return jsonify({"status": "No data found for the given date and street"}), 404

        # Clear existing data before generating new data
        clear_trip_data(version)
        clear_summary_data(version)

        # Generate the trip file
        trip_file_path = generate_trip_file(result, street_filter, version)

        return send_file(trip_file_path, as_attachment=True, download_name=f"trips_{sanitize_filename(street_filter)}_{version}.xml", mimetype="application/xml")

    except Exception as e:
        return jsonify({"status": "Error generating trips", "error": str(e)}), 500

def apply_random_lane_assignment(route_file, modified_route_file, street_name, version):
    """Applies random departure lane assignments to vehicles based on street/version."""

    try:
        # Load the route file
        tree = ET.parse(route_file)
        root = tree.getroot()

        # ✅ Get the correct lane list
        available_lanes = LANE_MAPPING.get((street_name, version), [0])  # Default to [0] if not mapped

        # Assign a random lane to each vehicle
        for vehicle in root.findall("vehicle"):
            random_lane = str(random.choice(available_lanes))
            vehicle.set("departLane", random_lane)

        # Save modified route file
        tree.write(modified_route_file, encoding="utf-8", xml_declaration=True)
        print(f"✔ Random lane assignment applied with {len(available_lanes)} lanes. Saved as {modified_route_file}")

    except Exception as e:
        print(f"❌ Error modifying lanes: {e}")

@app.route("/generate_routes", methods=["GET"])
def generate_routes():
    try:
        street_filter = request.args.get("street")
        version = request.args.get("version", "original")

        if not street_filter:
            return jsonify({"status": "Error", "error": "Missing street name"}), 400

        street_dir = get_street_directory(street_filter, version)

        trip_file = os.path.join(street_dir, f"trips_{sanitize_filename(street_filter)}_{version}.xml")
        route_file = os.path.join(street_dir, f"routes_{sanitize_filename(street_filter)}_{version}.xml")
        modified_route_file = os.path.join(street_dir, f"routes_with_random_lanes_{sanitize_filename(street_filter)}_{version}.xml")
        network_file = os.path.join(street_dir, f"network_{sanitize_filename(street_filter)}_{version}.xml")

        if not os.path.exists(trip_file):
            return jsonify({"status": "error", "message": f"Trip file for {street_filter} ({version}) not found"}), 404

        subprocess.run(["duarouter", "--trip-files", trip_file, "--net-file", network_file, "--output-file", route_file], check=True)

        # ✅ Pass street name and version
        apply_random_lane_assignment(route_file, modified_route_file, street_filter, version)

        return send_file(modified_route_file, as_attachment=True,
                         download_name=f"routes_with_random_lanes_{sanitize_filename(street_filter)}_{version}.xml",
                         mimetype="application/xml")

    except subprocess.CalledProcessError as e:
        return jsonify({"status": "error", "message": f"duarouter execution failed: {e}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
def generate_sumo_config(street_name, version="original"):
    """Generates a SUMO configuration file for a specific street and version."""
    street_dir = get_street_directory(street_name, version)
    sanitized = sanitize_filename(street_name)

    # Define file paths
    network_file = os.path.join(street_dir, f"network_{sanitized}_{version}.xml")
    route_file = os.path.join(street_dir, f"routes_with_random_lanes_{sanitized}_{version}.xml")
    config_file = os.path.join(street_dir, f"osm_{sanitized}_{version}.sumocfg.xml")

    if not os.path.exists(network_file):
        print(f"❌ ERROR: Network file {network_file} not found. Please add it to {street_dir}.")
        return None

    if not os.path.exists(route_file):
        print(f"❌ ERROR: Route file {route_file} not found. Generate routes first.")
        return None

    root = ET.Element("configuration")

    # Input files
    input_element = ET.SubElement(root, "input")
    ET.SubElement(input_element, "net-file", value=network_file)
    ET.SubElement(input_element, "route-files", value=route_file)

    # Time
    time_element = ET.SubElement(root, "time")
    ET.SubElement(time_element, "begin", value="0")
    ET.SubElement(time_element, "end", value="52200")

    # Simulation
    sim_element = ET.SubElement(root, "simulation")
    ET.SubElement(sim_element, "step-length", value="1.0")

    # Output with custom naming
    output_element = ET.SubElement(root, "output")
    ET.SubElement(output_element, "summary-output",
                  value=f"summary_{sanitized}_{version}.xml",
                  synonymes="summary",
                  type="FILE",
                  help="Save aggregated vehicle departure info into FILE")
    ET.SubElement(output_element, "tripinfo-output",
                  value=f"tripinfo_{sanitized}_{version}.xml",
                  type="BOOL",
                  help="Write tripinfo output for vehicles which have not arrived at simulation end")

    # Save the configuration file
    tree = ET.ElementTree(root)
    tree.write(config_file, encoding="utf-8", xml_declaration=True)

    print(f"✔ SUMO configuration file saved: {config_file}")
    return config_file

@app.route("/generate_config", methods=["GET"])
def generate_config():
    try:
        street_filter = request.args.get("street")
        version = request.args.get("version", "original")  # Default to "original"

        if not street_filter:
            return jsonify({"status": "Error", "error": "Missing street name"}), 400

        config_path = generate_sumo_config(street_filter, version)  # ✅ Pass both street and version

        # ❌ If config file is None, return an error
        if config_path is None or not os.path.exists(config_path):
            return jsonify({"status": "Error", "message": f"Failed to generate SUMO config for {street_filter} ({version}). Ensure network and route files exist."}), 500

        return send_file(config_path, as_attachment=True, download_name=f"osm_{sanitize_filename(street_filter)}_{version}.sumocfg.xml", mimetype="application/xml")

    except Exception as e:
        return jsonify({"status": "Error", "message": str(e)}), 500

def parse_tripinfo_xml(xml_path, street_name):
    """Parse tripinfo XML file and extract data for database storage"""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        trip_data = []
        for trip in root.findall('tripinfo'):
            trip_data.append((
                trip.get('id'),
                float(trip.get('depart')),
                float(trip.get('arrival')),
                float(trip.get('duration')),
                trip.get('route'),
                street_name,
                float(trip.get('departDelay', 0)),
                float(trip.get('departSpeed', 0)),
                float(trip.get('arrivalSpeed', 0)),
                float(trip.get('waitingTime', 0)),
                float(trip.get('stopTime', 0)),
                float(trip.get('timeLoss', 0)),
                int(trip.get('rerouteNo', 0)),
                float(trip.get('speedFactor', 1.0))
            ))
        return trip_data
    except Exception as e:
        print(f"Error parsing tripinfo XML: {e}")
        return None

def parse_summary_xml(xml_path, street_name):
    """Parse summary XML file and extract data for database storage"""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        summary_data = []
        for interval in root.findall('interval'):
            summary_data.append((
                float(interval.get('begin')),
                float(interval.get('end')),
                int(interval.get('loaded', 0)),
                int(interval.get('inserted', 0)),
                int(interval.get('running', 0)),
                int(interval.get('ended', 0)),
                street_name,
                float(interval.get('meanWaitingTime', 0)),
                float(interval.get('mean_travelTime', 0)),
                float(interval.get('meanSpeed', 0)),
                float(interval.get('meanSpeedRelative', 0)),
                int(interval.get('collisions', 0)),
                int(interval.get('teleports', 0)),
                int(interval.get('halting', 0)),
                int(interval.get('stopped', 0))
            ))
        return summary_data
    except Exception as e:
        print(f"Error parsing summary XML: {e}")
        return None

    encoded_street = street_name.replace(" ", "%20").replace("/", "%2F")
    
    # ✅ 1. Generate Trips
    trip_url = f"http://127.0.0.1:5000/generate_trips?timestamp={timestamp}&street={encoded_street}&version={version}"
    response = requests.get(trip_url)
    if response.status_code != 200:
        print(f"❌ Trip generation failed: {response.json()}")
        return
    
    print(f"✔ Trip file generated successfully for {street_name} ({version})!")

    # ✅ 2. Generate Routes
    route_url = f"http://127.0.0.1:5000/generate_routes?street={encoded_street}&version={version}"
    response = requests.get(route_url)
    if response.status_code != 200:
        print(f"❌ Route generation failed: {response.json()}")
        return
    
    print(f"✔ Route file generated successfully for {street_name} ({version})!")

    # ✅ 3. Generate SUMO Configuration
    config_url = f"http://127.0.0.1:5000/generate_config?street={encoded_street}&version={version}"
    response = requests.get(config_url)
    if response.status_code != 200:
        print(f"❌ Config file generation failed: {response.json()}")
        return

    print(f"✔ SUMO configuration file generated successfully for {street_name} ({version})!")

    # ✅ 4. Run SUMO Simulation
    street_dir = get_street_directory(street_name, version)
    config_file = os.path.join(street_dir, f"osm_{sanitize_filename(street_name)}_{version}.sumocfg.xml")

    if not os.path.exists(config_file):
        print(f"❌ SUMO configuration file not found: {config_file}")
        return

    print(f"🚦 Starting SUMO simulation for {street_name} ({version})...")
    subprocess.run(["sumo-gui", "-c", config_file])  # Start SUMO with GUI

# Initialize at module level (not inside a function)
clearing_done = False
@app.route("/run_simulation", methods=["POST"])
def handle_simulation():
    data = request.get_json()
    street = data.get("street")
    timestamp = data.get("timestamp")
    version = data.get("version", "original")

    if not street or not timestamp:
        return jsonify({"error": "Missing street or timestamp"}), 400

    try:
        success = run_full_simulation(street, timestamp, version)
        if success:
            return jsonify({"status": "Simulation completed"}), 200
        return jsonify({"error": "Simulation failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Global flag to track clearing status
def run_full_simulation(street_name, timestamp, version="original"):
    with simulation_lock:
        if street_name in active_simulations:
            return False
        active_simulations[street_name] = True

    try:
        # 1. Network Loading
        print(f"1/5 Loading network for {street_name}")
        network_file = load_network(street_name, version)
        if not network_file:
            raise Exception("Network loading failed")

        # 2. Trips Generation + DB Storage
        print(f"2/5 Generating trips for {street_name}")
        trips_file = generate_trips(street_name, timestamp, version)
        if not trips_file:
            raise Exception("Trip generation failed")

        # 3. Routes Generation
        print(f"3/5 Generating routes for {street_name}")
        routes_file = generate_routes(street_name, version)
        if not routes_file:
            raise Exception("Route generation failed")

        # 4. Config Generation
        print(f"4/5 Generating config for {street_name}")
        config_file = generate_config(street_name, version)
        if not config_file:
            raise Exception("Config generation failed")

        # 5. Run Simulation
        print(f"5/5 Running simulation for {street_name}")
        success = run_sumo_simulation(config_file)
        return success

    except Exception as e:
        print(f"Simulation error: {str(e)}")
        return False
    finally:
        with simulation_lock:
            active_simulations.pop(street_name, None)

# Supported road configurations
ROAD_CONFIGS = {
    "King Fahd Road - North of Makkah/Khurais Road": {
        "versions": ["original", "enhanced"],
        "lanes": {"original": 3, "enhanced": 4}
    },
    "Eastern Ring Road - South of Oroubah Road": {
        "versions": ["original", "enhanced"], 
        "lanes": {"original": 3, "enhanced": 3}
    },
    "Eastern Ring Road - South of Omar Ibn Abdulaziz Road": {
        "versions": ["original", "enhanced"],
        "lanes": {"original": 4, "enhanced": 4} 
    },
    "Makkah/Khurais- Um alhammam": {
        "versions": ["original", "enhanced"],
        "lanes": {"original": 3, "enhanced": 3}
    }
}

@app.route("/get_network", methods=["GET"])
def get_network():
    try:
        street = request.args.get("street")
        version = request.args.get("version", "original")
        
        if not street or street not in ROAD_CONFIGS:
            return jsonify({"error": "Invalid or missing street parameter"}), 400
            
        if version not in ROAD_CONFIGS[street]["versions"]:
            return jsonify({"error": f"Version {version} not supported for {street}"}), 400

        # Get sanitized filename components
        # Handle both underscore and double underscore variations in filenames
        sanitized_street = sanitize_filename(street)
        possible_filenames = [
            f"network_{sanitized_street}_{version}.xml",
            f"network_{sanitized_street.replace('__', '_')}_{version}.xml"
        ]
        
        # Try each possible filename
        for filename in possible_filenames:
            file_path = os.path.join(
                get_street_directory(street, version),
                filename
            )
            if os.path.exists(file_path):
                return send_file(file_path, mimetype="application/xml")

        return jsonify({"error": f"Network file not found for {street} ({version})"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/monthly_congestion_summary", methods=["GET"])
def get_monthly_congestion_summary():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM monthly_congestion_summary ORDER BY recorded_at DESC LIMIT 1")
        data = cursor.fetchone()
        conn.close()
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"status": "Error fetching monthly congestion summary", "error": str(e)}), 500

@app.route("/weekly_congestion_summary", methods=["GET"])
def get_weekly_congestion_summary():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM weekly_congestion_summary ORDER BY recorded_at DESC LIMIT 1")
        data = cursor.fetchone()
        conn.close()
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"status": "Error fetching weekly congestion summary", "error": str(e)}), 500

# Global variable to control simulation state
simulation_active = False


def send_vehicle_positions():
    global simulation_active
    while simulation_active and traci.isLoaded():
        traci.simulationStep()
        vehicle_data = []

        for veh_id in traci.vehicle.getIDList():
            x, y = traci.vehicle.getPosition(veh_id)
            vehicle_data.append({"id": veh_id, "x": x, "y": y})

        socketio.emit("vehicle_positions", json.dumps(vehicle_data))
        time.sleep(0.5)


@app.route("/start_simulation", methods=["POST"])
def start_simulation():
    global simulation_active
    data = request.get_json()
    street = data.get("street")
    version = data.get("version", "original")

    if not street:
        return jsonify({"error": "Missing street parameter"}), 400

    try:
        # Clean up any existing connection
        if simulation_active and 'traci' in globals():
            try:
                traci.close()
            except:
                pass
            simulation_active = False
            time.sleep(0.5)

        # Get config file
        street_dir = get_street_directory(street, version)
        config_file = os.path.join(street_dir, f"osm_{sanitize_filename(street)}_{version}.sumocfg.xml")
        if not os.path.exists(config_file):
            return jsonify({"error": "Config file not found"}), 404

        # Start simulation
        traci.start(["sumo", "-c", config_file])
        simulation_active = True
        
        # Start vehicle updates
        socketio.start_background_task(send_vehicle_positions)

        # Store results after simulation completes
        def store_results():
            time.sleep(1)  # Wait for simulation to complete
            sanitized = sanitize_filename(street)
            
            # Store trip data
            tripinfo_path = os.path.join(street_dir, f"tripinfo_{sanitized}_{version}.xml")
            trip_data = parse_tripinfo_xml(tripinfo_path, street)
            if trip_data:
                store_trip_data(version, trip_data)
            
            # Store summary data
            summary_path = os.path.join(street_dir, f"summary_{sanitized}_{version}.xml")
            summary_data = parse_summary_xml(summary_path, street)
            if summary_data:
                store_summary_data(version, summary_data)

        # Run storage in background
        socketio.start_background_task(store_results)

        return jsonify({
            "status": "Simulation started and data storage initiated",
            "street": street,
            "version": version
        }), 200

    except Exception as e:
        print(f"Simulation error: {str(e)}")
        simulation_active = False
        if 'traci' in globals() and traci.isLoaded():
            try:
                traci.close()
            except:
                pass
        return jsonify({
            "error": "Simulation failed",
            "details": str(e)
        }), 500


@app.route("/stop_simulation", methods=["POST"])
def stop_simulation():
    global simulation_active
    simulation_active = False
    if traci.isLoaded():
        traci.close()
    return jsonify({"status": "Simulation stopped"}), 200


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
