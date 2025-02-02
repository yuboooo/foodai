# __import__('pysqlite3')
# import sys
# import pysqlite3
# sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

from preprocess import encode_image
from agents import agent1_food_image_caption, agent2_nutrition_augmentation
import chromadb
import chromadb.config
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
import streamlit as st
import boto3
from PIL import Image
import os
import pandas as pd
from preprocess import upload_image
import streamlit as st
import streamlit_authenticator as stauth

from streamlit_google_auth import Authenticate
from mongodb import MongoDB
import datetime

authenticator = Authenticate(
    secret_credentials_path='./.streamlit/google_credentials.json',
    cookie_name='my_cookie_name',
    cookie_key='this_is_secret',
    redirect_uri='http://localhost:5173',
)

authenticator.check_authentification()

# Create the login button
authenticator.login()

if st.session_state['connected']:
    st.image(st.session_state['user_info'].get('picture'))
    st.write('Hello, '+ st.session_state['user_info'].get('name'))
    st.write('Your email is '+ st.session_state['user_info'].get('email'))
    if st.button('Log out'):
        authenticator.logout()
else:
    st.write("Please log in to continue.")

OPENAI_API_KEY = st.secrets["general"]["OPENAI_API_KEY"]
# def get_db_json():
#     return Chroma(
#         collection_name="food_items_collection",
#         embedding_function=OpenAIEmbeddings(model="text-embedding-3-large"),
#         persist_directory="../data/food_db/vector_db_json"
#     )

def download_s3_bucket(bucket_name, local_dir):
    # Create an S3 client
    s3 = boto3.client(
        's3',
        aws_access_key_id=st.secrets["aws"]["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["aws"]["AWS_SECRET_ACCESS_KEY"],
        region_name=st.secrets["aws"]["AWS_DEFAULT_REGION"]
    )

    paginator = s3.get_paginator('list_objects_v2')
    operation_parameters = {'Bucket': bucket_name}
    
    for page in paginator.paginate(**operation_parameters):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                local_file_path = os.path.join(local_dir, key)

                # Create local directory structure if it doesn't exist
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

                # Download the file
                print(f"Downloading {key} to {local_file_path}")
                s3.download_file(bucket_name, key, local_file_path)

# Function to load Chroma database
def get_db_json():
    # Define S3 and local paths
    bucket_name = "food-ai-db" 
    local_dir = "../data/food_db_cloud/" 

    # Call the function
    download_s3_bucket(bucket_name, local_dir)

    db_path = os.path.join(local_dir, "vector_db_json")

    # Load the Chroma database
    return Chroma(
        collection_name="food_items_collection",
        embedding_function=OpenAIEmbeddings(model="text-embedding-3-large", api_key=st.secrets["general"]["OPENAI_API_KEY"]),
        persist_directory=db_path
    )

def save_analysis_to_db(email, image_data, ingredients, nutrition_info, nutrition_df, augmented_info):
    """
    Save the food analysis results to MongoDB
    """
    try:
        with MongoDB() as mongo:
            analysis_data = {
                "date": datetime.datetime.utcnow(),
                "image": image_data,
                "ingredients": ingredients,
                "nutrition_info": nutrition_info,
                "nutrition_df": nutrition_df.to_dict() if nutrition_df is not None else {},
                "augmented_info": augmented_info
            }
            
            # Update user document, adding new analysis to food_history
            result = mongo.users.update_one(
                {"email": email},
                {
                    "$setOnInsert": {
                        "email": email,
                        "created_at": datetime.datetime.utcnow()
                    },
                    "$push": {
                        "food_history": analysis_data
                    }
                },
                upsert=True
            )
            
            return True, "Analysis saved successfully!"
            
    except Exception as e:
        st.error(f"Error saving to database: {str(e)}")
        return False, str(e)

if __name__ == "__main__":

    # Streamlit app
    st.title("🍎 Food AI")

    # Initialize empty sidebar
    st.sidebar.empty()

    st.markdown("Analyze your food and get detailed nutritional insights! 🎉")
    st.header("📸 Upload a Food Image")
    uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "png", "jpeg"])

    if uploaded_file is None:
        st.info("Please upload a JPG, PNG, or JPEG image of your food to get started!")
    else:
        image = Image.open(uploaded_file)
        upload_image(uploaded_file)
        st.image(image, caption="Uploaded Food Image", use_container_width=True)

        # Encode image and extract ingredients
        with st.spinner("Processing image to extract food ingredients..."):
            encoded_image = encode_image(uploaded_file)
            ingredients = agent1_food_image_caption(encoded_image)

        if ingredients[0] == 'False':
            st.error("Sorry, we couldn't identify the food in the image. Please try again with a clearer image.")
            st.stop()

        st.subheader("🍴 Extracted Food Ingredients")
        st.write(ingredients)

        with st.spinner("Fetching nutrition information for ingredients..."):
            # Get the database
            db = get_db_json()


            # Retrieve nutrition info for each ingredient
            nutrition_info = {}
            display_info = {}
            for ingredient in ingredients:
                similar_doc = db.similarity_search(ingredient, k=1)
                food_description = similar_doc[0].page_content if similar_doc else None
                metadata = similar_doc[0].metadata
                display_info[ingredient] = metadata
                nutrition_info[food_description] = metadata  # Use ingredient as the key

        # Prepare a cleaner table
        st.subheader("🍽️ Nutrition Facts for Each Ingredient (per 100g)")

        # Convert nutrition info to a DataFrame for better display
        nutrition_df = pd.DataFrame.from_dict(display_info, orient='index').reset_index()
        nutrition_df.columns = ["Ingredient", "Carbohydrate (g)", "Energy (kcal)", "Protein (g)", "Fat (g)"]

        # Customize the DataFrame for a better display
        nutrition_df["Carbohydrate (g)"] = nutrition_df["Carbohydrate (g)"].apply(lambda x: x.split()[0])
        nutrition_df["Protein (g)"] = nutrition_df["Protein (g)"].apply(lambda x: x.split()[0])
        nutrition_df["Fat (g)"] = nutrition_df["Fat (g)"].apply(lambda x: x.split()[0])
        nutrition_df["Energy (kcal)"] = nutrition_df["Energy (kcal)"].apply(lambda x: x.split()[0])

        # Display as a pretty table in Streamlit
        st.table(nutrition_df)


        # # Augmented nutrition data
        # st.write("Generating augmented nutrition information...")
        # nutrition_augmentation = agent2_nutrition_augmentation(encoded_image, nutrition_info)
        # st.subheader("Augmented Nutrition Information")
        # st.write(nutrition_augmentation)


        # Augmented Nutrition Data
        st.subheader("🌟 Augmented Nutrition Information")
        st.markdown("""
        Here, we enhance the basic nutrition facts with additional insights, 
        combining data and analysis to provide you with a richer understanding of your food choices.
        """)

        # Generate augmented nutrition information
        with st.spinner("Generating augmented nutrition information..."):
            nutrition_augmentation = agent2_nutrition_augmentation(encoded_image, nutrition_info, ingredients)

        # Display the augmented information with better formatting
        st.markdown(f"""{nutrition_augmentation}""")




        # Add explanation and citation
        st.subheader("📚 Source Information")
        st.markdown("""
        The nutritional facts displayed above are sourced from the **USDA SRLegacy Database**. 
        Our system identifies the most similar food descriptions in the database based on the ingredients we identified. 
        While we strive to make the matches as accurate as possible, they might not always perfectly reflect the exact nutrition of your specific ingredient.
        We are working to improve our data and algorithms in future versions.

        Below are the matched descriptions from the USDA SRLegacy Database for your reference:
        """)

        # Display matched descriptions and source citation

        with st.expander("View USDA Food Central Data Sources"):
            for ingredient, description in nutrition_info.items():
                st.write(f"- **{ingredient}**:  {description}.")

        if st.session_state.get('connected', False):
            email = st.session_state['user_info'].get('email')
            
            # Add a save button
            if st.button("Save Analysis"):
                try:
                    # Convert uploaded image to bytes for storage
                    uploaded_file.seek(0)
                    image_data = uploaded_file.read()
                    
                    # Sample data structure for testing
                    sample_ingredients = [
                        "chicken breast",
                        "brown rice",
                        "broccoli"
                    ]
                    
                    sample_nutrition_info = {
                        "calories": "450 kcal",
                        "protein": "35g",
                        "carbs": "45g",
                        "fat": "15g"
                    }
                    
                    sample_text_summary = """
                    This meal is a balanced combination of lean protein, complex carbohydrates, and vegetables.
                    The chicken breast provides essential protein, the brown rice offers sustained energy,
                    and the broccoli adds important vitamins and fiber to the meal.
                    """
                    
                    # Create MongoDB instance and save
                    mongo = MongoDB()
                    mongo.save_analysis(
                        email=email,
                        image_data=image_data,
                        ingredients=sample_ingredients,
                        final_nutrition_info=sample_nutrition_info,
                        text_summary=sample_text_summary
                    )
                    
                    st.success("Analysis saved successfully!")
                    
                except Exception as e:
                    st.error(f"Error saving to database: {str(e)}")
        else:
            st.warning("Please log in to save your analysis.")