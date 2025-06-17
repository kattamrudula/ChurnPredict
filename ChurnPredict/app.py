
from collections import Counter
from flask import jsonify
from flask import render_template, url_for, json, session
from flask_cors import CORS, cross_origin
from flask import Flask, request, send_file, send_from_directory
from pymongo import MongoClient
from dotenv import load_dotenv
import os
from urllib.parse import quote_plus
import certifi
import pandas as pd
import numpy as np
import math

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
cors = CORS(app)

# --- MongoDB Configuration ---
# Get MongoDB URI and DB Name from environment variables
escaped_username = quote_plus(os.getenv("MONGO_USERNAME"))
escaped_password = quote_plus(os.getenv("MONGO_PASSWORD"))
MONGO_URI = os.getenv("MONGO_URI").replace("<db_username>:<db_password>",escaped_username+":"+escaped_password)
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

client = MongoClient(MONGO_URI,tlsCAFile=certifi.where())
#client = MongoClient(MONGO_URI, server_api=ServerApi('1'),tlsCAFile=certifi.where())
db = client[MONGO_DB_NAME] 


@app.route("/")
def index():  
  return render_template('index.html')

@app.route("/ChurnPredict")
def ChurnPredict():  
  return render_template('ChurnPredict.html')

@app.route('/get_all_entities', methods=['GET'])
def get_all_entities():
    try:
        entities_collection = db.Entities
        # Find all documents in the 'Entities' collection without any projection
        # Exclude the default '_id' field (optional, but usually good practice for API responses)
        all_entities_cursor = entities_collection.find({}, {"_id": 0}) 
        
        # Convert the cursor to a list of dictionaries
        all_entities_list = list(all_entities_cursor)
        # print(all_entities_list)
        return jsonify({"entities": all_entities_list}), 200
    except Exception as e:
        print(f"Error fetching all entities: {e}")
        return jsonify({"message": "Failed to fetch all entities", "error": str(e)}), 500

@app.route('/save_entity', methods=['POST'])
def save_entity():
    try:
        entities_collection = db.Entities
        data = request.get_json()

        if not data:
            return jsonify({"message": "No JSON data received"}), 400

        # Validate required fields (optional, but good practice)
        required_fields = ['EntityName', 'Purpose', 'Domain', 'Channels']
        if not all(field in data for field in required_fields):
            return jsonify({"message": "Missing required fields"}), 400

        # Insert the entity data into the 'Entities' collection
        # MongoDB will automatically add an _id field
        result = entities_collection.insert_one(data)

        return jsonify({
            "message": "Entity saved successfully!",
            "entity_id": str(result.inserted_id) # Convert ObjectId to string for JSON response
        }), 201 # 201 Created status code

    except Exception as e:
        print(f"Error saving entity: {e}")
        return jsonify({"message": "Failed to save entity", "error": str(e)}), 500

@app.route('/list_collections', methods=['GET'])
def list_collections():
    try:
        collection_names = db.list_collection_names()
        return jsonify({"collections": collection_names}), 200
    except Exception as e:
        print(f"Error listing collections: {e}")
        return jsonify({"message": "Failed to list collections", "error": str(e)}), 500
    
@app.route('/get_entity_by_name/<entity_name>', methods=['GET'])
def get_entity_by_name(entity_name):
    try:
        entities_collection = db.Entities
        entity = entities_collection.find_one({"EntityName": entity_name}, {"_id": 0})
        if entity:
            return jsonify(entity), 200
        else:
            return jsonify({"message": f"Entity with name '{entity_name}' not found"}), 404
    except Exception as e:
        print(f"Error fetching entity by name: {e}")
        return jsonify({"message": "Failed to fetch entity", "error": str(e)}), 500
    
@app.route('/get_collection_by_name/<collection_name>', methods=['GET'])
def get_collection_by_name(collection_name):
    try:
        data_collection = db[collection_name]
        all_data_cursor = data_collection.find({}, {"_id": 0}) 
        
        # Convert the cursor to a list of dictionaries
        all_data_list = list(all_data_cursor)
        # print(all_entities_list)
        return jsonify({"data": all_data_list}), 200
    except Exception as e:
        print(f"Error fetching all data: {e}")
        return jsonify({"message": "Failed to fetch all data", "error": str(e)}), 500

@app.route('/get_collection_columns/<collection_name>', methods=['GET'])
def get_collection_columns(collection_name):
    try:
        target_collection = db[collection_name]
        
        # Get one document to infer column names
        # Use projection to limit fields if document is large, or fetch all keys
        sample_document = target_collection.find_one({}, {"_id": 0}) 

        if sample_document:
            columns = list(sample_document.keys())
            # Optionally filter out internal MongoDB fields if necessary
            # e.g., columns = [col for col in columns if not col.startswith('_')]
            return jsonify({"columns": columns}), 200
        else:
            return jsonify({"columns": [], "message": f"Collection '{collection_name}' is empty or does not exist."}), 200
    except Exception as e:
        print(f"Error getting columns from collection '{collection_name}': {e}")
        return jsonify({"message": f"Failed to get columns from collection '{collection_name}'", "error": str(e)}), 500

def get_all_field_names_in_collection(collection_name, sample_size=1000):
    try:
        collection = db[collection_name]
        field_names_and_types = {}

        pipeline = [
            {"$sample": {"size": sample_size}},
            {"$project": {
                "arrayofkeyvalue": {
                    "$objectToArray": "$$ROOT"
                }
            }},
            {"$unwind": "$arrayofkeyvalue"},
            {"$project": {
                "field_name": "$arrayofkeyvalue.k",
                "field_type": {"$type": "$arrayofkeyvalue.v"} # Get the BSON type of the value
            }},
            {"$group": {
                "_id": "$field_name", # Group by field name
                "single_type": {"$first": "$field_type"} # Get the first observed type for this field
            }}
        ]
        result = list(collection.aggregate(pipeline))
        types_to_skip = {"date", "timestamp"}
        for item in result:
            field_name = item["_id"]
            observed_type = item["single_type"]

            # --- NEW: Skip if type is date or timestamp ---
            if observed_type in types_to_skip:
                continue # Skip to the next field

            # Apply exclusion filter for ID variants if enabled
            if "ID" in field_name.lower() or field_name == '_id':
                continue # Skip to the next field

            field_names_and_types[field_name] = observed_type

        if '_id' in field_names_and_types:
            del field_names_and_types['_id']

        return field_names_and_types
    except Exception as e:
        print(f"An error occurred while discovering field names: {e}")
        return set()
    
@app.route("/get_distinct_counts_for_charts_dynamic_old/<collection_name>",methods=["GET"])
def get_distinct_counts_for_charts_dynamic_old(collection_name):
    # print(f"Discovering fields in '{collection_name}'...")
    fields_to_analyze = get_all_field_names_in_collection(collection_name, 1000)

    if not fields_to_analyze:
        print("No fields found or an error occurred during field discovery.")
        return {}

    # print(f"Discovered fields: {list(fields_to_analyze)}")
    
    try:
        collection = db[collection_name]
        chart_data = {}
        for field in sorted(list(fields_to_analyze)): # Sort for consistent output
            # print(f"Processing field: '{field}'")
            
            # MongoDB aggregation pipeline to group by the field and count distinct occurrences
            pipeline = [
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                {"$project": {"_id": 0, "label": "$_id", "count": 1}} # Rename _id to label
            ]
            result = list(collection.aggregate(pipeline))
            chart_data[field] = result
        return chart_data

    except Exception as e:
        print(f"An error occurred during distinct count generation: {e}")
        return {}

def transform_numeric_fields(data):
    df = pd.DataFrame(data)
    transformed_df = df.copy()
    divisors_map = {} # To store divisors for each numeric column

    for col in df.columns:
        # Check if the column is numeric
        if pd.api.types.is_numeric_dtype(df[col]):
            max_val = df[col].max()
            divisor = 1

            if max_val == 0:
                divisor = 1
            elif max_val <= 10:
                divisor = 1
            else:
                # Find the smallest power of 10 such that max_val / divisor <= 10
                temp_divisor = 1
                while max_val / temp_divisor > 10:
                    temp_divisor *= 10
                divisor = temp_divisor

            divisors_map[col] = divisor # Store the divisor

            # Apply the transformation (ceil after division)
            if divisor == 1:
                transformed_df[col] = np.ceil(df[col])
            else:
                transformed_df[col] = np.ceil(df[col] / divisor)

    return transformed_df.to_dict(orient='records'), divisors_map
  
@app.route("/get_distinct_counts_for_charts_dynamic/<collection_name>",methods=["GET"])
def get_distinct_counts_for_charts_dynamic(collection_name):
    try:
        collection = db[collection_name]
        all_data_cursor = collection.find({}, {"_id": 0}) 
        # Convert the cursor to a list of dictionaries
        all_data_list = list(all_data_cursor)
        all_data_normalised, divisors_map = transform_numeric_fields(all_data_list)
        chart_data = []
        if all_data_normalised:
            all_fields = all_data_normalised[0].keys()

            for field in all_fields:
                if "ID" in field or "Date" in field:
                    continue # Skip excluded fields

                field_values = [record.get(field) for record in all_data_normalised if record.get(field) is not None]

                if not field_values:
                    continue # Skip fields with no values

                current_chart_item = {
                    "fieldName": field,
                    "chartdata": [],
                    "divisor": 1 # Default divisor for non-numeric/categorical fields
                }

                # Determine if the field was numeric and transformed
                if field in divisors_map:
                    current_chart_item["divisor"] = divisors_map[field]
                    # For numeric fields, count occurrences of the transformed values (1-10)
                    distinct_counts = Counter(field_values)
                    for label, count in distinct_counts.items():
                        # Ensure labels are strings for charting, convert float to int string
                        current_chart_item["chartdata"].append({"label": str(int(label)), "count": count})
                else:
                    # It's a categorical field
                    distinct_counts = Counter(field_values)
                    for label, count in distinct_counts.items():
                        current_chart_item["chartdata"].append({"label": str(label), "count": count})

                chart_data.append(current_chart_item)

        return jsonify({"status": "success", "data": chart_data}), 200
        

    except Exception as e:
        print(f"An error occurred during distinct count generation: {e}")
        return {}

@app.route('/get_domain_fields_mapping', methods=['GET'])
def get_domain_fields_mapping():
    try:
        # In a real application, this data would likely come from a database
        domain_data = [
            {"Domain": "Telecom", "Fields": ['CustomerID','CoverageArea','NetworkStrength','MonthlyCost','ContractType','DataIncluded','PaymentMethod','InternationalCalls','CloudStorage','Streaming','InternetService','TechSupport','DeviceProtection','Churn']},
            {"Domain": "Retail", "Fields": ['Customer_ID','Age','Gender','Annual_Income','Total_Spend','Years_as_Customer','Num_of_Purchases','Average_Transaction_Amount','Num_of_Returns','Num_of_Support_Contacts','Satisfaction_Score','Last_Purchase_Days_Ago','Email_Opt_In','Promotion_Response','Churn']},
            {"Domain": "Clinical", "Fields": ['PatientID','AppointmentID','HospitalID','AppointmentDate','TreatmentCost','DistanceToHospital','TravelTime','TrafficCondition','SanitationRating','StaffSkillRating','Department','PreviousVisits','FollowUpRecommended','Churn']},
            {"Domain": "Insurance", "Fields": ['CustomerID','PolicyID','InsuranceType','PolicyStartDate','PolicyEndDate','CoverageAmount','PremiumCost','MinimalPayment','PaymentFrequency','PaymentMethod','ClaimsMade','PolicyStatus','Tenure','Churn']},
            {"Domain": "Banking", "Fields": ['CustomerID','AccountType','BranchCoverage','MobileBankingEnabled','FreeWithdrawals','FreeDDs','MinimumBalance','CurrentBalance','AccountFeatures','Tenure','IsSalaryAccount','CreditCard','OnlineBankingEnabled','Churn']},
            {"Domain": "Restaurant", "Fields": ['CustomerID','Age','Gender','DistanceFromRestaurant','LastVisitDate','UsedReservationSystem','UsedDeliveryService','PreferredDishCategories','AverageRating','RestaurantType','AverageDishPrice','ParkingAvailability','RatingHygiene','RatingQuality','RatingTimeliness','Churn']},
            {"Domain": "Gaming", "Fields": ['PlayerID','RegistrationDate','Country/Region','AgeGroup','DeviceType','TotalPlaytimeHours','LevelAchieved','SessionsPlayed','AverageSessionDuration','NumberOfPurchases','FriendsCount','GuildMembership','FeedbackSentiment','InteractiveFeatureUsage','Churn']},
            {"Domain": "Transport", "Fields": ['CustomerID','TripID','TransportMode','Origin','Destination','TripDate','Price','Availability','TravelTime','OnTimePerformance','Volume','RollingAvgVolume','VolumeDropPercent','ConsecutiveDropWeeks','LoyaltyStatus','Churn']},
            {"Domain": "Automobiles", "Fields": ['CustomerID','VehicleID','Make','Model','Year','PurchaseDate','Cost','Mileage','DurabilityRating','SafetyRating','ComfortRating','AestheticsRating','Color','ServiceVisits','LastServiceDate','Recency','Frequency','Tenure','Churn']},
            {"Domain": "Mobiles", "Fields": ['CustomerID','MobileID','Brand','Model','PurchaseDate','Cost','Weight','ScreenSize','Color','Features','Storage','RAM','BatteryCapacity','CameraSpecs','PreviousPurchases','WarrantyStatus','Churn']}
        ]
        return jsonify({"domain_fields": domain_data}), 200
    except Exception as e:
        print(f"Error fetching domain fields mapping: {e}")
        return jsonify({"message": "Failed to fetch domain fields mapping", "error": str(e)}), 500


@app.route('/update_channel_config', methods=['POST'])
def update_channel_config():
    try:
        entities_collection = db.Entities
        data = request.get_json()

        entity_name = data.get('EntityName')
        channel_name = data.get('ChannelName')
        new_schedule = data.get('Schedule')
        new_keywords = data.get('Keywords')

        if not all([entity_name, channel_name, new_schedule is not None, new_keywords is not None]):
            return jsonify({"message": "Missing required fields for update"}), 400

        # Find the entity and update the specific channel's configuration
        # This requires finding the correct channel object within the 'Channels' array
        result = entities_collection.update_one(
            {"EntityName": entity_name, "Channels.name": channel_name},
            {"$set": {
                "Channels.$.schedule": new_schedule,
                "Channels.$.keywords": new_keywords
            }}
        )

        if result.matched_count == 0:
            return jsonify({"message": f"Entity '{entity_name}' or channel '{channel_name}' not found"}), 404
        elif result.modified_count == 0:
            return jsonify({"message": "No changes made, configuration might be the same"}), 200
        else:
            return jsonify({"message": "Channel configuration updated successfully"}), 200

    except Exception as e:
        print(f"Error updating channel config: {e}")
        return jsonify({"message": "Failed to update channel configuration", "error": str(e)}), 500


if __name__ == '__main__':
    server_port = os.environ.get('PORT', '8080')
    app.run(debug=True, port=server_port, host='0.0.0.0')
    





